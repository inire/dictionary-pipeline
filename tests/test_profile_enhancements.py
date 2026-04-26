"""Tests for Stage 1 profile enhancements: outliers, duplicates, freshness."""

from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import pytest

from dictionary_pipeline.stages.s1_profile import (
    _detect_outliers_iqr,
    _detect_outliers_zscore,
    _duplicate_summary,
    _freshness_summary,
    _outlier_summary,
    profile,
)


# ---- outlier detection ----


class TestOutlierDetection:
    def test_iqr_flags_extreme_values(self):
        s = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 100])
        mask = _detect_outliers_iqr(s)
        assert mask.iloc[-1]  # 100 should be flagged

    def test_iqr_clean_data_no_flags(self):
        s = pd.Series(range(100))
        mask = _detect_outliers_iqr(s)
        assert mask.sum() == 0

    def test_zscore_flags_extreme_values(self):
        rng = np.random.default_rng(42)
        s = pd.Series(np.concatenate([rng.normal(50, 5, 100), [200]]))
        mask = _detect_outliers_zscore(s)
        assert mask.iloc[-1]  # 200 should be flagged

    def test_zscore_constant_series_no_flags(self):
        s = pd.Series([5] * 20)
        mask = _detect_outliers_zscore(s)
        assert mask.sum() == 0

    def test_outlier_summary_too_few_values(self):
        s = pd.Series([1, 2, 3])
        result = _outlier_summary(s)
        assert result.get("skipped") is True

    def test_outlier_summary_reports_counts(self):
        rng = np.random.default_rng(42)
        s = pd.Series(np.concatenate([rng.normal(50, 5, 100), [500, -500]]))
        result = _outlier_summary(s)
        assert result["outlier_count"] >= 2
        assert "outlier_pct" in result
        assert "iqr_outliers" in result
        assert "zscore_outliers" in result


# ---- duplicate detection ----


class TestDuplicateDetection:
    def test_no_duplicates(self):
        df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        result = _duplicate_summary(df)
        assert result["full_row_duplicate_count"] == 0
        assert result["full_row_duplicate_pct"] == 0.0

    def test_with_duplicates(self):
        df = pd.DataFrame({"a": [1, 1, 2], "b": ["x", "x", "y"]})
        result = _duplicate_summary(df)
        assert result["full_row_duplicate_count"] == 1
        assert result["full_row_duplicate_pct"] > 0

    def test_empty_dataframe(self):
        df = pd.DataFrame({"a": []})
        result = _duplicate_summary(df)
        assert result["full_row_duplicate_count"] == 0


# ---- freshness ----


class TestFreshness:
    def test_fresh_data(self):
        now = datetime.now(timezone.utc)
        s = pd.Series([now - timedelta(hours=1), now - timedelta(hours=2)])
        result = _freshness_summary(s)
        assert result is not None
        assert result["lag_hours"] < 2

    def test_stale_data(self):
        old = datetime.now(timezone.utc) - timedelta(days=30)
        s = pd.Series([old, old - timedelta(days=1)])
        result = _freshness_summary(s)
        assert result is not None
        assert result["lag_hours"] > 700  # ~30 days

    def test_no_valid_timestamps(self):
        s = pd.Series(["not-a-date", "also-not-a-date"])
        result = _freshness_summary(s)
        assert result is None


# ---- profile integration ----


class TestProfileIntegration:
    def test_profile_has_duplicates_key(self):
        df = pd.DataFrame({"a": [1, 1, 2], "b": [3, 3, 4]})
        result = profile(df)
        assert "duplicates" in result
        assert result["duplicates"]["full_row_duplicate_count"] == 1

    def test_profile_numeric_has_outliers(self):
        rng = np.random.default_rng(42)
        df = pd.DataFrame({
            "value": np.concatenate([rng.normal(50, 5, 100), [500]]),
        })
        result = profile(df)
        col = result["columns"]["value"]
        assert "outliers" in col
        assert col["outliers"]["outlier_count"] >= 1

    def test_profile_datetime_has_freshness(self):
        now = datetime.now(timezone.utc)
        df = pd.DataFrame({
            "ts": pd.to_datetime([now - timedelta(hours=h) for h in range(10)]),
        })
        result = profile(df)
        col = result["columns"]["ts"]
        assert "freshness" in col
        assert col["freshness"]["lag_hours"] < 1

    def test_profile_infinity_flagged(self):
        df = pd.DataFrame({"v": [1.0, 2.0, float("inf"), 4.0]})
        result = profile(df)
        assert result["columns"]["v"].get("infinity_count") == 1

    def test_profile_suspicious_rounding(self):
        # 96 whole numbers + 4 decimals in a float column
        vals = [float(i) for i in range(96)] + [0.1, 0.2, 0.3, 0.4]
        df = pd.DataFrame({"v": vals})
        result = profile(df)
        assert result["columns"]["v"].get("suspicious_rounding") is True

    def test_profile_future_dates_flagged(self):
        now = datetime.now(timezone.utc)
        future = now + timedelta(days=30)
        df = pd.DataFrame({
            "ts": pd.to_datetime([now - timedelta(days=1), future]),
        })
        result = profile(df)
        col = result["columns"]["ts"]
        assert col.get("future_date_count", 0) >= 1
