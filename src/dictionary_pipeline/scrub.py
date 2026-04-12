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


def _looks_numeric(s: str) -> bool:
    """Check if a string looks like a number (including currency and percentages)."""
    cleaned = s.replace(",", "").replace("$", "").replace("%", "").strip()
    if not cleaned:
        return False
    try:
        float(cleaned)
        return True
    except ValueError:
        return False


def detect_header_row(path: str | Path, max_scan: int = 10) -> int:
    """
    Guess which row contains column headers in a CSV.

    Heuristic: the header row is the first row where:
    - It has more than 1 non-empty field
    - The fields look like column names (not all numeric, not currency-formatted)
    - It's not a single long sentence/description

    Returns a 0-based row index suitable for pandas header= parameter.
    """
    path = Path(path)
    encoding = detect_encoding(path)

    lines: list[str] = []
    with path.open("r", encoding=encoding, newline="") as f:
        for _ in range(max_scan):
            line = f.readline()
            if not line:
                break
            lines.append(line)

    if not lines:
        return 0

    for idx, line in enumerate(lines):
        stripped = line.strip()

        # Skip blank lines
        if not stripped:
            continue

        # Parse as CSV to handle quoting
        parsed = next(csv.reader([stripped]))
        non_empty = [f for f in parsed if f.strip()]

        # Skip lines with only 1 field (likely a title/description)
        if len(non_empty) <= 1:
            continue

        # Skip lines where most fields are numeric (likely data, not headers)
        numeric_count = sum(1 for f in non_empty if _looks_numeric(f.strip()))
        if len(non_empty) > 2 and numeric_count / len(non_empty) > 0.6:
            continue

        # This looks like a header row
        return idx

    return 0
