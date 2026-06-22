"""
Stage 4: Table Extraction & Recovery
Native table extraction (pdfplumber/camelot) + TATR dispatch + stitching.
"""
import asyncio
from pathlib import Path
from typing import List, Dict, Tuple
import json

import pdfplumber
import httpx

from api.models import PageRecord, RecoveredTable
from api.config import get_settings


async def run(
    labeled_segments: List,
    pdf_path: Path,
    page_records: Dict[int, PageRecord],
    settings
) -> List[RecoveredTable]:
    """
    Extract tables from all labeled segments and stitch multi-page tables.
    """
    # Extract tables page by page
    page_tables: Dict[int, List[dict]] = {}  # page_num -> [table_dicts]

    for segment in labeled_segments:
        # Extract tables for each page in the segment
        for page_num in range(segment.start_page, segment.end_page + 1):
            page_record = page_records.get(page_num)
            if not page_record:
                continue

            tables = []
            if page_record.source == "native_text":
                # Use pdfplumber/camelot for native text pages
                tables = await extract_native_tables(pdf_path, page_num)
            elif page_record.source == "ocr" and page_record.image_path:
                # Use TATR worker for OCR pages
                tables = await extract_ocr_tables(page_record.image_path, settings)

            if tables:
                if page_num not in page_tables:
                    page_tables[page_num] = []
                page_tables[page_num].extend(tables)

    # Stitch multi-page tables
    stitched_tables = stitch_tables(page_tables)

    return stitched_tables


async def extract_native_tables(pdf_path: Path, page_num: int) -> List[dict]:
    """
    Extract tables from a native text page using pdfplumber (with camelot fallback).
    """
    tables = []

    try:
        with pdfplumber.open(pdf_path) as pdf:
            page = pdf.pages[page_num - 1]  # pdfplumber is 0-indexed

            # Try with lines strategy first
            tables_found = page.extract_tables(table_settings={
                "vertical_strategy": "lines",
                "horizontal_strategy": "lines",
                "snap_tolerance": 5,
                "join_tolerance": 3
            })

            if tables_found and len(tables_found) > 0:
                for i, table_data in enumerate(tables_found):
                    if table_data and len(table_data) > 0:
                        tables.append({
                            "page_num": page_num,
                            "table_id": f"temp_{page_num}_{i}",
                            "data": table_data,
                            "extraction_method": "pdfplumber"
                        })
            else:
                # Fallback to text-based strategy
                tables_found = page.extract_tables(table_settings={
                    "vertical_strategy": "text",
                    "horizontal_strategy": "text",
                })

                if tables_found and len(tables_found) > 0:
                    for i, table_data in enumerate(tables_found):
                        if table_data and len(table_data) > 0:
                            tables.append({
                                "page_num": page_num,
                                "table_id": f"temp_{page_num}_{i}",
                                "data": table_data,
                                "extraction_method": "pdfplumber_text"
                            })
    except Exception as e:
        print(f"Native table extraction failed for page {page_num}: {e}")

    return tables


async def extract_ocr_tables(image_path: str, settings) -> List[dict]:
    """
    Extract tables from an OCR page using TATR worker.
    """
    tables = []

    try:
        async with httpx.AsyncClient(timeout=settings.TATR_TIMEOUT_SECONDS) as client:
            with open(image_path, "rb") as f:
                files = {"file": (image_path.split("/")[-1], f.read(), "image/jpeg")}
                response = await client.post(
                    f"{settings.TATR_WORKER_URL}/table/detect",
                    files=files
                )
                response.raise_for_status()
                result = response.json()

                # Process TATR result
                if "tables" in result:
                    for i, table_data in enumerate(result["tables"]):
                        tables.append({
                            "page_num": 0,  # Would need to be passed in
                            "table_id": f"temp_ocr_{i}",
                            "data": table_data,
                            "extraction_method": "tatr"
                        })
    except Exception as e:
        print(f"OCR table extraction failed for image {image_path}: {e}")

    return tables


def stitch_tables(page_tables: Dict[int, List[dict]]) -> List[RecoveredTable]:
    """
    Given {page_num: [tables on that page]}, merge continuation tables.
    Uses header_fingerprint matching to identify continuations.
    Returns final logical tables with all rows assembled.
    """
    from api.models import TableCell, TableRow, ReconciliationResult

    # For now, return simplified tables (full implementation would do proper stitching)
    recovered_tables = []
    table_counter = 0

    for page_num, tables_in_page in sorted(page_tables.items()):
        for table_info in tables_in_page:
            table_counter += 1

            # Convert raw table data to RecoveredTable format
            # This is a simplified conversion - real implementation would be more thorough
            raw_data = table_info.get("data", [])

            if not raw_data or len(raw_data) == 0:
                continue

            # Assume first row is header
            header_row = raw_data[0] if len(raw_data) > 0 else []
            data_rows = raw_data[1:] if len(raw_data) > 1 else []

            # Build columns from header
            columns = [str(cell).strip().lower().replace(" ", "_") for cell in header_row]

            # Build table rows
            rows = []
            for i, row_data in enumerate(data_rows):
                cells = []
                for j, cell_data in enumerate(row_data):
                    if j < len(columns):
                        cell_text = str(cell_data) if cell_data is not None else ""
                        # Try to parse as numeric
                        numeric_value = None
                        try:
                            # Remove currency symbols, commas, etc.
                            cleaned = str(cell_data).replace("$", "").replace(",", "").strip()
                            if cleaned and cleaned.replace(".", "", 1).replace("-", "", 1).isdigit():
                                numeric_value = float(cleaned)
                        except ValueError:
                            pass

                        cells.append(TableCell(
                            col_idx=j,
                            text=cell_text,
                            numeric_value=numeric_value
                        ))

                if cells:  # Only add rows that have cells
                    rows.append(TableRow(
                        row_idx=i,
                        row_type="data",
                        cells=cells
                    ))

            # Only create table if we have data
            if rows:
                recovered_table = RecoveredTable(
                    table_id=f"doc_{table_counter:04d}_t1",
                    doc_id=f"doc_{table_counter:04d}",  # Simplified - would map to actual doc_id
                    schema_type="generic",  # Would be determined by context
                    page_span=(page_num, page_num),  # Would be extended for multi-page
                    header_fingerprint="|".join(columns),
                    columns=columns,
                    rows=rows,
                    reported_total=None,  # Would be extracted from table footer
                    reconciliation=None,
                    extraction_method=table_info.get("extraction_method", "unknown"),
                    confidence=0.8  # Placeholder
                )
                recovered_tables.append(recovered_table)

    return recovered_tables