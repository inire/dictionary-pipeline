"""
Stage 1 — Automated Profile.

Replaces /audit-xls with a deterministic profile. Outputs a JSON summary
suitable for handing to Claude in stage 3 (draft dictionary).

The JSON summary is always produced. When the optional `[profiling]`
extra is installed (`pip install -e ".[profiling]"`), a richer
ydata-profiling HTML report is also produced at `profile_report.html`
in the workdir. Failures from the HTML side never break the JSON side.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..logging import TransformationLog
from ..pii import redact_profile


# Probe ydata-profiling at import time so we can gate the HTML report
# without paying the import cost on every profile() call.
try:
    from ydata_profiling import ProfileReport as _YDataProfileReport  # noqa: F401

    _YDATA_AVAILABLE = True
except ImportError:
    _YDATA_AVAILABLE = False


def _freshness_check(df: pd.DataFrame, stale_threshold_days: int = 90) -> dict:
    """For each datetime column compute freshness stats. Return {"by_column": {...}}."""
    now = datetime.now(timezone.utc)
    by_column: dict = {}

    for col in df.columns:
        s = df[col]
        if not pd.api.types.is_datetime64_any_dtype(s):
            continue
        non_null = s.dropna()
        if len(non_null) == 0:
            continue

        newest = non_null.max()
        oldest = non_null.min()

        # Normalise to UTC-aware for comparison
        if newest.tzinfo is None:
            newest_aware = newest.tz_localize("UTC")
        else:
            newest_aware = newest.tz_convert("UTC")

        span_days = float((newest - oldest).total_seconds() / 86400)
        staleness_days = float((now - newest_aware).total_seconds() / 86400)

        by_column[col] = {
            "newest": str(newest),
            "oldest": str(oldest),
            "span_days": round(span_days, 3),
            "staleness_days": round(staleness_days, 3),
            "is_stale": staleness_days > stale_threshold_days,
        }

    if not by_column:
        return {}
    return {"by_column": by_column}


def profile(df: pd.DataFrame) -> dict:
    """Return a serializable profile of `df`."""
    summary: dict = {
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "columns": {},
    }

    for col in df.columns:
        s = df[col]
        col_info: dict = {
            "dtype": str(s.dtype),
            "null_count": int(s.isna().sum()),
            "null_pct": round(float(s.isna().mean()) * 100, 3),
            "distinct_count": int(s.nunique(dropna=True)),
        }

        non_null = s.dropna()
        if len(non_null) == 0:
            col_info["sample_values"] = []
        else:
            sample = non_null.value_counts().head(5)
            col_info["top_values"] = {
                str(k): int(v) for k, v in sample.items()
            }

        if pd.api.types.is_numeric_dtype(s) and len(non_null) > 0:
            col_info["min"] = float(non_null.min())
            col_info["max"] = float(non_null.max())
            col_info["mean"] = round(float(non_null.mean()), 4)
            col_info["std"] = round(float(non_null.std()), 4) if len(non_null) > 1 else 0.0
        elif pd.api.types.is_datetime64_any_dtype(s) and len(non_null) > 0:
            col_info["min"] = str(non_null.min())
            col_info["max"] = str(non_null.max())
        elif pd.api.types.is_string_dtype(s) or s.dtype == object:
            lengths = non_null.astype(str).str.len()
            if len(lengths) > 0:
                col_info["min_length"] = int(lengths.min())
                col_info["max_length"] = int(lengths.max())

        summary["columns"][col] = col_info

    freshness = _freshness_check(df)
    summary["freshness"] = freshness
    if freshness:
        for col, col_freshness in freshness["by_column"].items():
            summary["columns"][col]["freshness"] = col_freshness

    return summary


def _generate_html_report(df: pd.DataFrame, output_path: Path) -> dict:
    """Generate a ydata-profiling HTML report. Returns metadata for logging.

    Failures here are non-fatal: the JSON summary is the source of truth,
    and the HTML report is a convenience. A bad column type or one weird
    cell shouldn't break the run.
    """
    if not _YDATA_AVAILABLE:
        return {"html_report": None, "skipped": "ydata-profiling not installed"}

    try:
        from ydata_profiling import ProfileReport

        # `minimal=True` skips correlations and interactions, which are the
        # expensive parts on wide datasets and rarely earn their cost for
        # dictionary-drafting purposes. Users who want the full report can
        # pass --full-profile in a future flag.
        report = ProfileReport(df, minimal=True, progress_bar=False)
        report.to_file(output_path)
        return {"html_report": str(output_path), "skipped": None}
    except Exception as exc:  # noqa: BLE001
        # Never let the HTML side break the JSON side. Log the reason and
        # move on — the JSON summary is the contract.
        return {
            "html_report": None,
            "skipped": f"ydata-profiling failed: {type(exc).__name__}: {exc}",
        }


def run(
    df: pd.DataFrame,
    workdir: str | Path,
    log: TransformationLog | None = None,
    redact_pii: bool = False,
) -> dict:
    workdir = Path(workdir)
    summary = profile(df)

    if redact_pii:
        summary = redact_profile(summary)

    (workdir / "profile_summary.json").write_text(json.dumps(summary, indent=2, default=str))

    html_meta = _generate_html_report(df, workdir / "profile_report.html")

    if log:
        log.log(
            stage="s1_profile",
            event="profile_generated",
            rows_affected=len(df),
            details={
                "column_count": len(df.columns),
                "pii_redacted": redact_pii,
                **html_meta,
            },
        )
    return summary
