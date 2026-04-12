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
