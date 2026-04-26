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

Every LLM judgment is logged as an assumption with confidence/impact
scoring via the AssumptionLog (see assumptions.py).  The log is saved
alongside the pipeline output for human review.

Wire your Claude entry point in `_call_claude`. See s3_dictionary.py for
reference implementations.
"""

from __future__ import annotations

import json

import pandas as pd

from ..assumptions import AssumptionLog
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
    assumption_log: AssumptionLog | None = None,
) -> pd.DataFrame:
    """Normalize the named column via an LLM judgment call.

    If *assumption_log* is provided, every normalization mapping is
    recorded as an assumption with confidence and impact scoring for
    downstream human review.
    """
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

    changed = int((df[field_name] != out[field_name]).sum())

    # ---- record assumptions ----
    if assumption_log is not None:
        # One assumption per distinct normalization decision
        for original, normalized in mapping.items():
            if str(original) != str(normalized):
                row_count = int(counts.get(original, 0))
                # High-frequency values get higher impact
                impact = (
                    "high" if row_count > len(df) * 0.05
                    else "medium" if row_count > 10
                    else "low"
                )
                assumption_log.add(
                    stage="s6_judgment",
                    category="normalization",
                    assumption=(
                        f"{field_name}: '{original}' -> '{normalized}'"
                    ),
                    rationale=(
                        f"LLM normalized value in column '{field_label}'. "
                        f"Affected {row_count} rows."
                    ),
                    confidence="medium",
                    impact_if_wrong=impact,
                    validation_plan=(
                        f"Verify '{original}' and '{normalized}' are "
                        f"semantically equivalent for column '{field_name}'."
                    ),
                )

    if log:
        log.log(
            stage="s6_judgment",
            event=f"normalized_column_{field_name}",
            rows_affected=changed,
            details={
                "distinct_mappings": len(mapping),
                "assumptions_logged": (
                    len([
                        1 for o, n in mapping.items() if str(o) != str(n)
                    ])
                    if assumption_log is not None
                    else 0
                ),
            },
        )
    return out
