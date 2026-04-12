"""
Input scrubbing utilities for Stage 0.

Handles encoding detection, CSV formula injection scanning,
control character removal, and non-standard header detection.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import chardet


def detect_encoding(path: str | Path) -> str:
    """
    Detect file encoding. Returns a string suitable for open(encoding=...).

    Priority: UTF-8 BOM > chardet detection > fallback to utf-8.
    """
    path = Path(path)
    raw = path.read_bytes()

    # Check for BOM first — chardet sometimes misses it
    if raw[:3] == b"\xef\xbb\xbf":
        return "utf-8-sig"

    result = chardet.detect(raw)
    encoding = result.get("encoding", "utf-8") or "utf-8"

    # Normalize chardet's names to Python codec names
    encoding = encoding.lower()
    if encoding in ("ascii", "utf-8"):
        return "utf-8"

    return encoding


# Patterns that indicate CSV formula injection.
# We intentionally DO NOT flag + followed by digits (phone numbers like +1-555-1234).
_FORMULA_RE = re.compile(
    r"^[=@]"           # starts with = or @
    r"|^[+\-](?!\d)"   # starts with + or - NOT followed by a digit (excludes phone numbers, negative numbers)
    r"|^\t[=@+\-]"     # tab-prefixed formulas (bypass attempt)
)


def scan_formula_injection(
    path: str | Path,
    encoding: str | None = None,
) -> list[dict]:
    """
    Scan a CSV for cells that look like spreadsheet formula injection.

    Returns a list of dicts: {"row": int, "col": str, "value": str}
    for each suspicious cell. Empty list = clean file.

    Does NOT modify the file — this is detection only.
    """
    path = Path(path)
    if encoding is None:
        encoding = detect_encoding(path)

    hits: list[dict] = []
    with path.open("r", encoding=encoding, newline="") as f:
        reader = csv.DictReader(f)
        for row_idx, row in enumerate(reader, start=2):  # row 1 = header
            for col, value in row.items():
                if value and _FORMULA_RE.match(value.strip()):
                    hits.append({"row": row_idx, "col": col, "value": value.strip()})

    return hits


# Control characters to remove. We keep \t (0x09), \n (0x0a), \r (0x0d).
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def strip_control_chars(value: str | None) -> str | None:
    """Remove ASCII control characters except tab, newline, carriage return."""
    if value is None:
        return None
    return _CONTROL_RE.sub("", value)
