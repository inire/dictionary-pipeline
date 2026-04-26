"""Tests for the assumptions tracker."""

import json
import tempfile
from pathlib import Path

import pytest

from dictionary_pipeline.assumptions import Assumption, AssumptionLog


class TestAssumption:
    def test_risk_score_low_conf_high_impact(self):
        a = Assumption(
            id=1, stage="s6", category="normalization",
            assumption="test", rationale="test",
            confidence="low", impact_if_wrong="high",
        )
        assert a.risk_score == 8
        assert a.is_critical is True

    def test_risk_score_high_conf_low_impact(self):
        a = Assumption(
            id=1, stage="s6", category="normalization",
            assumption="test", rationale="test",
            confidence="high", impact_if_wrong="medium",
        )
        assert a.risk_score == 3
        assert a.is_critical is False

    def test_validated_not_critical(self):
        a = Assumption(
            id=1, stage="s6", category="normalization",
            assumption="test", rationale="test",
            confidence="low", impact_if_wrong="critical",
            validated=True, validation_result="confirmed",
        )
        assert a.is_critical is False


class TestAssumptionLog:
    def test_add_and_query(self):
        log = AssumptionLog(pipeline_run="test-run")
        log.add("s6", "normalization", "A -> B", "similar text", "medium", "low")
        log.add("s6", "normalization", "C -> D", "same thing", "low", "high")

        assert len(log.assumptions) == 2
        assert len(log.critical) == 1
        assert log.critical[0].assumption == "C -> D"

    def test_validate(self):
        log = AssumptionLog()
        log.add("s6", "normalization", "A -> B", "reason", "low", "high")
        assert len(log.critical) == 1

        log.validate(1, "confirmed", "checked with domain expert")
        assert len(log.critical) == 0
        assert log.assumptions[0].validated is True

    def test_validate_nonexistent_raises(self):
        log = AssumptionLog()
        with pytest.raises(ValueError):
            log.validate(99, "confirmed")

    def test_save_and_load(self):
        log = AssumptionLog(pipeline_run="round-trip")
        log.add("s6", "normalization", "X -> Y", "reason", "low", "critical")
        log.add("s3", "data", "grain is per-order", "profile says so", "high", "medium")

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = Path(f.name)

        log.save(path)
        loaded = AssumptionLog.load(path)

        assert loaded.pipeline_run == "round-trip"
        assert len(loaded.assumptions) == 2
        assert loaded.assumptions[0].assumption == "X -> Y"
        assert loaded.critical[0].stage == "s6"
        path.unlink()

    def test_to_dict_has_computed_fields(self):
        log = AssumptionLog()
        log.add("s6", "normalization", "A -> B", "reason", "low", "high")
        d = log.to_dict()

        assert d["total_assumptions"] == 1
        assert d["critical_count"] == 1
        assert d["assumptions"][0]["risk_score"] == 8
        assert d["assumptions"][0]["is_critical"] is True

    def test_report_output(self):
        log = AssumptionLog(pipeline_run="test")
        log.add("s6", "normalization", "Kid's Menu -> Kids Menu",
                "syntactic variant", "medium", "low")
        log.add("s6", "normalization", "Beverages -> Drinks",
                "LLM judgment", "low", "high",
                validation_plan="confirm with data owner")

        report = log.report()
        assert "CRITICAL ASSUMPTIONS" in report
        assert "Beverages -> Drinks" in report
        assert "confirm with data owner" in report
