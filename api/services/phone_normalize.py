"""Phone number normalization utility.

Strips formatting artifacts, handles float-like values from CSV imports,
adds Czech +420 prefix where appropriate, and provides display formatting.
"""

from __future__ import annotations

import re
from typing import Optional


def normalize_phone(raw: Optional[str]) -> Optional[str]:
    """Normalize a phone number string for storage.

    - Strips whitespace, dashes, parentheses, dots (non-digit/non-plus chars)
    - Handles float-like values: "602123456.0" → "602123456"
    - Adds +420 prefix for Czech numbers (9 digits starting with 2-7)
    - Normalizes "00420" → "+420" and "420" → "+420"
    - Preserves existing "+" prefixes

    Returns normalized string like "+420602123456", or None if input is empty.
    """
    if raw is None:
        return None

    # Convert to string in case a numeric value sneaks through
    s = str(raw).strip()
    if not s:
        return None

    # Strip trailing .0 from float-like values (e.g. "602123456.0")
    s = re.sub(r"\.0+$", "", s)

    # Preserve the leading '+' if present
    has_plus = s.startswith("+")

    # Strip all non-digit characters
    digits = re.sub(r"\D", "", s)

    if not digits:
        return None

    # Restore or apply prefix
    if has_plus:
        # Had a +, reconstruct: +<digits>
        result = f"+{digits}"
    elif digits.startswith("00") and len(digits) > 4:
        # International format 00XX... → +XX... (strip leading 00)
        result = f"+{digits[2:]}"
    elif digits.startswith("420") and len(digits) >= 12:
        # 420XXXXXXXXX (420 + 9-digit Czech number)
        result = f"+{digits}"
    elif len(digits) == 9 and digits[0] in "234567":
        # Czech mobile/landline: 9 digits starting with 2-7
        result = f"+420{digits}"
    else:
        # Unknown format — store as-is with + prefix if it looks international
        # (10+ digits), otherwise just the digits
        if len(digits) >= 10:
            result = f"+{digits}"
        else:
            result = digits

    return result


def format_phone_display(normalized: Optional[str]) -> Optional[str]:
    """Format a normalized phone number for display.

    "+420602123456" → "+420 602 123 456"
    Other formats are returned as-is.
    """
    if not normalized:
        return normalized

    # Czech numbers: +420 XXX XXX XXX
    m = re.match(r"^\+420(\d{3})(\d{3})(\d{3})$", normalized)
    if m:
        return f"+420 {m.group(1)} {m.group(2)} {m.group(3)}"

    # Generic international: insert space after country code (first 1-3 digits after +)
    m = re.match(r"^\+(\d{1,3})(\d+)$", normalized)
    if m:
        cc = m.group(1)
        rest = m.group(2)
        # Group remaining digits in threes
        groups = [rest[i : i + 3] for i in range(0, len(rest), 3)]
        return f"+{cc} {' '.join(groups)}"

    return normalized
