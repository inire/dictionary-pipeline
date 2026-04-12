"""
Stage 5 — Rule-Based Cleaning.

Deterministic, type-aware cleanup. Anything that requires judgment goes
to Stage 6 (s6_judgment.py), not here.

Currently implements:
  - whitespace stripping on string columns
  - duplicate row removal (full-row exact match)

Extend with rapidfuzz, dateutil, etc. as your datasets demand.
"""

from __future__ import annotations

import pandas as pd

from ..contract import Contract
from ..logging import TransformationLog


def run(
    df: pd.DataFrame,
    contract: Contract,
    log: TransformationLog | None = None,
) -> pd.DataFrame:
    out = df.copy()
    events: list[tuple[str, int, dict]] = []

    # 1. strip whitespace on text/categorical/identifier columns
    #    NOTE: must preserve NaN — astype(str) on NaN yields "nan" (a string),
    #    which would silently corrupt nullable columns. Use .where() to skip nulls.
    text_types = {"text", "categorical", "categorical_open", "identifier"}
    for spec in contract.fields:
        if spec.type in text_types and spec.name in out.columns:
            col = out[spec.name]
            non_null_mask = col.notna()
            stripped = col.where(~non_null_mask, col.astype("string").str.strip())
            changed = int((col.fillna("\x00") != stripped.fillna("\x00")).sum())
            if changed:
                out[spec.name] = stripped
                events.append(("whitespace_stripped", changed, {"column": spec.name}))

    # 2. exact duplicate row removal
    before_n = len(out)
    out = out.drop_duplicates().reset_index(drop=True)
    dropped = before_n - len(out)
    if dropped:
        events.append(("exact_duplicates_removed", dropped, {}))

    if log:
        for event, n, details in events:
            log.log(stage="s5_clean", event=event, rows_affected=n, details=details)

    return out
