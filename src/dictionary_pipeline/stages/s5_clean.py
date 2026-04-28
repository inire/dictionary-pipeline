"""
Stage 5 — Rule-Based Cleaning.

Deterministic, type-aware cleanup. Anything that requires judgment goes
to Stage 6 (s6_judgment.py), not here.

Currently implements:
  - whitespace stripping on string columns
  - duplicate row removal (full-row exact match)
  - fuzzy near-duplicate detection (requires rapidfuzz; skipped gracefully if missing)

Extend with dateutil, etc. as your datasets demand.
"""

from __future__ import annotations

import pandas as pd

from ..contract import Contract
from ..logging import TransformationLog

try:
    from rapidfuzz import fuzz as _fuzz
    _RAPIDFUZZ_AVAILABLE = True
except ImportError:  # pragma: no cover
    _RAPIDFUZZ_AVAILABLE = False


_TEXT_TYPES = {"text", "categorical", "categorical_open", "identifier"}


def _fuzzy_near_dupes(
    df: pd.DataFrame,
    contract: Contract,
    threshold: float = 85.0,
) -> dict:
    """Detect near-duplicate rows using fuzzy string matching.

    Only compares rows within a sliding window of 500 rows (sorted by the
    first text column) to keep complexity manageable.  Exact duplicates are
    assumed to have already been removed by the caller.

    Returns a report dict:
      {
        "near_duplicate_pairs": [
          {"row_a": int, "row_b": int, "similarity": float, "key_diffs": {col: [val_a, val_b]}}
        ],
        "threshold": float,
      }
    """
    if not _RAPIDFUZZ_AVAILABLE:
        return {"near_duplicate_pairs": [], "threshold": threshold, "skipped": "rapidfuzz not installed"}

    # Collect text-like columns present in the dataframe
    text_cols = [
        spec.name
        for spec in contract.fields
        if spec.type in _TEXT_TYPES and spec.name in df.columns
    ]

    if not text_cols:
        return {"near_duplicate_pairs": [], "threshold": threshold}

    # Sort by the first text column so nearby rows in sort order are compared
    sort_col = text_cols[0]
    # df arrives already reset_index'd from run(); sorted positions are the row refs
    sorted_df = df.sort_values(sort_col, na_position="last").reset_index(drop=True)

    n = len(sorted_df)
    window = 500
    pairs: list[dict] = []

    # Materialize the columns we care about into plain Python structures ONCE.
    # Inside the O(n × window) inner loop we then do O(1) dict / list lookups
    # instead of pandas .iloc — that single change drops a 500-row scan from
    # 60+s to under a second on representative TAM data.
    records: list[dict] = sorted_df[text_cols].to_dict(orient="records")
    null_masks: list[dict[str, bool]] = [
        {c: pd.isna(rec[c]) for c in text_cols} for rec in records
    ]

    def _row_str_from_record(rec: dict, nulls: dict[str, bool]) -> str:
        return " ".join(
            "" if nulls[c] else str(rec[c])
            for c in text_cols
        )

    row_strings = [
        _row_str_from_record(records[i], null_masks[i]) for i in range(n)
    ]

    def _cells_equal(rec_a: dict, rec_b: dict, nulls_a: dict, nulls_b: dict, c: str) -> bool:
        if nulls_a[c] and nulls_b[c]:
            return True
        if nulls_a[c] or nulls_b[c]:
            return False
        return rec_a[c] == rec_b[c]

    for i in range(n):
        rec_i = records[i]
        nulls_i = null_masks[i]
        for j in range(i + 1, min(i + 1 + window, n)):
            rec_j = records[j]
            nulls_j = null_masks[j]

            # Skip if all text columns are identical (exact dupe — already removed)
            if all(_cells_equal(rec_i, rec_j, nulls_i, nulls_j, c) for c in text_cols):
                continue

            similarity = _fuzz.ratio(row_strings[i], row_strings[j])
            if similarity >= threshold:
                key_diffs = {
                    c: [
                        None if nulls_i[c] else rec_i[c],
                        None if nulls_j[c] else rec_j[c],
                    ]
                    for c in text_cols
                    if not _cells_equal(rec_i, rec_j, nulls_i, nulls_j, c)
                }
                pairs.append({
                    "row_a": int(i),
                    "row_b": int(j),
                    "similarity": float(similarity),
                    "key_diffs": key_diffs,
                })

    return {"near_duplicate_pairs": pairs, "threshold": threshold}



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
    for spec in contract.fields:
        if spec.type in _TEXT_TYPES and spec.name in out.columns:
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

    # 3. fuzzy near-duplicate detection (report only — no auto-removal)
    near_dupe_report = _fuzzy_near_dupes(out, contract)
    pair_count = len(near_dupe_report.get("near_duplicate_pairs", []))
    if log:
        log.log(
            stage="s5_clean",
            event="near_duplicates_detected",
            rows_affected=pair_count,
            details=near_dupe_report,
        )

    return out
