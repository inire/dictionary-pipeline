"""
Stage 7 — Derived Columns.

Thin wrapper around contract.apply_derivations(). The dictionary's
`derived_fields` section is the spec; this stage just executes it.
"""

from __future__ import annotations

import pandas as pd

from ..contract import (
    Contract,
    _RE_BINARY_OP,
    _RE_GROUPBY_AGG,
    _RE_GROUPBY_SIZE,
    apply_derivations,
)
from ..logging import TransformationLog


def _check_null_propagation(
    df_before: pd.DataFrame,
    df_after: pd.DataFrame,
    contract: Contract,
) -> list[dict]:
    """
    Check for null propagation in derived columns.

    For each derived field, parse its source columns from the transformation
    expression, count nulls in sources vs. the derived column, and flag
    amplification when the derived column has more nulls than any single source.

    Returns a list of warning dicts (empty when no nulls are involved):
        {
            "derived_field": str,
            "source_nulls": {col: count, ...},
            "derived_nulls": int,
            "amplified": bool,
        }
    """
    warnings = []

    for d in contract.derived_fields:
        t = d.transformation.strip()

        # --- extract source column names from the transformation expression ---
        source_cols: list[str] = []

        m = _RE_BINARY_OP.match(t)
        if m:
            source_cols = [m.group(1), m.group(3)]
        else:
            m = _RE_GROUPBY_SIZE.match(t)
            if m:
                source_cols = [m.group(1)]
            else:
                m = _RE_GROUPBY_AGG.match(t)
                if m:
                    source_cols = [m.group(1), m.group(2)]

        if not source_cols:
            continue

        # --- count nulls in source columns (from df_before) ---
        source_nulls = {
            col: int(df_before[col].isna().sum())
            for col in source_cols
            if col in df_before.columns
        }

        # --- count nulls in the derived column (from df_after) ---
        if d.name not in df_after.columns:
            continue
        derived_nulls = int(df_after[d.name].isna().sum())

        # no nulls anywhere → nothing to warn about
        if all(n == 0 for n in source_nulls.values()) and derived_nulls == 0:
            continue

        max_source_nulls = max(source_nulls.values()) if source_nulls else 0
        amplified = derived_nulls > max_source_nulls

        warnings.append(
            {
                "derived_field": d.name,
                "source_nulls": source_nulls,
                "derived_nulls": derived_nulls,
                "amplified": amplified,
            }
        )

    return warnings


def run(
    df: pd.DataFrame,
    contract: Contract,
    log: TransformationLog | None = None,
) -> pd.DataFrame:
    out = apply_derivations(df, contract)
    if log:
        log.log(
            stage="s7_derive",
            event="derivations_applied",
            rows_affected=len(out),
            details={"new_columns": [d.name for d in contract.derived_fields]},
        )
    null_warnings = _check_null_propagation(df, out, contract)
    if log:
        for w in null_warnings:
            log.log(
                stage="s7_derive",
                event="null_propagation_warning",
                rows_affected=w["derived_nulls"],
                details=w,
            )
    return out
