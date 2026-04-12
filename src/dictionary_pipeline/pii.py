"""
PII detection and redaction for dictionary pipeline outputs.

Detects common PII patterns in field values and provides redaction
functions for profiles, dictionaries, and markdown outputs.
"""

from __future__ import annotations

import re


# --- Pattern definitions ---

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("ssn", re.compile(r"^\d{3}-\d{2}-\d{4}$")),
    ("email", re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}$")),
    ("credit_card", re.compile(r"^\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}$")),
    ("partial_card", re.compile(r"(?:ending|last\s*4|card)\s*(?:in\s*)?\d{4}", re.IGNORECASE)),
    ("partial_account", re.compile(r"^[.*]{2,}\d{3,}$")),
    ("phone", re.compile(r"^[+]?[\d\s().-]{10,}$")),
]

# Phone number false-positive guard: must have at least 7 actual digits
_DIGIT_RE = re.compile(r"\d")

# ISO date pattern — exclude from phone matches (YYYY-MM-DD)
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def classify_pii(value: str) -> str | None:
    """
    Classify a string value as a PII type, or None if not PII.

    Returns one of: 'ssn', 'email', 'credit_card', 'partial_card',
    'partial_account', 'phone', or None.
    """
    value = value.strip()
    if not value:
        return None

    for pii_type, pattern in _PATTERNS:
        if pattern.search(value):
            # Extra checks for phone: must have at least 7 digits and not be an ISO date
            if pii_type == "phone":
                if len(_DIGIT_RE.findall(value)) < 7:
                    continue
                if _ISO_DATE_RE.match(value):
                    continue
            return pii_type

    return None
