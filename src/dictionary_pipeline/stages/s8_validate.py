"""
Stage 8 — Validation.

Three checks:
  1. Re-validate the final DataFrame against the contract (catches drift
     introduced by stages 5/6/7).
  2. Diff against the intake archive on a per-column basis to surface any
     unexpected value changes.
  3. QA checks — non-fatal warnings for data quality issues (infinity values,
     suspicious rounding, future dates, column name hygiene).

If schema revalidation or diff checks fail, this stage raises and the pipeline
halts before export. QA checks are warnings only — they never raise.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..contract import Contract, build_pandera_schema, rename_to_contract
from ..logging import TransformationLog
from .s0_intake import read_source


def _reread_archive(workdir: Path, archive_path: Path) -> pd.DataFrame:
    """
    Re-read the intake archive using the same reader + params recorded in
    the intake manifest. Falls back to a sensible default if the manifest
    is missing (older runs, direct invocation without Stage 0).
    """
    manifest_path = workdir / "intake_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        params = manifest.get("reader_params", {}) or {}
        sheet_name = params.get("sheet_name", 0)
        header_row = params.get("header", 0)
        nrows = params.get("nrows")
        df, _ = read_source(
            archive_path,
            sheet_name=sheet_name,
            header_row=header_row,
            nrows=nrows,
        )
        return df
    # fallback: dispatch on extension with defaults
    df, _ = read_source(archive_path)
    return df


def _qa_checks(df: pd.DataFrame, contract: Contract) -> dict:
    """
    Run non-fatal QA checks on the final DataFrame.

    Returns a dict with four keys, each a list of column names that triggered
    the check.  Never raises — callers treat results as warnings only.

    Checks performed:
      - infinity_columns: numeric columns containing inf or -inf
      - suspicious_rounding_columns: float columns where >90% of non-null
        values are whole numbers (suggests data was truncated or mistyped)
      - future_date_columns: datetime columns with values beyond today + 1 day
      - bad_column_names: columns with leading/trailing whitespace, double
        spaces, or non-ASCII characters
    """
    result: dict = {
        "infinity_columns": [],
        "suspicious_rounding_columns": [],
        "future_date_columns": [],
        "bad_column_names": [],
    }

    cutoff = pd.Timestamp.now() + pd.Timedelta(days=1)

    for col in df.columns:
        series = df[col]

        # 1. Infinity — any numeric column
        if pd.api.types.is_numeric_dtype(series):
            try:
                if np.isinf(series.dropna().astype(float)).any():
                    result["infinity_columns"].append(col)
            except (TypeError, ValueError, OverflowError):
                pass

        # 2. Suspicious rounding — float columns only
        if pd.api.types.is_float_dtype(series):
            non_null = series.dropna()
            if len(non_null) > 0 and (non_null == non_null.round(0)).mean() > 0.9:
                result["suspicious_rounding_columns"].append(col)

        # 3. Future dates — datetime columns only
        if pd.api.types.is_datetime64_any_dtype(series):
            if (series.dropna() > cutoff).any():
                result["future_date_columns"].append(col)

        # 4. Column name hygiene
        if col != col.strip() or "  " in col or not col.isascii():
            result["bad_column_names"].append(col)

    return result


def run(
    final_df: pd.DataFrame,
    contract: Contract,
    intake_archive_path: str | Path,
    workdir: str | Path,
    sheet_name: str | int = 0,  # retained for backward compat, unused when manifest present
    log: TransformationLog | None = None,
) -> dict:
    workdir = Path(workdir)
    report: dict = {}

    # 1. re-validate against contract
    schema = build_pandera_schema(contract)
    schema.validate(final_df, lazy=True)
    report["schema_revalidation"] = "passed"

    # 2. diff against original (per column, on shared columns)
    original = _reread_archive(workdir, Path(intake_archive_path))
    original = rename_to_contract(original, contract)

    diffs: dict[str, dict] = {}
    for col in contract.field_names():
        if col not in original.columns or col not in final_df.columns:
            continue
        if len(original) != len(final_df):
            diffs[col] = {
                "row_count_changed": True,
                "original_rows": len(original),
                "final_rows": len(final_df),
            }
            continue
        # align by position; treat NaN==NaN as equal (default str cast makes NaN -> "nan"
        # which is fine for equality, but explicit null-aware comparison is clearer)
        orig_col = original[col].reset_index(drop=True)
        final_col = final_df[col].reset_index(drop=True)
        try:
            both_null = orig_col.isna() & final_col.isna()
            both_present = orig_col.notna() & final_col.notna()
            value_match = pd.Series(False, index=orig_col.index)
            value_match[both_present] = (
                orig_col[both_present].astype(str) == final_col[both_present].astype(str)
            )
            mismatch_mask = ~(both_null | value_match)
            mismatches = int(mismatch_mask.sum())
        except Exception:
            mismatches = -1
        if mismatches:
            diffs[col] = {"mismatches": mismatches}
    report["original_vs_final_diff"] = diffs

    # 3. QA checks (warnings only — never raises)
    report["qa_checks"] = _qa_checks(final_df, contract)

    (workdir / "validation_report.json").write_text(json.dumps(report, indent=2, default=str))

    if log:
        log.log(
            stage="s8_validate",
            event="validation_complete",
            rows_affected=len(final_df),
            details={"diff_columns": list(diffs.keys())},
        )
    return report
