"""Tests for input scrubbing — encoding, sanitization, header detection."""

import textwrap
from pathlib import Path

import pytest

from dictionary_pipeline.scrub import detect_encoding, scan_formula_injection, strip_control_chars
from dictionary_pipeline.scrub import detect_header_row


def test_detect_utf8(tmp_path: Path):
    p = tmp_path / "utf8.csv"
    p.write_text("Name,City\nAlice,Zürich\n", encoding="utf-8")
    assert detect_encoding(p) == "utf-8"


def test_detect_latin1(tmp_path: Path):
    p = tmp_path / "latin1.csv"
    p.write_bytes("Name,City\nAlice,Café\n".encode("latin-1"))
    result = detect_encoding(p)
    assert result in ("latin-1", "ISO-8859-1", "Windows-1252", "iso-8859-1", "windows-1252", "cp1250", "cp1252")


def test_detect_utf8_bom(tmp_path: Path):
    p = tmp_path / "bom.csv"
    p.write_bytes(b"\xef\xbb\xbf" + "Name,City\nAlice,Zürich\n".encode("utf-8"))
    assert detect_encoding(p) == "utf-8-sig"


def test_scan_finds_formula_cells(tmp_path: Path):
    p = tmp_path / "formulas.csv"
    p.write_text(textwrap.dedent("""\
        Name,Value
        Alice,100
        =CMD("calc"),200
        Bob,+1-555-1234
        @SUM(A1:A3),300
    """))
    hits = scan_formula_injection(p)
    assert len(hits) == 2
    # =CMD is dangerous, @SUM is dangerous
    # +1-555-1234 is NOT flagged (phone number pattern, not a formula)
    assert any("=CMD" in h["value"] for h in hits)
    assert any("@SUM" in h["value"] for h in hits)


def test_scan_clean_file_returns_empty(tmp_path: Path):
    p = tmp_path / "clean.csv"
    p.write_text("Name,Age\nAlice,30\nBob,25\n")
    hits = scan_formula_injection(p)
    assert hits == []


def test_strip_removes_null_bytes():
    assert strip_control_chars("hello\x00world") == "helloworld"


def test_strip_preserves_newlines_and_tabs():
    assert strip_control_chars("hello\tworld\n") == "hello\tworld\n"


def test_strip_removes_mixed_control():
    assert strip_control_chars("a\x01b\x02c\x7fd") == "abcd"


def test_strip_handles_none():
    assert strip_control_chars(None) is None


def test_detect_header_standard_csv(tmp_path: Path):
    """Row 0 is the header when it looks like column names."""
    p = tmp_path / "standard.csv"
    p.write_text("Name,Age,Score\nAlice,30,95\nBob,25,87\n")
    assert detect_header_row(p) == 0


def test_detect_header_with_preamble(tmp_path: Path):
    """Fidelity-style: descriptive row, blank row, then headers on row 2."""
    p = tmp_path / "preamble.csv"
    p.write_text(textwrap.dedent('''\
        "Positions for account Rollover IRA ...965 as of 03:17 PM ET, 2026/03/28"

        "Symbol","Description","Qty","Price","Mkt Val","Asset Type",
        "VTSAX","VANGUARD TOTAL STOCK","46.12","152.42","$7,029.61","Mutual Fund",
    '''))
    assert detect_header_row(p) == 2


def test_detect_header_single_preamble_row(tmp_path: Path):
    """One junk row then the header."""
    p = tmp_path / "one_junk.csv"
    p.write_text(textwrap.dedent("""\
        Report generated 2026-03-28
        Date,Description,Amount,Category
        03/17/2026,STORE,41.88,Merchandise
    """))
    assert detect_header_row(p) == 1
