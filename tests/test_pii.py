"""Tests for PII detection and redaction."""

import pytest

from dictionary_pipeline.pii import classify_pii


def test_detects_email():
    assert classify_pii("alice@example.com") == "email"


def test_detects_ssn():
    assert classify_pii("123-45-6789") == "ssn"


def test_detects_phone():
    assert classify_pii("+1 (555) 123-4567") == "phone"
    assert classify_pii("555-123-4567") == "phone"


def test_detects_credit_card():
    assert classify_pii("4111 1111 1111 1111") == "credit_card"
    assert classify_pii("4111111111111111") == "credit_card"


def test_detects_partial_card():
    assert classify_pii("Visa ending in 4122") == "partial_card"


def test_detects_partial_account():
    assert classify_pii("...965") == "partial_account"
    assert classify_pii("***218") == "partial_account"


def test_clean_values_return_none():
    assert classify_pii("hello world") is None
    assert classify_pii("42.99") is None
    assert classify_pii("2026-03-28") is None
    assert classify_pii("Merchandise") is None


from dictionary_pipeline.pii import redact_profile


def test_redact_profile_scrubs_top_values():
    profile = {
        "row_count": 10,
        "column_count": 2,
        "columns": {
            "email": {
                "dtype": "object",
                "null_count": 0,
                "distinct_count": 5,
                "top_values": {
                    "alice@example.com": 3,
                    "bob@test.org": 2,
                    "carol@foo.net": 2,
                },
            },
            "amount": {
                "dtype": "float64",
                "null_count": 0,
                "distinct_count": 8,
                "top_values": {
                    "42.99": 3,
                    "19.95": 2,
                },
            },
        },
    }

    scrubbed = redact_profile(profile)

    # Email top_values should be redacted
    email_top = scrubbed["columns"]["email"]["top_values"]
    assert "alice@example.com" not in email_top
    assert all("[REDACTED" in k for k in email_top)

    # Amount top_values should be untouched
    amount_top = scrubbed["columns"]["amount"]["top_values"]
    assert "42.99" in amount_top


def test_redact_profile_preserves_structure():
    # NOTE: Replace these placeholder names with real examples from your dataset
    # when running against actual data. These generic names validate that the
    # _is_person_name() heuristic catches "Firstname Lastname" patterns.
    profile = {
        "row_count": 5,
        "column_count": 1,
        "columns": {
            "name": {
                "dtype": "object",
                "distinct_count": 2,
                "top_values": {"Jane Doe": 3, "John Smith": 2},
            },
        },
    }
    scrubbed = redact_profile(profile)
    assert scrubbed["row_count"] == 5
    assert "name" in scrubbed["columns"]
    assert scrubbed["columns"]["name"]["distinct_count"] == 2
    # Names should be redacted
    name_top = scrubbed["columns"]["name"]["top_values"]
    assert "Jane Doe" not in name_top
    assert "John Smith" not in name_top


from dictionary_pipeline.pii import find_pii


def test_find_pii_in_free_text():
    text = "Contact customer at jane@example.com or 555-123-4567 for questions."
    findings = find_pii(text)
    types = [t for t, _ in findings]
    assert "email" in types
    assert "phone" in types


def test_find_pii_returns_empty_for_clean_text():
    assert find_pii("This is a normal sentence with no sensitive data.") == []


def test_find_pii_handles_empty_and_none():
    assert find_pii("") == []
    assert find_pii(None) == []


def test_find_pii_detects_partial_card_in_text():
    findings = find_pii("The card ending 4122 was declined.")
    types = [t for t, _ in findings]
    assert "partial_card" in types


def test_find_pii_detects_ssn_in_text():
    findings = find_pii("SSN is 123-45-6789 on record.")
    types = [t for t, _ in findings]
    assert "ssn" in types


def test_find_pii_ignores_iso_dates():
    findings = find_pii("Updated 2026-04-14 per policy.")
    # ISO date should not be classified as phone
    assert not any(t == "phone" for t, _ in findings)
