"""
contract.py — the YAML dictionary <-> pandera schema bridge.

The dictionary YAML is the source of truth. This module:
  1. Loads it
  2. Validates its own internal structure
  3. Builds a pandera DataFrameSchema from the `fields` section
  4. Exposes derivation specs from the `derived_fields` section
  5. Maps source column names <-> field names

Stages 4, 5, 7, 8, 9 all consume the contract through this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import re

import pandas as pd
import pandera.pandas as pa
import yaml


# ---------- dataclass models ---------------------------------------------------


@dataclass
class FieldSpec:
    name: str
    label: str
    type: str
    dtype: str
    nullable: bool = False
    allowed_values: list[Any] | None = None
    min: float | None = None
    max: float | None = None
    pattern: str | None = None
    null_tolerance: float = 0.0
    source_column: str | None = None
    notes: str = ""
    review_status: str = "draft"
    pii: bool = False
    reliability: str = "reliable"
    parse_format: str | None = None
    shareable: bool = True
    community_notes: str = ""


@dataclass
class DerivedFieldSpec:
    name: str
    label: str
    type: str
    dtype: str
    transformation: str
    notes: str = ""
    review_status: str = "draft"


@dataclass
class Contract:
    dataset_name: str
    description: str
    source: str
    grain: str
    pii: bool
    pii_fields: list[str]
    naming_convention: str
    last_updated: str
    community_version: str = ""
    fields: list[FieldSpec] = field(default_factory=list)
    derived_fields: list[DerivedFieldSpec] = field(default_factory=list)

    # ---- lookups ----

    def field_by_name(self, name: str) -> FieldSpec | None:
        return next((f for f in self.fields if f.name == name), None)

    def source_to_field_map(self) -> dict[str, str]:
        return {f.source_column: f.name for f in self.fields if f.source_column}

    def field_names(self) -> list[str]:
        return [f.name for f in self.fields]

    def derived_names(self) -> list[str]:
        return [d.name for d in self.derived_fields]


# ---------- loading ------------------------------------------------------------


def load_contract(path: str | Path) -> Contract:
    """Load a dictionary YAML file into a Contract object."""
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    ds = raw.get("dataset", {})
    fields = [FieldSpec(**_clean(f)) for f in raw.get("fields", [])]
    derived = [DerivedFieldSpec(**_clean(d)) for d in raw.get("derived_fields", [])]

    return Contract(
        dataset_name=ds.get("name", "unnamed"),
        description=ds.get("description", ""),
        source=ds.get("source", ""),
        grain=ds.get("grain", ""),
        pii=ds.get("pii", False),
        pii_fields=ds.get("pii_fields", []),
        naming_convention=ds.get("naming_convention", "snake_case"),
        last_updated=ds.get("last_updated", ""),
        community_version=ds.get("community_version", ""),
        fields=fields,
        derived_fields=derived,
    )


def _clean(d: dict) -> dict:
    """Drop keys not in the dataclass and normalize None values."""
    allowed_field_keys = {f for f in FieldSpec.__dataclass_fields__}
    allowed_derived_keys = {f for f in DerivedFieldSpec.__dataclass_fields__}
    if "transformation" in d:
        return {k: v for k, v in d.items() if k in allowed_derived_keys}
    return {k: v for k, v in d.items() if k in allowed_field_keys}


# ---------- pandera schema construction ---------------------------------------


# Map our type names to pandera dtype + Check builders
_DTYPE_MAP = {
    "string": pa.String,
    "Int64": pa.Int64,
    "int64": pa.Int64,
    "float64": pa.Float64,
    "datetime64[ns]": pa.DateTime,
    "bool": pa.Bool,
}


def build_pandera_schema(contract: Contract) -> pa.DataFrameSchema:
    """Convert a Contract into a pandera DataFrameSchema for enforcement."""
    columns: dict[str, pa.Column] = {}

    for spec in contract.fields:
        checks: list[pa.Check] = []

        if spec.allowed_values is not None:
            checks.append(pa.Check.isin(spec.allowed_values))
        if spec.min is not None:
            checks.append(pa.Check.greater_than_or_equal_to(spec.min))
        if spec.max is not None:
            checks.append(pa.Check.less_than_or_equal_to(spec.max))
        if spec.pattern is not None:
            checks.append(pa.Check.str_matches(spec.pattern))

        dtype = _DTYPE_MAP.get(spec.dtype, pa.String)

        columns[spec.name] = pa.Column(
            dtype=dtype,
            checks=checks if checks else None,
            nullable=spec.nullable or spec.null_tolerance > 0,
            coerce=True,
            description=spec.label,
        )

    return pa.DataFrameSchema(
        columns=columns,
        strict="filter",  # drop columns not in the contract
        coerce=True,
    )


# ---------- derivation execution ----------------------------------------------

_RE_BINARY_OP = re.compile(r"^(\w+)\s*([+\-*/])\s*(\w+)$")
_RE_GROUPBY_SIZE = re.compile(r"^groupby\((\w+)\)\.size\(\)$")
_RE_GROUPBY_AGG = re.compile(r"^groupby\((\w+)\)\.(\w+)\.(sum|mean|min|max)\(\)$")

_BINARY_OPS: dict[str, Any] = {
    "/": lambda a, b: a / b,
    "*": lambda a, b: a * b,
    "+": lambda a, b: a + b,
    "-": lambda a, b: a - b,
}


def _require_columns(df: pd.DataFrame, *cols: str, transformation: str) -> None:
    """Raise KeyError if any referenced columns are missing from the DataFrame."""
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise KeyError(
            f"Derivation {transformation!r} references columns not in "
            f"DataFrame: {missing}"
        )


def apply_derivations(df: pd.DataFrame, contract: Contract) -> pd.DataFrame:
    """
    Execute the derivations from the contract.

    Patterns are matched by regex — no eval(). Supported families:

      <field_a> +|-|*|/ <field_b>       element-wise arithmetic
      groupby(<key>).size()              per-group row count
      groupby(<key>).<field>.sum()       per-group aggregation (sum/mean/min/max)
    """
    out = df.copy()

    for d in contract.derived_fields:
        t = d.transformation.strip()

        m = _RE_BINARY_OP.match(t)
        if m:
            left, op, right = m.group(1), m.group(2), m.group(3)
            _require_columns(out, left, right, transformation=t)
            out[d.name] = _BINARY_OPS[op](out[left], out[right])
            continue

        m = _RE_GROUPBY_SIZE.match(t)
        if m:
            key = m.group(1)
            _require_columns(out, key, transformation=t)
            out[d.name] = out.groupby(key)[key].transform("size")
            continue

        m = _RE_GROUPBY_AGG.match(t)
        if m:
            key, field, agg = m.group(1), m.group(2), m.group(3)
            _require_columns(out, key, field, transformation=t)
            out[d.name] = out.groupby(key)[field].transform(agg)
            continue

        raise NotImplementedError(
            f"Derivation pattern not registered: {t!r}. "
            f"Supported: '<a> +-*/ <b>', 'groupby(<k>).size()', "
            f"'groupby(<k>).<f>.sum|mean|min|max()'."
        )

    return out


# ---------- column rename helper ----------------------------------------------


def rename_to_contract(df: pd.DataFrame, contract: Contract) -> pd.DataFrame:
    """Rename source columns to contract field names."""
    mapping = contract.source_to_field_map()
    return df.rename(columns=mapping)
