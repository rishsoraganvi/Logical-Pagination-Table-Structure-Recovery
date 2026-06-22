"""
Numeric utilities for parsing currency strings and numbers.
"""
import re
from typing import Optional


def parse_currency_string(value: str) -> Optional[float]:
    """
    Parse a currency string into a float.
    Handles formats like: $1,234.56, 1234.56, (123.45), -123.45, etc.
    Returns None if parsing fails.
    """
    if not value or not isinstance(value, str):
        return None

    # Strip whitespace
    value = value.strip()

    # Handle parentheses as negative
    is_negative = False
    if value.startswith('(') and value.endswith(')'):
        is_negative = True
        value = value[1:-1]

    # Remove currency symbols and commas
    # Keep minus sign if present (but we already handled parentheses)
    cleaned = re.sub(r'[^\d.-]', '', value)

    # Handle empty string after cleaning
    if not cleaned or cleaned == '-' or cleaned == '.':
        return None

    try:
        result = float(cleaned)
        return -result if is_negative else result
    except ValueError:
        return None


def parse_percentage_string(value: str) -> Optional[float]:
    """
    Parse a percentage string into a float (e.g., "12.5%" -> 0.125).
    Returns None if parsing fails.
    """
    if not value or not isinstance(value, str):
        return None

    # Strip whitespace
    value = value.strip()

    # Remove percentage sign
    if value.endswith('%'):
        value = value[:-1]

    try:
        result = float(value)
        return result / 100.0  # Convert to decimal
    except ValueError:
        return None


def is_numeric_string(value: str) -> bool:
    """
    Check if a string represents a number (integer or float).
    """
    if not value or not isinstance(value, str):
        return False

    # Strip whitespace
    value = value.strip()

    # Handle parentheses as negative
    if value.startswith('(') and value.endswith(')'):
        value = value[1:-1]

    # Remove commas and decimal point for digit check
    cleaned = re.sub(r'[^\d.-]', '', value)

    # Check if it's a valid number format
    if not cleaned or cleaned == '-' or cleaned == '.':
        return False

    # Allow at most one decimal point and one minus sign (at start)
    if cleaned.count('.') > 1:
        return False
    if cleaned.count('-') > 1 or (cleaned.count('-') == 1 and not cleaned.startswith('-')):
        return False

    try:
        float(cleaned)
        return True
    except ValueError:
        return False