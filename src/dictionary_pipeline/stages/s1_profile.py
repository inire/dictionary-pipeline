"""
Stage 1 — Automated Profile.

Replaces /audit-xls with a deterministic profile. Outputs a JSON summary
suitable for handing to Claude in stage 3 (draft dictionary).

Includes:
  - Per-column dtype, null, distinct, top-value stats
  - Outlier detection (IQR + z-score) for numeric columns
  - Duplicate detection (full-row and per-column)
  - Freshness check for datetime columns

Intentionally lightweight — no ydata-profiling dependency for the core
build. You can swap in ydata-profiling later by replacing `profile()`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ..logging import TransformationLog
from ..pii import redact_profile


# ---------------------------------------------------------------------------
#  Outlier detection helpers
# ---------------------------------------------------------------------------


def _detect_outliers_iqr(series: pd.Series, k: float = 1.5) -> pd.Series:
    """Flag values outside the IQR fence."""
    q1, q3 = series.quantile(0.25), series.quantile(0.75)
    iqr = q3 - q1
    return (series < q1 - k * iqr) | (series > q3 + k * iqr)


def _detect_outliers_zscore(series: pd.Series, threshold: float = 3.0) -> pd.Series:
    """Flag values beyond *threshold* standard deviations from the mean."""
    if series.std(ddof=1) == 0:
        return pd.Series(False, index=series.index)
    z = (series - series.mean()) / series.std(ddof=1)
    return z.abs() > threshold


def _outlier_summary(series: pd.Series) -> dict:
    """Return an outlier report dict for a single numeric column."""
    non_null = series.dropna()
    if len(non_null) < 4:          # need enough data for IQR
        return {"skipped": True, "reason": "too few values"}

    iqr_mask = _detect_outliers_iqr(non_null)
    z_mask = _detect_outliers_zscore(non_null)
    combined = iqr_mask | z_mask

    return {
        "outlier_count": int(combined.sum()),
        "outlier_pct": round(float(combined.mean()) * 100, 2),
        "iqr_outliers": int(iqr_mask.sum()),
        "zscore_outliers": int(z_mask.sum()),
    }


# ---------------------------------------------------------------------------
#  Duplicate detection helpers
# ---------------------------------------------------------------------------


def _duplicate_summary(df: pd.DataFrame) -> dict:
    """Return full-row duplicate stats for the DataFrame."""
    full_dupes = int(df.duplicated().sum())
    return {
        "full_row_duplicate_count": full_dupes,
        "full_row_duplicate_pct": round(full_dupes / max(len(df), 1) * 100, 2),
    }


# ---------------------------------------------------------------------------
#  Freshness check helper
# ---------------------------------------------------------------------------


def _freshness_summary(series: pd.Series) -> dict | None:
    """If *series* is datetime-like, report how stale the newest record is."""
    ts = pd.to_datetime(series, errors="coerce", utc=True)
    valid = ts.dropna()
    if valid.empty:
        return None
    latest = valid.max().to_pydatetime()
    now = datetime.now(timezone.utc)
    lag_hours = round((now - latest).total_seconds() / 3600, 2)
    return {
        "latest_record": latest.isoformat(),
        "lag_hours": lag_hours,
    }


# ---------------------------------------------------------------------------
#  Main profiler
# ---------------------------------------------------------------------------


def profile(df: pd.DataFrame) -> dict:
    """Return a serializable profile of *df*.

    The output dict contains per-column stats plus top-level duplicate
    info.  Numeric columns get an ``outliers`` sub-dict (IQR + z-score).
    Datetime columns get a ``freshness`` sub-dict.
    """
    summary: dict = {
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "duplicates": _duplicate_summary(df),
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
            col_info["outliers"] = _outlier_summary(s)

            # Flag suspicious rounding (>95% whole numbers in a float col)
            if not pd.api.types.is_integer_dtype(s) and len(non_null) > 10:
                round_pct = float((non_null % 1 == 0).mean())
                if 0.95 < round_pct < 1.0:
                    col_info["suspicious_rounding"] = True
                    col_info["whole_number_pct"] = round(round_pct * 100, 1)

            # Flag infinity values
            inf_count = int(np.isinf(non_null).sum())
            if inf_count > 0:
                col_info["infinity_count"] = inf_count

        elif pd.api.types.is_datetime64_any_dtype(s) and len(non_null) > 0:
            col_info["min"] = str(non_null.min())
            col_info["max"] = str(non_null.max())
            freshness = _freshness_summary(s)
            if freshness:
                col_info["freshness"] = freshness

            # Flag future dates
            try:
                ts = pd.to_datetime(non_null, errors="coerce", utc=True)
                tomorrow = datetime.now(timezone.utc).replace(
                    hour=23, minute=59, second=59
                )
                future_count = int((ts.dropna() > tomorrow).sum())
                if future_count > 0:
                    col_info["future_date_count"] = future_count
            except Exception:
                pass

        elif pd.api.types.is_string_dtype(s) or s.dtype == object:
            lengths = non_null.astype(str).str.len()
            if len(lengths) > 0:
                col_info["min_length"] = int(lengths.min())
                col_info["max_length"] = int(lengths.max())

        summary["columns"][col] = col_info

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
