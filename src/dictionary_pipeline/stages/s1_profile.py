"""
Stage 1 — Automated Profile.

Replaces /audit-xls with a deterministic profile. Outputs a JSON summary
suitable for handing to Claude in stage 3 (draft dictionary).

Intentionally lightweight — no ydata-profiling dependency for the core
build. You can swap in ydata-profiling later by replacing `profile()`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..logging import TransformationLog
from ..pii import redact_profile


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
    if log:
        log.log(
            stage="s1_profile",
            event="profile_generated",
            rows_affected=len(df),
            details={"column_count": len(df.columns), "pii_redacted": redact_pii},
        )
    return summary
