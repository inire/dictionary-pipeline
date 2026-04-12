"""
Bulk multi-file intake utilities.

Groups files by schema (column headers) so the pipeline can process
each schema group independently with its own dictionary contract.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from .scrub import detect_encoding, detect_header_row


def _read_headers(path: Path) -> tuple[list[str], int]:
    """Read the header row from a file. Returns (columns, header_row_index)."""
    encoding = detect_encoding(path)
    header_idx = detect_header_row(path)

    with path.open("r", encoding=encoding, newline="") as f:
        for _ in range(header_idx):
            f.readline()  # skip preamble rows
        header_line = f.readline()

    if not header_line.strip():
        return [], header_idx

    parsed = next(csv.reader([header_line]))
    columns = [c.strip().strip('"') for c in parsed if c.strip()]
    return columns, header_idx


def group_by_schema(
    files: Iterable[str | Path],
) -> list[dict]:
    """
    Group files by matching column headers.

    Returns a list of dicts:
        {
            "columns": ["col1", "col2", ...],
            "files": [Path, Path, ...],
            "header_rows": {Path: int, ...},
        }

    Files with identical column sets (order-sensitive) go in the same group.
    """
    files = [Path(f) for f in files]
    if not files:
        return []

    groups: dict[tuple[str, ...], dict] = {}

    for f in sorted(files):
        try:
            columns, header_idx = _read_headers(f)
        except Exception:
            continue

        key = tuple(columns)
        if key not in groups:
            groups[key] = {
                "columns": columns,
                "files": [],
                "header_rows": {},
            }
        groups[key]["files"].append(f)
        groups[key]["header_rows"][f] = header_idx

    return list(groups.values())
