"""
Stage 1: Cheap Page Fingerprinting
Compute lightweight features for each page: header/footer text, layout, embeddings.
"""
from typing import List
import numpy as np

from api.models import PageFingerprint, PageRecord
from sentence_transformers import SentenceTransformer
import cv2


# Load the sentence transformer model once at module level
_model = SentenceTransformer("all-MiniLM-L6-v2")


def fingerprint_page(record: PageRecord) -> PageFingerprint:
    """
    Compute fingerprint for a single page.
    """
    # Extract header and footer text
    header_text, footer_text = _extract_header_footer(record)

    # Get embedding for header text
    embed_vec = _get_embedding(header_text)

    # Compute layout features
    layout_vec = _compute_layout_features(record)

    # Check if near blank
    is_near_blank = layout_vec[5] < 0.05  # ink_coverage < 0.05

    return PageFingerprint(
        page_num=record.page_num,
        header_text=header_text,
        footer_text=footer_text,
        embed_vec=embed_vec.tolist(),
        layout_vec=layout_vec.tolist(),
        is_near_blank=is_near_blank,
    )


def run(records: List[PageRecord]) -> List[PageFingerprint]:
    """
    Compute fingerprints for all pages.
    """
    return [fingerprint_page(record) for record in records]


def _extract_header_footer(record: PageRecord) -> tuple[str, str]:
    """
    Extract header (top 15%) and footer (bottom 15%) text from page.
    """
    if record.source == "native_text":
        # For native text, we'd need bounding box info from pypdf
        # For simplicity, we'll approximate by splitting text
        lines = record.text.split("\n")
        if not lines:
            return "", ""

        # Take first and last few lines as header/footer approximation
        header_lines = lines[:max(1, len(lines) // 6)]  # Top ~15%
        footer_lines = lines[max(0, len(lines) * 5 // 6):]  # Bottom ~15%

        header_text = " ".join(header_lines).strip()
        footer_text = " ".join(footer_lines).strip()
    else:
        # For OCR pages, use bbox information
        if not record.ocr_blocks:
            return "", ""

        # Sort blocks by vertical position (y1)
        sorted_blocks = sorted(record.ocr_blocks, key=lambda b: b.bbox[1])

        # Estimate page height from blocks
        if sorted_blocks:
            max_y2 = max(block.bbox[3] for block in sorted_blocks)
            header_cutoff = max_y2 * 0.15  # Top 15%
            footer_cutoff = max_y2 * 0.85  # Start of bottom 15%

            header_blocks = [b for b in sorted_blocks if b.bbox[1] < header_cutoff]
            footer_blocks = [b for b in sorted_blocks if b.bbox[3] > footer_cutoff]

            header_text = " ".join(b.text for b in header_blocks).strip()
            footer_text = " ".join(b.text for b in footer_blocks).strip()
        else:
            header_text, footer_text = "", ""

    return header_text, footer_text


def _get_embedding(text: str) -> np.ndarray:
    """
    Get sentence embedding for text.
    """
    if not text.strip():
        return np.zeros(384)  # Return zero vector for empty text
    return _model.encode(text)


def _compute_layout_features(record: PageRecord) -> np.ndarray:
    """
    Compute layout features: [line_density, col_count, whitespace_ratio,
                             table_present, text_density, ink_coverage]
    """
    if record.source == "native_text":
        # For native text pages, synthesize features from text
        return _compute_layout_features_native(record)
    else:
        # For OCR/scanned pages, use OpenCV on the image
        return _compute_layout_features_ocr(record)


def _compute_layout_features_native(record: PageRecord) -> np.ndarray:
    """
    Compute layout features for native text pages (approximation).
    """
    lines = record.text.split("\n")
    non_empty_lines = [line for line in lines if line.strip()]

    # Line density: ratio of non-empty lines to total lines
    line_density = len(non_empty_lines) / max(len(lines), 1)

    # Estimate column count based on whitespace patterns
    # Simple approximation: count lines with significant indentation
    indented_lines = sum(1 for line in lines if line.startswith(("  ", "\t")))
    col_count = min(max(indented_lines // 10, 1), 5)  # Rough estimate

    # Whitespace ratio: proportion of whitespace characters
    total_chars = len(record.text)
    whitespace_chars = sum(1 for c in record.text if c.isspace())
    whitespace_ratio = whitespace_chars / max(total_chars, 1)

    # Table present: heuristic based on regular spacing
    # Very rough approximation
    table_present = 1.0 if line_density > 0.3 and whitespace_ratio > 0.2 else 0.0

    # Text density: ratio of non-whitespace to total characters
    text_density = 1.0 - whitespace_ratio

    # Ink coverage: approximation for text pages
    ink_coverage = text_density * 0.8  # Assume text covers 80% of non-whitespace area

    return np.array([
        line_density,
        float(col_count),
        whitespace_ratio,
        table_present,
        text_density,
        ink_coverage
    ])


def _compute_layout_features_ocr(record: PageRecord) -> np.ndarray:
    """
    Compute layout features for OCR pages using OpenCV on the image.
    """
    if not record.image_path:
        return np.zeros(6)

    try:
        # Load image
        image = cv2.imread(record.image_path)
        if image is None:
            return np.zeros(6)

        height, width = image.shape[:2]

        # Convert to grayscale
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # Threshold to get binary image
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # Calculate ink coverage (proportion of non-white pixels)
        ink_coverage = np.sum(binary > 0) / (width * height)

        # Text density: approximate from OCR confidence
        text_density = min(ink_coverage * 1.2, 1.0)  # Rough approximation

        # Whitespace ratio: inverse of ink coverage with smoothing
        whitespace_ratio = max(0.0, 1.0 - ink_coverage * 1.1)

        # Line density: estimate from horizontal projections
        horizontal_proj = np.sum(binary, axis=1)
        # Count peaks in horizontal projection (lines of text)
        from scipy.signal import find_peaks
        try:
            peaks, _ = find_peaks(horizontal_proj, height=horizontal_proj.max()*0.1, distance=5)
            line_density = len(peaks) / height if height > 0 else 0
        except ImportError:
            # Fallback if scipy not available
            line_density = np.sum(horizontal_proj > horizontal_proj.mean()) / height

        # Column count: estimate from vertical projections
        vertical_proj = np.sum(binary, axis=0)
        try:
            peaks, _ = find_peaks(vertical_proj, height=vertical_proj.max()*0.1, distance=10)
            col_count = len(peaks)
        except ImportError:
            # Fallback if scipy not available
            col_count = np.sum(vertical_proj > vertical_proj.mean()) // max(width // 20, 1)

        # Table present: heuristic based on regular grid patterns
        # Very rough approximation
        table_present = 1.0 if (line_density > 0.01 and col_count > 1 and ink_coverage > 0.1) else 0.0

        return np.array([
            min(line_density, 1.0),  # Normalize
            min(float(col_count), 10.0) / 10.0,  # Normalize to 0-1
            min(whitespace_ratio, 1.0),
            table_present,
            min(text_density, 1.0),
            min(ink_coverage, 1.0)
        ])
    except Exception:
        # Return zeros if image processing fails
        return np.zeros(6)