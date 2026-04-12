"""Tests for input scrubbing — encoding, sanitization, header detection."""

import textwrap
from pathlib import Path

import pytest

from dictionary_pipeline.scrub import detect_encoding


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
