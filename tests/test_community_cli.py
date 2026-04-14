"""Integration tests for the community-export CLI command."""

from __future__ import annotations

from pathlib import Path

import pytest

from dictionary_pipeline.cli import main


def _write_contract(path: Path, notes: str = "Order total in USD") -> None:
    path.write_text(f"""
dataset:
  name: orders
  description: Order history
  source: CSV export
  grain: one row per order
  pii: false
  pii_fields: []
  naming_convention: snake_case
  last_updated: "2026-04-14"

fields:
  - name: total
    label: Total
    type: decimal
    dtype: float64
    nullable: false
    notes: "{notes}"
""")


def test_community_export_cli_produces_bundle(tmp_path):
    contract = tmp_path / "dict.yaml"
    _write_contract(contract)
    out_dir = tmp_path / "out"

    rc = main([
        "community-export",
        "--contract", str(contract),
        "--output-dir", str(out_dir),
    ])

    assert rc == 0
    assert (out_dir / "dictionary.yaml").exists()
    assert (out_dir / "README.md").exists()


def test_community_export_cli_rejects_unsafe_without_force(tmp_path, capsys):
    contract = tmp_path / "dict.yaml"
    _write_contract(contract, notes="Reach us at jane@example.com anytime")
    out_dir = tmp_path / "out"

    rc = main([
        "community-export",
        "--contract", str(contract),
        "--output-dir", str(out_dir),
    ])

    assert rc != 0
    err = capsys.readouterr().err
    assert "email" in err.lower() or "unsafe" in err.lower()


def test_community_export_cli_force_flag_proceeds(tmp_path):
    contract = tmp_path / "dict.yaml"
    _write_contract(contract, notes="Reach us at jane@example.com anytime")
    out_dir = tmp_path / "out"

    rc = main([
        "community-export",
        "--contract", str(contract),
        "--output-dir", str(out_dir),
        "--force",
    ])

    assert rc == 0
    assert (out_dir / "dictionary.yaml").exists()
    md = (out_dir / "README.md").read_text()
    assert "jane@example.com" not in md
