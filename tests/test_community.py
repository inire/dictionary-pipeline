"""Tests for the community sharing module."""

from __future__ import annotations

from dictionary_pipeline.community import SafetyReport, scan_contract, scan_profile
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


def test_scan_contract_finds_embedded_email_in_allowed_values():
    """Allowed_values that embed PII inside longer text should be caught by find_pii."""
    fields = [
        FieldSpec(name="src", label="Src", type="categorical", dtype="string",
                  allowed_values=["contact jane@example.com"]),
    ]
    report = scan_contract(_mk_contract(fields))
    assert any(f.pii_type == "email" for f in report.findings)


def test_safety_report_summary_when_safe():
    assert SafetyReport().summary() == "Safe (no PII detected)"


def test_safety_report_summary_aggregates_by_type():
    r = SafetyReport()
    r.add("field.a.notes", "email", "x@y.com")
    r.add("field.b.notes", "email", "z@w.com")
    r.add("field.c.notes", "phone", "555-123-4567")
    s = r.summary()
    assert "email:2" in s
    assert "phone:1" in s
    assert s.startswith("Unsafe")


def test_scan_contract_finds_pii_in_community_notes():
    """PII in the community_notes override field should also be detected."""
    fields = [
        FieldSpec(name="contact", label="Contact", type="text", dtype="string",
                  notes="Customer contact field.",
                  community_notes="See jane@example.com for questions."),
    ]
    report = scan_contract(_mk_contract(fields))
    assert report.is_safe is False
    assert any(
        f.pii_type == "email" and f.location == "field.contact.community_notes"
        for f in report.findings
    )


def test_scan_profile_clean_profile_is_safe():
    profile = {
        "row_count": 100,
        "column_count": 2,
        "columns": {
            "amount": {
                "dtype": "float64",
                "top_values": {"10.00": 30, "25.00": 20},
            },
            "category": {
                "dtype": "object",
                "top_values": {"Food": 40, "Transport": 15},
            },
        },
    }
    report = scan_profile(profile)
    assert report.is_safe is True


def test_scan_profile_detects_email_in_top_values():
    profile = {
        "columns": {
            "contact": {
                "top_values": {"jane@example.com": 5, "john@example.com": 3},
            },
        },
    }
    report = scan_profile(profile)
    assert report.is_safe is False
    assert all(f.pii_type == "email" for f in report.findings)
    assert len(report.findings) == 2


def test_scan_profile_handles_missing_columns_key():
    assert scan_profile({}).is_safe is True
