"""Tests for null propagation warnings in Stage 7 (s7_derive.py)."""
from __future__ import annotations

import pandas as pd
import pytest

from dictionary_pipeline.contract import Contract, DerivedFieldSpec
from dictionary_pipeline.logging import TransformationLog
from dictionary_pipeline.stages.s7_derive import _check_null_propagation, run


def _make_contract(*derived_fields: DerivedFieldSpec) -> Contract:
    return Contract(
        dataset_name="test",
        description="",
        source="",
        grain="",
        pii=False,
        pii_fields=[],
        naming_convention="snake_case",
        last_updated="2026-01-01",
        derived_fields=list(derived_fields),
    )


def _derived(name: str, transformation: str) -> DerivedFieldSpec:
    return DerivedFieldSpec(
        name=name,
        label=name,
        type="decimal",
        dtype="float64",
        transformation=transformation,
    )


class TestCheckNullPropagation:
    """Unit tests for _check_null_propagation()."""

    def test_no_nulls_returns_empty_list(self):
        """No nulls in sources or derived column → no warnings."""
        df_before = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})
        df_after = df_before.copy()
        df_after["c"] = df_before["a"] + df_before["b"]
        contract = _make_contract(_derived("c", "a + b"))

        result = _check_null_propagation(df_before, df_after, contract)

        assert result == []

    def test_source_null_generates_warning(self):
        """Source column has 1 null → warning with correct counts, not amplified."""
        df_before = pd.DataFrame({"a": [1.0, None], "b": [3.0, 4.0]})
        df_after = df_before.copy()
        df_after["c"] = df_before["a"] + df_before["b"]
        contract = _make_contract(_derived("c", "a + b"))

        result = _check_null_propagation(df_before, df_after, contract)

        assert len(result) == 1
        w = result[0]
        assert w["derived_field"] == "c"
        assert w["source_nulls"] == {"a": 1, "b": 0}
        assert w["derived_nulls"] == 1
        assert w["amplified"] is False

    def test_null_amplification_flagged(self):
        """A has 2 nulls, B has 3 nulls at disjoint rows → A/B inherits all 5 → amplified."""
        # a: nulls at rows 0,1 (2 nulls)
        # b: nulls at rows 2,3,4 (3 nulls)
        # a/b: NaN wherever either operand is NaN → rows 0,1,2,3,4 → 5 nulls
        # 5 > max(2,3) = 3, so amplified
        df_before = pd.DataFrame({
            "a": [None, None, 1.0, 2.0, 3.0],
            "b": [4.0, 5.0, None, None, None],
        })
        df_after = df_before.copy()
        df_after["ratio"] = df_before["a"] / df_before["b"]
        contract = _make_contract(_derived("ratio", "a / b"))

        result = _check_null_propagation(df_before, df_after, contract)

        assert len(result) == 1
        w = result[0]
        assert w["derived_field"] == "ratio"
        assert w["source_nulls"] == {"a": 2, "b": 3}
        assert w["derived_nulls"] == 5
        assert w["amplified"] is True

    def test_groupby_agg_source_null_warning(self):
        """Null in aggregated field for groupby agg → warning generated."""
        df_before = pd.DataFrame({
            "grp": ["x", "x", "y"],
            "val": [1.0, None, 3.0],
        })
        df_after = df_before.copy()
        df_after["val_sum"] = df_before.groupby("grp")["val"].transform("sum")
        contract = _make_contract(_derived("val_sum", "groupby(grp).val.sum()"))

        result = _check_null_propagation(df_before, df_after, contract)

        assert len(result) == 1
        w = result[0]
        assert w["derived_field"] == "val_sum"
        assert w["source_nulls"]["val"] == 1


class TestRunLogsWarnings:
    """Integration tests: run() logs null propagation warnings via TransformationLog."""

    def test_run_logs_warning_when_source_has_nulls(self, tmp_path):
        """run() emits null_propagation_warning event for each flagged derivation."""
        tlog = TransformationLog(tmp_path / "transform.jsonl")
        df = pd.DataFrame({"a": [1.0, None], "b": [3.0, 4.0]})
        contract = _make_contract(_derived("c", "a + b"))

        run(df, contract, log=tlog)

        events = tlog.read_all()
        warnings = [e for e in events if e["event"] == "null_propagation_warning"]
        assert len(warnings) == 1
        assert warnings[0]["stage"] == "s7_derive"
        assert warnings[0]["details"]["derived_field"] == "c"

    def test_run_no_warning_event_when_clean(self, tmp_path):
        """run() does not emit null_propagation_warning when all sources are clean."""
        tlog = TransformationLog(tmp_path / "transform.jsonl")
        df = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})
        contract = _make_contract(_derived("c", "a + b"))

        run(df, contract, log=tlog)

        events = tlog.read_all()
        warnings = [e for e in events if e["event"] == "null_propagation_warning"]
        assert len(warnings) == 0

    def test_run_returns_df_unchanged_signature(self):
        """run() still returns the DataFrame with derived column (return type unchanged)."""
        df = pd.DataFrame({"a": [1.0, None], "b": [3.0, 4.0]})
        contract = _make_contract(_derived("c", "a + b"))

        result = run(df, contract)

        assert "c" in result.columns
        assert len(result) == len(df)
