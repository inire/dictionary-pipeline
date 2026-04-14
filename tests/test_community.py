"""Tests for the community sharing module."""

from __future__ import annotations

from dictionary_pipeline.community import (
    SafetyReport,
    dump_contract_yaml,
    render_community_markdown,
    sanitize_contract,
    scan_contract,
    scan_profile,
)
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


def test_sanitize_drops_non_shareable_fields():
    fields = [
        FieldSpec(name="keep", label="Keep", type="text", dtype="string"),
        FieldSpec(name="drop", label="Drop", type="text", dtype="string", shareable=False),
    ]
    sanitized = sanitize_contract(_mk_contract(fields))
    assert len(sanitized.fields) == 1
    assert sanitized.fields[0].name == "keep"


def test_sanitize_uses_community_notes_when_set():
    fields = [
        FieldSpec(
            name="foo", label="Foo", type="text", dtype="string",
            notes="Real notes with jane@example.com",
            community_notes="Generic description",
        ),
    ]
    sanitized = sanitize_contract(_mk_contract(fields))
    assert sanitized.fields[0].notes == "Generic description"
    assert sanitized.fields[0].community_notes == ""


def test_sanitize_strips_pii_from_notes_when_no_community_notes():
    fields = [
        FieldSpec(
            name="foo", label="Foo", type="text", dtype="string",
            notes="Contact jane@example.com for details. Card ending 4122 was used.",
        ),
    ]
    sanitized = sanitize_contract(_mk_contract(fields))
    out = sanitized.fields[0].notes
    assert "jane@example.com" not in out
    assert "4122" not in out
    assert "[REDACTED_EMAIL]" in out
    assert "[REDACTED_PARTIAL_CARD]" in out


def test_sanitize_preserves_clean_notes_verbatim():
    fields = [
        FieldSpec(name="foo", label="Foo", type="text", dtype="string",
                  notes="Transaction amount in USD, always positive."),
    ]
    sanitized = sanitize_contract(_mk_contract(fields))
    assert sanitized.fields[0].notes == "Transaction amount in USD, always positive."


def test_sanitize_scrubs_allowed_values_pii():
    fields = [
        FieldSpec(name="payment", label="Payment", type="categorical", dtype="string",
                  allowed_values=["Visa ending 4122", "Mastercard ending 3854"]),
    ]
    sanitized = sanitize_contract(_mk_contract(fields))
    # Partial-card values should be replaced with a summary count
    assert sanitized.fields[0].allowed_values is None
    assert "2 unique" in (sanitized.fields[0].notes or "")


def test_dump_contract_yaml_roundtrip(tmp_path):
    fields = [
        FieldSpec(name="amount", label="Amount", type="decimal", dtype="float64",
                  nullable=False, notes="USD transaction amount"),
    ]
    contract = _mk_contract(fields)
    contract.community_version = "1.0.0"

    yaml_text = dump_contract_yaml(contract)
    assert "dataset:" in yaml_text
    assert "name: test" in yaml_text
    assert "community_version: 1.0.0" in yaml_text
    assert "amount" in yaml_text
    assert "USD transaction amount" in yaml_text


def test_dump_contract_yaml_excludes_empty_fields():
    fields = [FieldSpec(name="foo", label="Foo", type="text", dtype="string")]
    contract = _mk_contract(fields)
    yaml_text = dump_contract_yaml(contract)
    # community_notes defaults to "" and should not appear
    assert "community_notes" not in yaml_text
    # shareable defaults to True, but community exports drop the flag
    assert "shareable" not in yaml_text


def test_render_markdown_includes_dataset_heading():
    fields = [
        FieldSpec(name="amount", label="Amount", type="decimal", dtype="float64",
                  notes="USD amount"),
    ]
    contract = _mk_contract(fields)
    md = render_community_markdown(contract)
    assert "# test" in md
    assert "## Fields" in md
    assert "amount" in md
    assert "USD amount" in md


def test_render_markdown_includes_grain_and_source():
    contract = _mk_contract([])
    contract.grain = "one row per purchase"
    contract.source = "Bank CSV export"
    md = render_community_markdown(contract)
    assert "one row per purchase" in md
    assert "Bank CSV export" in md


def test_render_markdown_shows_community_version_when_set():
    contract = _mk_contract([])
    contract.community_version = "1.2.0"
    md = render_community_markdown(contract)
    assert "1.2.0" in md


def test_render_markdown_omits_derived_section_when_empty():
    contract = _mk_contract([])
    md = render_community_markdown(contract)
    assert "## Derived fields" not in md
