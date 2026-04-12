"""
Stage 6 — Judgment Cleaning (LLM-in-the-loop, STUB).

Only invoked when Stage 5 leaves cases the rules couldn't decide.
The DataFrame passed to Claude here should be MINIMAL — just the
ambiguous rows and the column being decided on, nothing else.

Pattern:
  1. Caller identifies ambiguous cases (e.g., kids/beverage category variants)
  2. Calls run() with just those rows + the field name
  3. Claude returns a mapping: original_value -> normalized_value
  4. Caller applies the mapping to the full DataFrame

Wire your Claude entry point in `_call_claude`. See s3_dictionary.py for
reference implementations.
"""

from __future__ import annotations

import json

import pandas as pd

from ..logging import TransformationLog

PROMPT_TEMPLATE = """You are normalizing values in a single column.

COLUMN: {field_name}
COLUMN PURPOSE: {field_label}
NOTES FROM DICTIONARY: {field_notes}

DISTINCT VALUES TO NORMALIZE (with counts):
{value_counts}

Return a JSON object mapping each original value to a normalized canonical value.
Group syntactic variants together (e.g., "Kids Menu" / "Kid's Menu" / "Kids' Menu").
Do NOT merge values that represent semantically distinct things even if similar.

Return ONLY the JSON object, no preamble.
"""


def _call_claude(prompt: str) -> str:
    raise NotImplementedError(
        "Stage 6 needs a Claude entry point. Edit _call_claude() in s6_judgment.py."
    )


def normalize_column(
    df: pd.DataFrame,
    field_name: str,
    field_label: str,
    field_notes: str,
    log: TransformationLog | None = None,
) -> pd.DataFrame:
    """Normalize the named column via an LLM judgment call."""
    counts = df[field_name].value_counts(dropna=False)
    value_counts_text = "\n".join(f"  {v!r}: {c}" for v, c in counts.items())

    prompt = PROMPT_TEMPLATE.format(
        field_name=field_name,
        field_label=field_label,
        field_notes=field_notes,
        value_counts=value_counts_text,
    )

    response = _call_claude(prompt)
    mapping: dict = json.loads(response)

    out = df.copy()
    out[field_name] = out[field_name].map(lambda v: mapping.get(v, v))

    if log:
        changed = int((df[field_name] != out[field_name]).sum())
        log.log(
            stage="s6_judgment",
            event=f"normalized_column_{field_name}",
            rows_affected=changed,
            details={"distinct_mappings": len(mapping)},
        )
    return out
