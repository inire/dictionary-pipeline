"""
Input scrubbing utilities for Stage 0.

Handles encoding detection, CSV formula injection scanning,
control character removal, and non-standard header detection.
"""

from __future__ import annotations

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
