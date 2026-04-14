"""
PII detection and redaction for dictionary pipeline outputs.

Detects common PII patterns in field values and provides redaction
functions for profiles, dictionaries, and markdown outputs.
"""

from __future__ import annotations

import copy
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


# Unanchored versions for substring scanning inside free text.
# Use word boundaries so matches stop at non-identifier characters.
# Note: partial_account from _PATTERNS is intentionally omitted — its
# anchored pattern (^[.*]{2,}\d{3,}$) doesn't adapt to substring scanning
# without producing false positives on any "... NNN" sequence in prose.
_SCAN_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("email", re.compile(r"\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.[a-zA-Z]{2,}\b")),
    ("credit_card", re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b")),
    ("partial_card", re.compile(r"(?:ending|last\s*4|card)\s*(?:in\s*)?\d{4}", re.IGNORECASE)),
    ("phone", re.compile(r"\b\+?\d{3}[\s.-]?\d{3}[\s.-]?\d{4}\b")),
]


def find_pii(text: str | None) -> list[tuple[str, str]]:
    """
    Find PII occurrences inside a free-text string.

    Unlike classify_pii (which checks if an entire value IS a PII type),
    this searches for PII substrings within longer text like notes fields.

    Returns a list of (pii_type, matched_text) tuples. Empty list if clean.
    """
    if not text:
        return []

    findings: list[tuple[str, str]] = []
    for pii_type, pattern in _SCAN_PATTERNS:
        for m in pattern.finditer(text):
            matched = m.group(0)
            # Guard: phone must have at least 7 digits. The ISO-date check
            # is defensive parity with classify_pii — the phone regex needs
            # 10 digits and ISO dates only have 8, so this branch is currently
            # unreachable but kept to prevent drift if either pattern changes.
            if pii_type == "phone":
                if len(_DIGIT_RE.findall(matched)) < 7:
                    continue
                if _ISO_DATE_RE.match(matched):
                    continue
            findings.append((pii_type, matched))

    return findings


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


def redact_value(value: str, pii_type: str) -> str:
    """Replace a PII value with a type-tagged placeholder."""
    return f"[REDACTED_{pii_type.upper()}]"


def _is_person_name(value: str) -> bool:
    """
    Simple heuristic: a person name is 2-4 capitalized words, no digits,
    no special chars beyond hyphens and apostrophes.
    """
    if not value or any(c.isdigit() for c in value):
        return False
    parts = value.split()
    if len(parts) < 2 or len(parts) > 4:
        return False
    return all(
        p[0].isupper() and p.replace("-", "").replace("'", "").isalpha()
        for p in parts
    )


def redact_profile(profile: dict) -> dict:
    """
    Return a deep copy of a Stage 1 profile with PII values redacted
    in the top_values entries.
    """
    scrubbed = copy.deepcopy(profile)

    for col_name, col_info in scrubbed.get("columns", {}).items():
        top_values = col_info.get("top_values")
        if not top_values:
            continue

        new_top: dict = {}
        redact_idx = 0
        for val, count in top_values.items():
            pii_type = classify_pii(val)

            # Also check for person names (not caught by regex patterns)
            if pii_type is None and _is_person_name(val):
                pii_type = "person_name"

            if pii_type:
                redact_idx += 1
                new_top[f"[REDACTED_{pii_type.upper()}_{redact_idx}]"] = count
            else:
                new_top[val] = count

        col_info["top_values"] = new_top

    return scrubbed
