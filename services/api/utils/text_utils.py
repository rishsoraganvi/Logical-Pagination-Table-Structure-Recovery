"""
Text utilities for header/footer extraction and normalization.
"""
import re
from typing import Tuple, List
from pathlib import Path


def extract_header_footer_zones(
    text: str,
    header_fraction: float = 0.15,
    footer_fraction: float = 0.15
) -> Tuple[str, str]:
    """
    Extract header and footer text zones from page text.
    Uses simple line-based approximation since we don't have bbox info in text-only mode.
    """
    if not text.strip():
        return "", ""

    lines = text.split('\n')
    total_lines = len(lines)

    if total_lines == 0:
        return "", ""

    # Calculate line counts for zones
    header_lines_count = max(1, int(total_lines * header_fraction))
    footer_lines_count = max(1, int(total_lines * footer_fraction))

    # Extract header (first N lines)
    header_lines = lines[:header_lines_count]
    header_text = '\n'.join(header_lines).strip()

    # Extract footer (last N lines)
    footer_lines = lines[-footer_lines_count:] if footer_lines_count < total_lines else lines
    footer_text = '\n'.join(footer_lines).strip()

    return header_text, footer_text


def normalize_text(text: str) -> str:
    """
    Normalize text for comparison and processing.
    """
    if not text:
        return ""

    # Convert to lowercase
    text = text.lower()

    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text)

    # Strip leading/trailing whitespace
    text = text.strip()

    return text


def extract_distinguishing_patterns(text: str) -> dict:
    """
    Extract potential distinguishing attributes using regex patterns.
    Returns dict with attribute names and their values (or None if not found).
    """
    patterns = {
        "statement_period_start": [
            r"(?:statement\s+period\s+from|period\s+starting|covering\s+period\s+from)[\s:]*(\d{4}[-/]\d{2}[-/]\d{2})",
            r"(?:from)[\s:]*(\d{4}[-/]\d{2}[-/]\d{2})(?:\s+(?:to|through))"
        ],
        "statement_period_end": [
            r"(?:statement\s+period\s+to|period\s+ending|covering\s+period\s+to)[\s:]*(\d{4}[-/]\d{2}[-/]\d{2})",
            r"(?:to|through)[\s:]*(\d{4}[-/]\d{2}[-/]\d{2})"
        ],
        "account_number_last4": [
            r"(?:account\s+#?|acct\s*#?)[\s:]*[^\d]*(\d{4})[^\d]",
            r"(?:account\s+number)[\s:]*[^\d]*(\d{4})"
        ],
        "tax_year": [
            r"(?:tax\s+year|year)[\s:]*(\d{4})",
            r"\b(\d{4})\s*(?:tax\s+year|return\s+year)"
        ],
        "pay_period_start": [
            r"(?:pay\s+period\s+from|period\s+starting)[\s:]*(\d{4}[-/]\d{2}[-/]\d{2})",
            r"(?:earnings\s+from|paid\s+for\s+period\s+starting)[\s:]*(\d{4}[-/]\d{2}[-/]\d{2})"
        ],
        "pay_period_end": [
            r"(?:pay\s+period\s+to|period\s+ending)[\s:]*(\d{4}[-/]\d{2}[-/]\d{2})",
            r"(?:earnings\s+to|paid\s+for\s+period\s+ending)[\s:]*(\d{4}[-/]\d{2}[-/]\d{2})"
        ],
        "pay_date": [
            r"(?:pay\s+date|date\s+paid|check\s+date)[\s:]*(\d{4}[-/]\d{2}[-/]\d{2})",
            r"(?:paid\s+on)[\s:]*(\d{4}[-/]\d{2}[-/]\d{2})"
        ],
        "employer_name": [
            r"(?:employer|company)[\s:]*([^\n\r\r]{1,60})",
            r"(?:paid\s+by|issued\s+by)[\s:]*([^\n\r\r]{1,60})"
        ],
        "subject": [
            r"(?:subject|re:|re:)\s*([^\n\r]{1,100})",
            r"(?:regarding|re:)\s*([^\n\r]{1,100})"
        ],
        "form_number": [
            r"(?:form\s*#?|irs\s*form\s*#?)[\s:]*(\d+[A-Z]*)",
            r"\b(\d+[A-Z]*)\s*(?:form|return)"
        ]
    }

    results = {}
    for attr_name, pattern_list in patterns.items():
        results[attr_name] = None
        for pattern in pattern_list:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                results[attr_name] = match.group(1)
                break  # Use first match found

    return results