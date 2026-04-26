"""Tests for the freshness check in Stage 1 profile."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from dictionary_pipeline.stages.s1_profile import _freshness_check, profile


def _utc(days_ago: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


def test_recent_datetime_not_stale():
    df = pd.DataFrame({"ts": pd.to_datetime([_utc(1), _utc(5), _utc(10)], utc=True)})
    result = _freshness_check(df)
    assert result != {}
    col = result["by_column"]["ts"]
    assert col["is_stale"] is False
    assert col["staleness_days"] < 90


def test_old_datetime_is_stale():
    df = pd.DataFrame({"ts": pd.to_datetime([_utc(120), _utc(200), _utc(150)], utc=True)})
    result = _freshness_check(df)
    col = result["by_column"]["ts"]
    assert col["is_stale"] is True
    assert col["staleness_days"] > 90


def test_no_datetime_columns_returns_empty():
    df = pd.DataFrame({"name": ["alice", "bob"], "age": [30, 25]})
    result = _freshness_check(df)
    assert result == {}


def test_staleness_calculation_correctness():
    # newest value is exactly 100 days ago → staleness_days ≈ 100
    newest = _utc(100)
    oldest = _utc(200)
    df = pd.DataFrame({"ts": pd.to_datetime([newest, oldest], utc=True)})
    result = _freshness_check(df)
    col = result["by_column"]["ts"]
    assert abs(col["staleness_days"] - 100) < 0.1
    assert abs(col["span_days"] - 100) < 0.1
    assert col["is_stale"] is True  # 100 > 90


def test_profile_merges_freshness_into_summary():
    df = pd.DataFrame({"ts": pd.to_datetime([_utc(10), _utc(20)], utc=True)})
    summary = profile(df)
    assert "freshness" in summary
    assert "by_column" in summary["freshness"]
    assert "freshness" in summary["columns"]["ts"]


def test_profile_no_datetime_freshness_is_empty():
    df = pd.DataFrame({"val": [1, 2, 3]})
    summary = profile(df)
    assert summary["freshness"] == {}


def test_custom_threshold():
    # 30 days ago, threshold=20 → stale
    df = pd.DataFrame({"ts": pd.to_datetime([_utc(30)], utc=True)})
    result = _freshness_check(df, stale_threshold_days=20)
    assert result["by_column"]["ts"]["is_stale"] is True

    # same data, threshold=60 → not stale
    result2 = _freshness_check(df, stale_threshold_days=60)
    assert result2["by_column"]["ts"]["is_stale"] is False
