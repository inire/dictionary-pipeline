"""Tests for Stage 0 multi-format intake dispatch."""

import textwrap
from pathlib import Path

import pandas as pd
import pytest

from dictionary_pipeline.stages.s0_intake import read_source


@pytest.fixture()
def csv_file(tmp_path: Path) -> Path:
    p = tmp_path / "test.csv"
    p.write_text(textwrap.dedent("""\
        Name,Age,Score
        Alice,30,95.5
        Bob,25,87.0
        Carol,28,91.2
    """))
    return p


@pytest.fixture()
def tsv_file(tmp_path: Path) -> Path:
    p = tmp_path / "test.tsv"
    p.write_text(textwrap.dedent("""\
        Name\tAge\tScore
        Alice\t30\t95.5
        Bob\t25\t87.0
        Carol\t28\t91.2
    """))
    return p


def test_read_csv(csv_file: Path):
    df, info = read_source(csv_file)
    assert len(df) == 3
    assert list(df.columns) == ["Name", "Age", "Score"]
    assert info["reader"] == "pandas.read_csv"
    assert info["params"]["header"] == 0


def test_read_tsv(tsv_file: Path):
    df, info = read_source(tsv_file)
    assert len(df) == 3
    assert list(df.columns) == ["Name", "Age", "Score"]
    assert info["reader"] == "pandas.read_csv"
    assert info["params"]["sep"] == "\t"


def test_read_csv_with_nrows(csv_file: Path):
    df, info = read_source(csv_file, nrows=2)
    assert len(df) == 2
    assert info["params"]["nrows"] == 2


def test_read_csv_with_header_row(tmp_path: Path):
    p = tmp_path / "preamble.csv"
    p.write_text(textwrap.dedent("""\
        Report Title,,,
        Generated 2025-01-01,,,
        Name,Age,Score,Grade
        Alice,30,95.5,A
        Bob,25,87.0,B
    """))
    df, info = read_source(p, header_row=2)
    assert len(df) == 2
    assert list(df.columns) == ["Name", "Age", "Score", "Grade"]
    assert info["params"]["header"] == 2


def test_unsupported_extension_raises(tmp_path: Path):
    p = tmp_path / "data.json"
    p.write_text('{"a": 1}')
    with pytest.raises(ValueError, match="Unsupported file extension"):
        read_source(p)


def test_read_latin1_csv(tmp_path: Path):
    """Stage 0 should auto-detect Latin-1 encoding."""
    p = tmp_path / "latin1.csv"
    p.write_bytes("Name,City\nAlice,Café\n".encode("latin-1"))
    df, info = read_source(p)
    assert len(df) == 1
    # The value should be readable (not garbled)
    assert "Caf" in df["City"].iloc[0]


def test_read_csv_with_auto_header_detection(tmp_path: Path):
    """Stage 0 should auto-detect header row when header_row='auto'."""
    p = tmp_path / "preamble.csv"
    p.write_text(textwrap.dedent('''\
        "Report for account XYZ"

        Name,Age,Score
        Alice,30,95
        Bob,25,87
    '''))
    df, info = read_source(p, header_row="auto")
    assert list(df.columns) == ["Name", "Age", "Score"]
    assert len(df) == 2
