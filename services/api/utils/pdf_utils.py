"""
PDF utilities for text extraction and page processing.
"""
import pypdf
from pathlib import Path
from typing import Tuple


def get_page_count(pdf_path: Path) -> int:
    """Get the number of pages in a PDF file."""
    with open(pdf_path, "rb") as f:
        pdf = pypdf.PdfReader(f)
        return len(pdf.pages)


def extract_text_from_page(pdf_path: Path, page_num: int) -> str:
    """
    Extract text from a specific page (1-indexed).
    Returns empty string if page is out of range or extraction fails.
    """
    try:
        with open(pdf_path, "rb") as f:
            pdf = pypdf.PdfReader(f)
            if 1 <= page_num <= len(pdf.pages):
                page = pdf.pages[page_num - 1]  # Convert to 0-indexed
                return page.extract_text() or ""
            else:
                return ""
    except Exception:
        return ""


def extract_all_text(pdf_path: Path) -> str:
    """Extract all text from a PDF file."""
    try:
        with open(pdf_path, "rb") as f:
            pdf = pypdf.PdfReader(f)
            text_parts = []
            for page in pdf.pages:
                text_parts.append(page.extract_text() or "")
            return "\n\n".join(text_parts)
    except Exception:
        return ""