"""
Stage 4 — Schema Enforcement.

Loads the dictionary, builds a pandera schema, validates and coerces the
DataFrame. Failures are written to schema_violations.csv.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pandera.pandas as pa

from ..contract import Contract, build_pandera_schema, load_contract, rename_to_contract
from ..logging import TransformationLog


def run(
    df: pd.DataFrame,
    contract_path: str | Path,
    workdir: str | Path,
    log: TransformationLog | None = None,
) -> tuple[pd.DataFrame, Contract]:
    workdir = Path(workdir)
    contract = load_contract(contract_path)

    df = rename_to_contract(df, contract)
    schema = build_pandera_schema(contract)

    try:
        validated = schema.validate(df, lazy=True)
        if log:
            log.log(
                stage="s4_enforce",
                event="schema_validation_passed",
                rows_affected=len(validated),
                details={"contract": str(contract_path)},
            )
        return validated, contract
    except pa.errors.SchemaErrors as exc:
        violations_path = workdir / "schema_violations.csv"
        exc.failure_cases.to_csv(violations_path, index=False)
        if log:
            log.log(
                stage="s4_enforce",
                event="schema_validation_failed",
                rows_affected=int(len(exc.failure_cases)),
                details={"violations_path": str(violations_path)},
            )
        raise
