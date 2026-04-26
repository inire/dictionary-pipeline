"""Tests for Stage 8 QA checks (_qa_checks function)."""

from datetime import datetime, timedelta

import pandas as pd
import pytest

from dictionary_pipeline.contract import Contract, FieldSpec
from dictionary_pipeline.stages.s8_validate import _qa_checks


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


def _make_field(name: str, dtype: str) -> FieldSpec:
    return FieldSpec(name=name, label=name, type=dtype, dtype=dtype)


# ---------- infinity checks ---------------------------------------------------


def test_infinity_detected_in_float_column():
    df = pd.DataFrame({"price": [1.0, float("inf"), 3.0]})
    contract = _make_contract(_make_field("price", "float64"))
    result = _qa_checks(df, contract)
    assert "price" in result["infinity_columns"]


def test_negative_infinity_detected():
    df = pd.DataFrame({"score": [1.0, float("-inf"), 3.0]})
    contract = _make_contract(_make_field("score", "float64"))
    result = _qa_checks(df, contract)
    assert "score" in result["infinity_columns"]


def test_no_infinity_clean_column():
    df = pd.DataFrame({"price": [1.0, 2.5, 3.7]})
    contract = _make_contract(_make_field("price", "float64"))
    result = _qa_checks(df, contract)
    assert "price" not in result["infinity_columns"]


def test_infinity_result_key_always_present():
    df = pd.DataFrame({"x": [1, 2, 3]})
    contract = _make_contract(_make_field("x", "Int64"))
    result = _qa_checks(df, contract)
    assert "infinity_columns" in result


# ---------- suspicious rounding checks ----------------------------------------


def test_suspicious_rounding_detected_when_all_round():
    """100% round values (>90% threshold) in a float column → flagged."""
    df = pd.DataFrame({"price": [float(i) for i in range(1, 11)]})
    contract = _make_contract(_make_field("price", "float64"))
    result = _qa_checks(df, contract)
    assert "price" in result["suspicious_rounding_columns"]


def test_suspicious_rounding_not_triggered_when_mixed():
    """<90% round numbers → not flagged."""
    df = pd.DataFrame({"price": [1.0, 2.5, 3.7, 4.0, 5.1]})
    contract = _make_contract(_make_field("price", "float64"))
    result = _qa_checks(df, contract)
    assert "price" not in result["suspicious_rounding_columns"]


def test_suspicious_rounding_skips_integer_columns():
    """Integer columns (not float) are not subject to the rounding check."""
    df = pd.DataFrame({"count": list(range(1, 11))})
    contract = _make_contract(_make_field("count", "Int64"))
    result = _qa_checks(df, contract)
    assert "count" not in result["suspicious_rounding_columns"]


def test_suspicious_rounding_ignores_nulls_in_ratio():
    """Null values are excluded from the 90% calculation."""
    # 5 round values, 4 non-round, 1 null → 5/9 ≈ 55.6% — should NOT flag
    df = pd.DataFrame({"price": [1.0, 2.0, 3.0, 4.0, 5.0, 1.1, 2.2, 3.3, 4.4, None]})
    contract = _make_contract(_make_field("price", "float64"))
    result = _qa_checks(df, contract)
    assert "price" not in result["suspicious_rounding_columns"]


# ---------- future dates checks -----------------------------------------------


def test_future_dates_detected():
    """A datetime column with a value >1 day in the future is flagged."""
    future = datetime.now() + timedelta(days=5)
    df = pd.DataFrame({"event_date": pd.to_datetime([datetime.now(), future])})
    contract = _make_contract(_make_field("event_date", "datetime64[ns]"))
    result = _qa_checks(df, contract)
    assert "event_date" in result["future_date_columns"]


def test_future_dates_not_triggered_within_grace_period():
    """Dates within 1-day grace period are not flagged."""
    near = datetime.now() + timedelta(hours=12)
    df = pd.DataFrame({"event_date": pd.to_datetime([datetime.now(), near])})
    contract = _make_contract(_make_field("event_date", "datetime64[ns]"))
    result = _qa_checks(df, contract)
    assert "event_date" not in result["future_date_columns"]


def test_future_dates_skips_non_datetime_columns():
    """Non-datetime columns are not checked for future dates."""
    df = pd.DataFrame({"name": ["Alice", "Bob"]})
    contract = _make_contract(_make_field("name", "string"))
    result = _qa_checks(df, contract)
    assert result["future_date_columns"] == []


def test_future_dates_ignores_null_values():
    """Null values in datetime columns should not cause errors."""
    future = datetime.now() + timedelta(days=5)
    df = pd.DataFrame({"event_date": pd.to_datetime([None, future])})
    contract = _make_contract(_make_field("event_date", "datetime64[ns]"))
    result = _qa_checks(df, contract)
    assert "event_date" in result["future_date_columns"]


# ---------- column name hygiene checks ----------------------------------------


def test_column_name_leading_whitespace_flagged():
    df = pd.DataFrame({" name": ["Alice"]})
    contract = _make_contract(_make_field(" name", "string"))
    result = _qa_checks(df, contract)
    assert " name" in result["bad_column_names"]


def test_column_name_trailing_whitespace_flagged():
    df = pd.DataFrame({"name ": ["Alice"]})
    contract = _make_contract(_make_field("name ", "string"))
    result = _qa_checks(df, contract)
    assert "name " in result["bad_column_names"]


def test_column_name_double_space_flagged():
    df = pd.DataFrame({"first  name": ["Alice"]})
    contract = _make_contract(_make_field("first  name", "string"))
    result = _qa_checks(df, contract)
    assert "first  name" in result["bad_column_names"]


def test_column_name_non_ascii_flagged():
    df = pd.DataFrame({"naïve": ["Alice"]})
    contract = _make_contract(_make_field("naïve", "string"))
    result = _qa_checks(df, contract)
    assert "naïve" in result["bad_column_names"]


def test_clean_column_names_not_flagged():
    df = pd.DataFrame({"first_name": ["Alice"], "age": [30]})
    contract = _make_contract(
        _make_field("first_name", "string"),
        _make_field("age", "Int64"),
    )
    result = _qa_checks(df, contract)
    assert result["bad_column_names"] == []


# ---------- result structure --------------------------------------------------


def test_qa_checks_returns_all_four_keys():
    df = pd.DataFrame({"x": [1.0]})
    contract = _make_contract(_make_field("x", "float64"))
    result = _qa_checks(df, contract)
    assert set(result.keys()) == {
        "infinity_columns",
        "suspicious_rounding_columns",
        "future_date_columns",
        "bad_column_names",
    }
