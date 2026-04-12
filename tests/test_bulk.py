"""Tests for bulk multi-file intake and schema grouping."""

import textwrap
from pathlib import Path

import pytest

from dictionary_pipeline.bulk import group_by_schema


def test_groups_identical_headers(tmp_path: Path):
    """Files with the same columns get grouped together."""
    (tmp_path / "a.csv").write_text("Name,Age,Score\nAlice,30,95\n")
    (tmp_path / "b.csv").write_text("Name,Age,Score\nBob,25,87\n")
    (tmp_path / "c.csv").write_text("Date,Amount,Category\n2026-01-01,100,Food\n")

    groups = group_by_schema(tmp_path.glob("*.csv"))
    assert len(groups) == 2

    # Find the group with Name,Age,Score
    name_group = [g for g in groups if "Name" in g["columns"]][0]
    assert len(name_group["files"]) == 2

    # Find the group with Date,Amount,Category
    date_group = [g for g in groups if "Date" in g["columns"]][0]
    assert len(date_group["files"]) == 1


def test_groups_handle_header_detection(tmp_path: Path):
    """Files with preamble rows should still group correctly."""
    (tmp_path / "normal.csv").write_text("X,Y,Z\n1,2,3\n")
    (tmp_path / "preamble.csv").write_text('"Report"\n\nX,Y,Z\n4,5,6\n')

    groups = group_by_schema(tmp_path.glob("*.csv"))
    assert len(groups) == 1
    assert len(groups[0]["files"]) == 2


def test_empty_glob_returns_empty():
    groups = group_by_schema([])
    assert groups == []
