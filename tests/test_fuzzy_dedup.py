"""Tests for fuzzy near-duplicate detection in Stage 5 (s5_clean)."""

from __future__ import annotations

import sys
import types
from unittest.mock import patch

import pandas as pd
import pytest

from dictionary_pipeline.contract import Contract, FieldSpec
from dictionary_pipeline.stages.s5_clean import _fuzzy_near_dupes, run
from dictionary_pipeline.logging import TransformationLog


def _make_contract(*field_names_and_types: tuple[str, str]) -> Contract:
    """Build a minimal Contract with the given (name, type) field pairs."""
    fields = [
        FieldSpec(
            name=name,
            label=name,
            type=ftype,
            dtype="string",
            nullable=True,
        )
        for name, ftype in field_names_and_types
    ]
    return Contract(
        dataset_name="test",
        description="",
        source="",
        grain="row",
        pii=False,
        pii_fields=[],
        naming_convention="snake_case",
        last_updated="2026-01-01",
        fields=fields,
    )


# ---------------------------------------------------------------------------
# Core detection tests
# ---------------------------------------------------------------------------

def test_similar_rows_detected():
    """Two rows that are ~90% similar must be flagged."""
    df = pd.DataFrame({
        "name": ["John Smith", "John Smyth"],
        "city": ["London", "London"],
    })
    contract = _make_contract(("name", "text"), ("city", "categorical"))

    report = _fuzzy_near_dupes(df, contract, threshold=85.0)

    assert len(report["near_duplicate_pairs"]) == 1
    pair = report["near_duplicate_pairs"][0]
    assert pair["similarity"] >= 85.0
    assert pair["row_a"] == 0
    assert pair["row_b"] == 1
    # Only "name" differs → key_diffs should mention name
    assert "name" in pair["key_diffs"]
    assert "city" not in pair["key_diffs"]


def test_different_rows_not_flagged():
    """Two completely different rows must not be flagged."""
    df = pd.DataFrame({
        "name": ["Alice Wonderland", "Bob the Builder"],
        "city": ["Paris", "Tokyo"],
    })
    contract = _make_contract(("name", "text"), ("city", "categorical"))

    report = _fuzzy_near_dupes(df, contract, threshold=85.0)

    assert report["near_duplicate_pairs"] == []


def test_threshold_is_respected():
    """Results just below the threshold are not included."""
    df = pd.DataFrame({
        "name": ["John Smith", "John Smyth"],
        "city": ["London", "London"],
    })
    contract = _make_contract(("name", "text"), ("city", "categorical"))

    # At 99% threshold the pair should NOT be detected
    report = _fuzzy_near_dupes(df, contract, threshold=99.0)
    assert report["near_duplicate_pairs"] == []

    # At 80% it should be detected
    report = _fuzzy_near_dupes(df, contract, threshold=80.0)
    assert len(report["near_duplicate_pairs"]) == 1


def test_exact_dupes_skipped_fuzzy_catches_near_match():
    """After exact dedup, fuzzy still catches near-duplicates that survived."""
    # Row 0 and 1 are exact → removed by exact dedup inside run()
    # Row 2 is a near-dupe of what remains
    df = pd.DataFrame({
        "name": ["Alice", "Alice", "Alce"],
        "city": ["NYC", "NYC", "NYC"],
    })
    contract = _make_contract(("name", "text"), ("city", "categorical"))

    # After exact dedup: ["Alice", "Alce"] remain
    result_df = run(df, contract)

    assert len(result_df) == 2  # exact dupe removed

    # Direct call on the deduplicated data
    report = _fuzzy_near_dupes(result_df, contract, threshold=80.0)
    assert len(report["near_duplicate_pairs"]) == 1
    assert report["near_duplicate_pairs"][0]["similarity"] >= 80.0


def test_report_structure():
    """Report dict always contains 'near_duplicate_pairs' and 'threshold'."""
    df = pd.DataFrame({"label": ["a", "b"]})
    contract = _make_contract(("label", "text"))

    report = _fuzzy_near_dupes(df, contract)

    assert "near_duplicate_pairs" in report
    assert "threshold" in report
    assert report["threshold"] == 85.0  # default


def test_no_text_columns_returns_empty():
    """If no text/categorical/identifier columns exist, return empty pairs."""
    df = pd.DataFrame({"count": [1, 2]})
    contract = _make_contract(("count", "integer"))

    report = _fuzzy_near_dupes(df, contract)

    assert report["near_duplicate_pairs"] == []


# ---------------------------------------------------------------------------
# Logging integration
# ---------------------------------------------------------------------------

def test_run_logs_near_duplicate_event(tmp_path):
    """run() must log 'near_duplicates_detected' to TransformationLog."""
    df = pd.DataFrame({
        "name": ["John Smith", "John Smyth"],
        "city": ["London", "London"],
    })
    contract = _make_contract(("name", "text"), ("city", "categorical"))
    log = TransformationLog(tmp_path / "log.jsonl")

    run(df, contract, log=log)

    events = log.read_all()
    event_names = [e["event"] for e in events]
    assert "near_duplicates_detected" in event_names

    nd_event = next(e for e in events if e["event"] == "near_duplicates_detected")
    assert nd_event["stage"] == "s5_clean"
    assert nd_event["rows_affected"] >= 1
    assert "near_duplicate_pairs" in nd_event["details"]


def test_run_returns_dataframe():
    """run() must still return a plain DataFrame (not a dict)."""
    df = pd.DataFrame({"name": ["Alice", "Alice", "Bob"]})
    contract = _make_contract(("name", "text"))

    result = run(df, contract)

    assert isinstance(result, pd.DataFrame)


# ---------------------------------------------------------------------------
# Graceful degradation when rapidfuzz is missing
# ---------------------------------------------------------------------------

def test_missing_rapidfuzz_graceful_skip():
    """When rapidfuzz is not installed, _fuzzy_near_dupes returns empty pairs."""
    df = pd.DataFrame({
        "name": ["John Smith", "John Smyth"],
    })
    contract = _make_contract(("name", "text"))

    with patch("dictionary_pipeline.stages.s5_clean._RAPIDFUZZ_AVAILABLE", False):
        report = _fuzzy_near_dupes(df, contract)

    assert report["near_duplicate_pairs"] == []
    assert "skipped" in report


def test_missing_rapidfuzz_run_does_not_crash(tmp_path):
    """run() must not raise even when rapidfuzz is unavailable."""
    df = pd.DataFrame({"term": ["hello", "helo"]})
    contract = _make_contract(("term", "text"))
    log = TransformationLog(tmp_path / "log.jsonl")

    with patch("dictionary_pipeline.stages.s5_clean._RAPIDFUZZ_AVAILABLE", False):
        result = run(df, contract, log=log)

    assert isinstance(result, pd.DataFrame)

    events = log.read_all()
    nd_event = next(e for e in events if e["event"] == "near_duplicates_detected")
    assert nd_event["rows_affected"] == 0
    assert "skipped" in nd_event["details"]
