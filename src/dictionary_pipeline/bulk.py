"""
Bulk multi-file intake utilities.

Groups files by schema (column headers) so the pipeline can process
each schema group independently with its own dictionary contract.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

import pandas as pd

from .logging import TransformationLog
from .scrub import detect_encoding, detect_header_row
from .stages import s0_intake, s1_profile


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


def bulk_intake_run(
    files: list[str | Path],
    workdir: str | Path,
) -> dict:
    """
    Run intake + profile for each schema group.

    Creates: {workdir}/group_0/, group_1/, etc.
    Returns a summary report with group metadata.
    """
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    groups = group_by_schema(files)
    report = {"groups": []}

    for idx, group in enumerate(groups):
        group_dir = workdir / f"group_{idx}"
        group_dir.mkdir(parents=True, exist_ok=True)
        log = TransformationLog(group_dir / "transformations_log.jsonl")

        # Concatenate all files in this group into one DataFrame
        frames = []
        for f in group["files"]:
            header_row = group["header_rows"].get(Path(f), 0)
            df, manifest = s0_intake.run(
                f, group_dir, header_row=header_row, log=log,
            )
            frames.append(df)

        combined = pd.concat(frames, ignore_index=True)
        combined.to_parquet(group_dir / "stage0_df.parquet")

        profile = s1_profile.run(combined, group_dir, log=log)

        group_info = {
            "group_index": idx,
            "workdir": str(group_dir),
            "columns": group["columns"],
            "file_count": len(group["files"]),
            "files": [str(f) for f in group["files"]],
            "total_rows": len(combined),
        }
        report["groups"].append(group_info)

    # Write the bulk report
    (workdir / "bulk_report.json").write_text(json.dumps(report, indent=2))
    return report
