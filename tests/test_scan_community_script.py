"""Tests for the community/ PII gate script."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "scan_community_pii.py"


def _run_script(target_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(target_dir)],
        capture_output=True,
        text=True,
    )


def test_scan_script_passes_on_clean_dir(tmp_path):
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "dictionary.yaml").write_text("""
dataset:
  name: test
  description: Clean test
  source: Generic CSV export
  grain: one row per transaction
  pii: false
  pii_fields: []
  naming_convention: snake_case
  last_updated: "2026-04-14"
fields:
  - name: amount
    label: Amount
    type: decimal
    dtype: float64
    nullable: false
    notes: Transaction amount in USD
""")
    (clean / "README.md").write_text("# test\n\nClean content with no PII.\n")

    result = _run_script(clean)
    assert result.returncode == 0, result.stdout + result.stderr


def test_scan_script_fails_on_pii_in_markdown(tmp_path):
    dirty = tmp_path / "dirty"
    dirty.mkdir()
    (dirty / "README.md").write_text("Contact us at jane@example.com for help.\n")

    result = _run_script(dirty)
    assert result.returncode != 0
    assert "email" in result.stdout.lower() or "email" in result.stderr.lower()


def test_scan_script_fails_on_pii_in_yaml_notes(tmp_path):
    dirty = tmp_path / "dirty"
    dirty.mkdir()
    (dirty / "dictionary.yaml").write_text("""
dataset:
  name: leaky
  description: test
  source: test
  grain: test
  pii: false
  pii_fields: []
  naming_convention: snake_case
  last_updated: "2026-04-14"
fields:
  - name: foo
    label: Foo
    type: text
    dtype: string
    nullable: true
    notes: "Card ending 4122 was used"
""")

    result = _run_script(dirty)
    assert result.returncode != 0


def test_scan_script_handles_missing_directory(tmp_path):
    missing = tmp_path / "does_not_exist"
    result = _run_script(missing)
    # Missing dir is treated as empty/clean — exit 0
    assert result.returncode == 0
