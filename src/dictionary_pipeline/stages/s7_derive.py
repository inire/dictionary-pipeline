"""
Stage 7 — Derived Columns.

Thin wrapper around contract.apply_derivations(). The dictionary's
`derived_fields` section is the spec; this stage just executes it.
"""

from __future__ import annotations

import pandas as pd

from ..contract import Contract, apply_derivations
from ..logging import TransformationLog


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
    return out
