"""Tests for the community sharing module."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from dictionary_pipeline.community import SafetyReport, scan_contract
from dictionary_pipeline.contract import Contract, FieldSpec


def _mk_contract(fields: list[FieldSpec]) -> Contract:
    return Contract(
        dataset_name="test",
        description="test",
        source="test",
        grain="one row per thing",
        pii=False,
        pii_fields=[],
        naming_convention="snake_case",
        last_updated="2026-04-14",
        fields=fields,
    )


def test_safety_report_empty_has_no_findings():
    report = SafetyReport()
    assert report.is_safe is True
    assert report.findings == []


def test_safety_report_with_finding_is_unsafe():
    report = SafetyReport()
    report.add("field.notes", "email", "jane@example.com")
    assert report.is_safe is False
    assert len(report.findings) == 1
    assert report.findings[0].location == "field.notes"
    assert report.findings[0].pii_type == "email"


def test_scan_contract_clean_contract_returns_safe_report():
    fields = [
        FieldSpec(name="amount", label="Amount", type="decimal", dtype="float64",
                  notes="Transaction amount in USD."),
    ]
    report = scan_contract(_mk_contract(fields))
    assert report.is_safe is True


def test_scan_contract_finds_email_in_notes():
    fields = [
        FieldSpec(name="contact", label="Contact", type="text", dtype="string",
                  notes="Send questions to jane@example.com for help."),
    ]
    report = scan_contract(_mk_contract(fields))
    assert report.is_safe is False
    assert any(f.pii_type == "email" for f in report.findings)


def test_scan_contract_finds_partial_card_in_allowed_values():
    fields = [
        FieldSpec(name="card", label="Card", type="categorical", dtype="string",
                  allowed_values=["Visa ending 4122", "Mastercard ending 3854"]),
    ]
    report = scan_contract(_mk_contract(fields))
    assert report.is_safe is False
    assert any(f.pii_type == "partial_card" for f in report.findings)


def test_scan_contract_skips_non_shareable_fields():
    fields = [
        FieldSpec(name="secret", label="Secret", type="text", dtype="string",
                  notes="Contact jane@example.com",
                  shareable=False),
    ]
    report = scan_contract(_mk_contract(fields))
    # Non-shareable fields are dropped, not scanned
    assert report.is_safe is True
