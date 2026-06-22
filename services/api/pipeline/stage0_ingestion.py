"""
Stage 0: Ingestion & Triage
Split PDF into pages, detect text layer, dispatch OCR for scanned pages.
"""
import asyncio
from pathlib import Path
from typing import List, Dict

import httpx
import pdf2image
import pypdf
from pdf2image.exceptions import PDFInfoNotInstalledError, PDFPageCountError

from api.models import PageRecord


async def run(job_id: str, pdf_path: Path, settings) -> List[PageRecord]:
    """
    Returns one PageRecord per page. Scanned pages have image_path set.
    Native pages have text set directly. OCR is dispatched but not awaited here.
    """
    records = []

    try:
        # Open PDF
        pdf_reader = pypdf.PdfReader(str(pdf_path))
        total_pages = len(pdf_reader.pages)

        # Process each page
        for page_num in range(total_pages):
            page_index = page_num  # 0-indexed for pypdf
            page_number = page_num + 1  # 1-indexed for our records

            page = pdf_reader.pages[page_index]
            text = page.extract_text()

            # Determine if page has sufficient text layer (Rule R-01)
            if len(text.strip()) > settings.NATIVE_TEXT_CHAR_THRESHOLD:
                # Native text page
                record = PageRecord(
                    job_id=job_id,
                    page_num=page_number,
                    source="native_text",
                    text=text,
                    char_count=len(text),
                    image_path=None,
                    ocr_blocks=None,
                    ocr_confidence_avg=None,
                )
            else:
                # Scanned page - needs OCR
                # Rasterize the page
                try:
                    images = pdf2image.convert_from_path(
                        pdf_path,
                        dpi=settings.OCR_DPI,
                        first_page=page_number,
                        last_page=page_number,
                        fmt="jpeg",
                    )
                    if images:
                        image = images[0]
                        # Save image
                        job_dir = Path(settings.DATA_DIR) / job_id
                        pages_dir = job_dir / "pages"
                        pages_dir.mkdir(parents=True, exist_ok=True)
                        image_path = pages_dir / f"{page_number:04d}.jpg"
                        image.save(str(image_path), "JPEG")

                        record = PageRecord(
                            job_id=job_id,
                            page_num=page_number,
                            source="ocr",  # Will be updated after OCR
                            text="",  # Will be filled after OCR
                            char_count=0,
                            image_path=str(image_path),
                            ocr_blocks=None,
                            ocr_confidence_avg=None,
                        )
                    else:
                        # Fallback if rasterization fails
                        record = PageRecord(
                            job_id=job_id,
                            page_num=page_number,
                            source="failed_ocr",
                            text="",
                            char_count=0,
                            image_path=None,
                            ocr_blocks=None,
                            ocr_confidence_avg=None,
                        )
                except (PDFInfoNotInstalledError, PDFPageCountError) as e:
                    # Handle rasterization errors
                    record = PageRecord(
                        job_id=job_id,
                        page_num=page_number,
                        source="failed_ocr",
                        text="",
                        char_count=0,
                        image_path=None,
                        ocr_blocks=None,
                        ocr_confidence_avg=None,
                    )

            records.append(record)

        # Dispatch OCR batches for scanned pages (non-blocking)
        scanned_pages = [r for r in records if r.source == "ocr" and r.image_path]
        if scanned_pages:
            asyncio.create_task(_dispatch_ocr_batches(scanned_pages, settings))

        return records

    except Exception as e:
        raise RuntimeError(f"Failed to ingest PDF: {str(e)}")


async def _dispatch_ocr_batches(scanned_pages: List[PageRecord], settings) -> Dict[int, dict]:
    """
    Chunks scanned pages into batches, posts to ocr-worker,
    returns {page_num: OCRResult} dict.
    """
    batches = [
        scanned_pages[i : i + settings.OCR_BATCH_SIZE]
        for i in range(0, len(scanned_pages), settings.OCR_BATCH_SIZE)
    ]

    results = {}

    async with httpx.AsyncClient(timeout=settings.OCR_TIMEOUT_SECONDS) as client:
        for batch in batches:
            # Prepare multipart form data
            files = []
            for page_record in batch:
                with open(page_record.image_path, "rb") as f:
                    files.append(
                        ("files", (f"{page_record.page_num:04d}.jpg", f.read(), "image/jpeg"))
                    )

            try:
                response = await client.post(
                    f"{settings.OCR_WORKER_URL}/ocr/batch", files=files
                )
                response.raise_for_status()
                ocr_results = response.json()

                # Map results back to page numbers
                for i, page_record in enumerate(batch):
                    page_num = page_record.page_num
                    if str(page_num) in ocr_results:
                        result_data = ocr_results[str(page_num)]
                        # Update the record with OCR results (in a real implementation,
                        # we'd update the stored record, but for now we return the results)
                        results[page_num] = result_data
            except Exception as e:
                # Log error but continue processing
                print(f"OCR batch failed: {e}")
                # Mark pages as failed OCR
                for page_record in batch:
                    results[page_record.page_num] = {
                        "error": str(e),
                        "text": "",
                        "blocks": [],
                        "confidence_avg": 0.0,
                    }

    return results