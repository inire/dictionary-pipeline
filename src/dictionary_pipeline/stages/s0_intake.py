"""
Stage 0 — Intake & Quarantine.

Copies the source file to an immutable archive, loads it into a DataFrame,
and writes an intake manifest. The original is now safe.

Accepts any spreadsheet-readable format: .csv, .tsv, .xlsx, .xls, .xlsm.
Dispatch is by file extension. The manifest records the reader and its
params so Stage 8 can re-read the archive with the same settings.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..logging import TransformationLog


_EXCEL_SUFFIXES = {".xlsx", ".xls", ".xlsm", ".xlsb", ".ods"}
_CSV_SUFFIXES = {".csv"}
_TSV_SUFFIXES = {".tsv", ".tab"}


def read_source(
    path: str | Path,
    *,
    sheet_name: str | int = 0,
    header_row: int = 0,
    nrows: int | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Load a tabular source file into a DataFrame.

    Returns (df, reader_params) where reader_params is a JSON-serializable
    record of exactly how the file was read. Stage 8 uses this to replay
    the same read against the archived copy.
    """
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix in _CSV_SUFFIXES:
        reader = "pandas.read_csv"
        params: dict[str, Any] = {"header": header_row}
        if nrows is not None:
            params["nrows"] = nrows
        df = pd.read_csv(path, **params)
    elif suffix in _TSV_SUFFIXES:
        reader = "pandas.read_csv"
        params = {"header": header_row, "sep": "\t"}
        if nrows is not None:
            params["nrows"] = nrows
        df = pd.read_csv(path, **params)
    elif suffix in _EXCEL_SUFFIXES:
        reader = "pandas.read_excel"
        params = {"sheet_name": sheet_name, "header": header_row}
        if nrows is not None:
            params["nrows"] = nrows
        df = pd.read_excel(path, **params)
    else:
        raise ValueError(
            f"Unsupported file extension {suffix!r} for {path}. "
            f"Supported: {sorted(_CSV_SUFFIXES | _TSV_SUFFIXES | _EXCEL_SUFFIXES)}"
        )

    return df, {"reader": reader, "params": params}


def run(
    source_path: str | Path,
    workdir: str | Path,
    sheet_name: str | int = 0,
    header_row: int = 0,
    nrows: int | None = None,
    log: TransformationLog | None = None,
) -> tuple[pd.DataFrame, dict]:
    """
    Copy `source_path` into `{workdir}/intake/`, load it, return (df, manifest).
    """
    source = Path(source_path)
    workdir = Path(workdir)
    intake_dir = workdir / "intake"
    intake_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = intake_dir / f"{source.stem}__{ts}{source.suffix}"
    shutil.copy2(source, archive)

    df, reader_info = read_source(
        archive,
        sheet_name=sheet_name,
        header_row=header_row,
        nrows=nrows,
    )

    manifest = {
        "source_path": str(source.resolve()),
        "archive_path": str(archive.resolve()),
        "ingested_at": ts,
        "reader": reader_info["reader"],
        "reader_params": reader_info["params"],
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "columns": list(df.columns),
        "dtypes": {c: str(t) for c, t in df.dtypes.items()},
    }

    (workdir / "intake_manifest.json").write_text(json.dumps(manifest, indent=2))

    if log:
        log.log(
            stage="s0_intake",
            event="archived_and_loaded",
            rows_affected=len(df),
            details={
                "archive": str(archive),
                "columns": list(df.columns),
                "reader": reader_info["reader"],
            },
        )

    return df, manifest
