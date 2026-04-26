"""Tests for cross-field validation in Stage 8 (s8_validate.py)."""
from __future__ import annotations

import pandas as pd
import pytest

from dictionary_pipeline.contract import Contract, FieldSpec
from dictionary_pipeline.stages.s8_validate import _cross_field_checks


# ---------- helpers -----------------------------------------------------------


def _make_contract(*field_specs: FieldSpec) -> Contract:
    return Contract(
        dataset_name="test",
        description="",
        source="",
        grain="",
        pii=False,
        pii_fields=[],
        naming_convention="snake_case",
        last_updated="",
        fields=list(field_specs),
    )


def _make_field(name: str, dtype: str = "string") -> FieldSpec:
    return FieldSpec(name=name, label=name, type=dtype, dtype=dtype)


# ---------- date ordering checks ----------------------------------------------


class TestDateOrdering:
    def test_start_date_after_end_date_violation_detected(self):
        """Row where start_date > end_date should be counted as a violation."""
        df = pd.DataFrame({
            "start_date": pd.to_datetime(["2024-01-10", "2024-01-01"]),
            "end_date": pd.to_datetime(["2024-01-05", "2024-01-31"]),
        })
        contract = _make_contract(
            _make_field("start_date", "datetime64[ns]"),
            _make_field("end_date", "datetime64[ns]"),
        )

        result = _cross_field_checks(df, contract)

        date_checks = [r for r in result if r["check"] == "date_ordering"]
        assert len(date_checks) == 1
        assert date_checks[0]["violations"] == 1
        assert set(date_checks[0]["columns"]) == {"start_date", "end_date"}

    def test_start_date_equal_to_end_date_is_not_a_violation(self):
        """Rows where start == end should be fine (same-day spans are valid)."""
        df = pd.DataFrame({
            "start_date": pd.to_datetime(["2024-01-01"]),
            "end_date": pd.to_datetime(["2024-01-01"]),
        })
        contract = _make_contract(
            _make_field("start_date", "datetime64[ns]"),
            _make_field("end_date", "datetime64[ns]"),
        )

        result = _cross_field_checks(df, contract)

        date_checks = [r for r in result if r["check"] == "date_ordering"]
        assert all(c["violations"] == 0 for c in date_checks)

    def test_created_at_after_updated_at_detected(self):
        """created_at/updated_at is an exact pair; violation should be flagged."""
        df = pd.DataFrame({
            "created_at": pd.to_datetime(["2024-01-10"]),
            "updated_at": pd.to_datetime(["2024-01-05"]),
        })
        contract = _make_contract(
            _make_field("created_at", "datetime64[ns]"),
            _make_field("updated_at", "datetime64[ns]"),
        )

        result = _cross_field_checks(df, contract)

        date_checks = [r for r in result if r["check"] == "date_ordering"]
        assert any(c["violations"] > 0 for c in date_checks)

    def test_open_close_pair_detected(self):
        """open_date/close_date should be treated as a temporal ordering pair."""
        df = pd.DataFrame({
            "open_date": pd.to_datetime(["2024-06-01", "2024-01-01"]),
            "close_date": pd.to_datetime(["2024-05-01", "2024-12-31"]),
        })
        contract = _make_contract(
            _make_field("open_date", "datetime64[ns]"),
            _make_field("close_date", "datetime64[ns]"),
        )

        result = _cross_field_checks(df, contract)

        date_checks = [r for r in result if r["check"] == "date_ordering"]
        assert len(date_checks) == 1
        assert date_checks[0]["violations"] == 1


# ---------- numeric range checks ----------------------------------------------


class TestNumericRange:
    def test_min_greater_than_max_violation_detected(self):
        """Row where min_price > max_price should be flagged."""
        df = pd.DataFrame({
            "min_price": [100.0, 10.0],
            "max_price": [50.0, 20.0],
        })
        contract = _make_contract(
            _make_field("min_price", "float64"),
            _make_field("max_price", "float64"),
        )

        result = _cross_field_checks(df, contract)

        range_checks = [r for r in result if r["check"] == "numeric_range"]
        assert len(range_checks) == 1
        assert range_checks[0]["violations"] == 1
        assert set(range_checks[0]["columns"]) == {"min_price", "max_price"}

    def test_min_equal_to_max_is_not_a_violation(self):
        """min == max is a degenerate range but not a logical error."""
        df = pd.DataFrame({
            "min_price": [50.0],
            "max_price": [50.0],
        })
        contract = _make_contract(
            _make_field("min_price", "float64"),
            _make_field("max_price", "float64"),
        )

        result = _cross_field_checks(df, contract)

        range_checks = [r for r in result if r["check"] == "numeric_range"]
        assert all(c["violations"] == 0 for c in range_checks)

    def test_low_high_pair_detected(self):
        """low/high is an alternative naming convention for range pairs."""
        df = pd.DataFrame({
            "low": [10.0, 5.0],
            "high": [5.0, 20.0],
        })
        contract = _make_contract(
            _make_field("low", "float64"),
            _make_field("high", "float64"),
        )

        result = _cross_field_checks(df, contract)

        range_checks = [r for r in result if r["check"] == "numeric_range"]
        assert len(range_checks) == 1
        assert range_checks[0]["violations"] == 1


# ---------- clean data produces no violations ---------------------------------


class TestCleanData:
    def test_clean_data_produces_no_violations(self):
        """All checks on well-ordered data should return zero violations."""
        df = pd.DataFrame({
            "start_date": pd.to_datetime(["2024-01-01", "2024-02-01"]),
            "end_date": pd.to_datetime(["2024-01-31", "2024-02-28"]),
            "min_score": [0.0, 5.0],
            "max_score": [10.0, 10.0],
        })
        contract = _make_contract(
            _make_field("start_date", "datetime64[ns]"),
            _make_field("end_date", "datetime64[ns]"),
            _make_field("min_score", "float64"),
            _make_field("max_score", "float64"),
        )

        result = _cross_field_checks(df, contract)

        assert all(r["violations"] == 0 for r in result)

    def test_no_recognisable_pairs_returns_empty_list(self):
        """When no pair heuristics match, the result list is empty."""
        df = pd.DataFrame({
            "name": ["Alice", "Bob"],
            "age": [30, 25],
        })
        contract = _make_contract(
            _make_field("name", "string"),
            _make_field("age", "Int64"),
        )

        result = _cross_field_checks(df, contract)

        # No date/range/referential/mutex patterns present
        assert result == []


# ---------- mutually exclusive nulls -----------------------------------------


class TestMutuallyExclusiveNulls:
    def test_perfectly_exclusive_null_columns_detected(self):
        """Columns where one is always null when the other has a value → flagged."""
        df = pd.DataFrame({
            "individual_name": ["Alice", None, "Bob", None],
            "company_name": [None, "Acme", None, "Globex"],
        })
        contract = _make_contract(
            _make_field("individual_name", "string"),
            _make_field("company_name", "string"),
        )

        result = _cross_field_checks(df, contract)

        mutex_checks = [r for r in result if r["check"] == "mutually_exclusive_nulls"]
        assert len(mutex_checks) == 1
        assert set(mutex_checks[0]["columns"]) == {"individual_name", "company_name"}

    def test_columns_with_overlapping_values_not_flagged(self):
        """When both columns are non-null on the same row, pattern is not present."""
        df = pd.DataFrame({
            "col_a": ["Alice", None, "Bob", "Carol"],
            "col_b": [None, "X", None, "Y"],
        })
        contract = _make_contract(
            _make_field("col_a", "string"),
            _make_field("col_b", "string"),
        )

        result = _cross_field_checks(df, contract)

        mutex_checks = [r for r in result if r["check"] == "mutually_exclusive_nulls"]
        assert len(mutex_checks) == 0

    def test_column_with_no_nulls_not_considered_for_mutex(self):
        """A column with zero nulls cannot form a mutex pair (nothing to exclude)."""
        df = pd.DataFrame({
            "always_present": ["A", "B", "C"],
            "sometimes_null": ["X", None, "Z"],
        })
        contract = _make_contract(
            _make_field("always_present", "string"),
            _make_field("sometimes_null", "string"),
        )

        result = _cross_field_checks(df, contract)

        mutex_checks = [r for r in result if r["check"] == "mutually_exclusive_nulls"]
        assert len(mutex_checks) == 0


# ---------- result structure --------------------------------------------------


class TestResultStructure:
    def test_result_is_list_of_dicts_with_required_keys(self):
        """Every entry must have check, columns, violations, sample_rows."""
        df = pd.DataFrame({
            "start_date": pd.to_datetime(["2024-01-10"]),
            "end_date": pd.to_datetime(["2024-01-05"]),
        })
        contract = _make_contract(
            _make_field("start_date", "datetime64[ns]"),
            _make_field("end_date", "datetime64[ns]"),
        )

        result = _cross_field_checks(df, contract)

        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, dict)
            assert "check" in item
            assert "columns" in item
            assert "violations" in item
            assert "sample_rows" in item

    def test_sample_rows_capped_at_five(self):
        """Even with many violations, sample_rows must not exceed 5 entries."""
        df = pd.DataFrame({
            "min_val": [100.0] * 10,
            "max_val": [10.0] * 10,
        })
        contract = _make_contract(
            _make_field("min_val", "float64"),
            _make_field("max_val", "float64"),
        )

        result = _cross_field_checks(df, contract)

        range_checks = [r for r in result if r["check"] == "numeric_range"]
        assert len(range_checks) == 1
        assert range_checks[0]["violations"] == 10
        assert len(range_checks[0]["sample_rows"]) <= 5
