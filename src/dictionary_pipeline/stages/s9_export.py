"""
Stage 9 — Export to Excel.

Writes the final workbook with three tabs:
  - <dataset_name>            : the cleaned data
  - Data Dictionary           : rendered from the contract
  - Automated Changes         : rendered from the transformation log
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..contract import Contract
from ..logging import TransformationLog


def _dictionary_to_df(contract: Contract) -> pd.DataFrame:
    rows: list[dict] = []
    for f in contract.fields:
        rows.append({
            "field_name": f.name,
            "label": f.label,
            "type": f.type,
            "dtype": f.dtype,
            "nullable": f.nullable,
            "allowed_values": ", ".join(map(str, f.allowed_values)) if f.allowed_values else "",
            "min": f.min if f.min is not None else "",
            "max": f.max if f.max is not None else "",
            "source_column": f.source_column or "",
            "pii": f.pii,
            "reliability": f.reliability,
            "review_status": f.review_status,
            "notes": f.notes,
            "transformation": "",
        })
    for d in contract.derived_fields:
        rows.append({
            "field_name": d.name,
            "label": d.label,
            "type": d.type,
            "dtype": d.dtype,
            "nullable": False,
            "allowed_values": "",
            "min": "",
            "max": "",
            "source_column": "(derived)",
            "pii": False,
            "reliability": "reliable",
            "review_status": d.review_status,
            "notes": d.notes,
            "transformation": d.transformation,
        })
    return pd.DataFrame(rows)


def _log_to_df(log_path: Path) -> pd.DataFrame:
    if not log_path.exists():
        return pd.DataFrame(columns=["ts", "stage", "event", "rows_affected", "details"])
    import json
    rows = []
    for line in log_path.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        rows.append({
            "ts": rec.get("ts", ""),
            "stage": rec.get("stage", ""),
            "event": rec.get("event", ""),
            "rows_affected": rec.get("rows_affected", 0),
            "details": json.dumps(rec.get("details", {})),
        })
    return pd.DataFrame(rows)


def run(
    df: pd.DataFrame,
    contract: Contract,
    workdir: str | Path,
    log_path: str | Path,
    output_path: str | Path | None = None,
    log: TransformationLog | None = None,
) -> Path:
    workdir = Path(workdir)
    log_path = Path(log_path)
    output = Path(output_path) if output_path else workdir / f"{contract.dataset_name}.xlsx"
    output.parent.mkdir(parents=True, exist_ok=True)

    dict_df = _dictionary_to_df(contract)
    log_df = _log_to_df(log_path)

    sheet_name = contract.dataset_name[:31]  # Excel max sheet name length

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)
        dict_df.to_excel(writer, sheet_name="Data Dictionary", index=False)
        log_df.to_excel(writer, sheet_name="Automated Changes", index=False)

    if log:
        log.log(
            stage="s9_export",
            event="workbook_written",
            rows_affected=len(df),
            details={"output": str(output), "sheets": [sheet_name, "Data Dictionary", "Automated Changes"]},
        )
    return output
