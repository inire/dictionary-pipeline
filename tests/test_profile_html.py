"""Tests for the optional ydata-profiling HTML report in stage 1."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import json
import pandas as pd
import pytest

from dictionary_pipeline.stages.s1_profile import run


# ydata-profiling is optional; the JSON-only path must work whether or not
# the extra is installed, so most tests here run in both states.
try:
    import ydata_profiling  # noqa: F401

    _HAS_YDATA = True
except ImportError:
    _HAS_YDATA = False

requires_ydata = pytest.mark.skipif(
    not _HAS_YDATA,
    reason='ydata-profiling not installed; install with pip install -e ".[profiling]"',
)


@pytest.fixture
def small_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": [1, 2, 3, 4],
            "name": ["alice", "bob", "carol", "dan"],
            "score": [10.5, 20.0, 30.5, 40.0],
        }
    )


def test_json_summary_always_written(small_df, tmp_path: Path):
    """profile_summary.json must be produced regardless of ydata availability."""
    run(small_df, workdir=tmp_path)
    summary_path = tmp_path / "profile_summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text())
    assert summary["row_count"] == 4
    assert set(summary["columns"]) == {"id", "name", "score"}


def test_log_records_html_metadata(small_df, tmp_path: Path):
    """The transformation log must record what happened with the HTML report.

    Either the path to the produced report, or a 'skipped' reason. This is
    how the change log communicates whether the user got the rich output.
    """
    from dictionary_pipeline.logging import TransformationLog

    log = TransformationLog(tmp_path / "log.jsonl")
    run(small_df, workdir=tmp_path, log=log)

    events = log.read_all()
    profile_events = [e for e in events if e["event"] == "profile_generated"]
    assert len(profile_events) == 1
    details = profile_events[0]["details"]
    # Either html_report was set OR a reason was given for skipping
    assert "html_report" in details
    assert "skipped" in details


@requires_ydata
def test_html_report_written_when_ydata_available(small_df, tmp_path: Path):
    """When [profiling] is installed, profile_report.html must be produced."""
    run(small_df, workdir=tmp_path)
    html_path = tmp_path / "profile_report.html"
    assert html_path.exists()
    # Should be a real HTML doc, not just a stub
    content = html_path.read_text()
    assert "<html" in content.lower()
    assert len(content) > 1000  # real reports are tens of KB minimum


def test_html_report_skipped_when_ydata_unavailable(small_df, tmp_path: Path):
    """When ydata-profiling is missing, no HTML report is written and
    the log records why."""
    from dictionary_pipeline.logging import TransformationLog

    log = TransformationLog(tmp_path / "log.jsonl")
    with patch("dictionary_pipeline.stages.s1_profile._YDATA_AVAILABLE", False):
        run(small_df, workdir=tmp_path, log=log)

    assert not (tmp_path / "profile_report.html").exists()

    events = log.read_all()
    details = next(e for e in events if e["event"] == "profile_generated")["details"]
    assert details["html_report"] is None
    assert "ydata-profiling not installed" in (details.get("skipped") or "")


def test_html_report_failure_does_not_break_json(small_df, tmp_path: Path):
    """If ydata raises, the JSON summary must still be written.

    Regression guard: the HTML report is a convenience and must never
    block the deterministic JSON output that downstream stages depend on.
    """
    from dictionary_pipeline.logging import TransformationLog

    log = TransformationLog(tmp_path / "log.jsonl")

    # Force the HTML path to raise by pointing _YDATA_AVAILABLE at True
    # but making ProfileReport blow up. We patch the import inside the
    # function rather than the constant, since the constant is checked
    # first.
    with patch("dictionary_pipeline.stages.s1_profile._YDATA_AVAILABLE", True), \
         patch(
             "ydata_profiling.ProfileReport",
             side_effect=RuntimeError("simulated failure"),
         ) if _HAS_YDATA else patch(
             "dictionary_pipeline.stages.s1_profile._YDATA_AVAILABLE", False
         ):
        run(small_df, workdir=tmp_path, log=log)

    # JSON must exist regardless
    assert (tmp_path / "profile_summary.json").exists()

    # Log must reflect the skip / failure reason
    events = log.read_all()
    details = next(e for e in events if e["event"] == "profile_generated")["details"]
    assert details["html_report"] is None
    assert details.get("skipped") is not None
