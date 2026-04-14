"""Test that Stage 1 profile respects the redact flag."""

from pathlib import Path

import json
import pandas as pd

from dictionary_pipeline.cli import main
from dictionary_pipeline.stages.s1_profile import run


def test_profile_run_with_redact(tmp_path: Path):
    df = pd.DataFrame({
        "email": ["alice@example.com", "bob@test.org", "alice@example.com"],
        "amount": [42.99, 19.95, 42.99],
    })
    run(df, tmp_path, redact_pii=True)

    profile = json.loads((tmp_path / "profile_summary.json").read_text())
    email_top = profile["columns"]["email"]["top_values"]
    assert all("REDACTED" in k for k in email_top)


def test_profile_run_without_redact(tmp_path: Path):
    df = pd.DataFrame({
        "email": ["alice@example.com", "bob@test.org"],
        "amount": [42.99, 19.95],
    })
    run(df, tmp_path, redact_pii=False)

    profile = json.loads((tmp_path / "profile_summary.json").read_text())
    email_top = profile["columns"]["email"]["top_values"]
    assert "alice@example.com" in email_top


def test_cli_profile_with_redact_pii_flag(tmp_path):
    # Set up a workdir with a parquet containing a PII column
    workdir = tmp_path / "run"
    workdir.mkdir()
    df = pd.DataFrame({
        "email": ["jane@example.com", "john@example.com", "jane@example.com"],
        "amount": [10.0, 20.0, 30.0],
    })
    df.to_parquet(workdir / "stage0_df.parquet")

    rc = main([
        "profile",
        "--workdir", str(workdir),
        "--redact-pii",
    ])
    assert rc == 0

    summary = json.loads((workdir / "profile_summary.json").read_text())
    top = summary["columns"]["email"]["top_values"]
    # email values should be redacted
    assert not any("@" in k for k in top.keys())
    assert any("REDACTED_EMAIL" in k for k in top.keys())


def test_cli_profile_without_redact_pii_flag_preserves_values(tmp_path):
    workdir = tmp_path / "run"
    workdir.mkdir()
    df = pd.DataFrame({
        "email": ["jane@example.com", "john@example.com"],
    })
    df.to_parquet(workdir / "stage0_df.parquet")

    rc = main(["profile", "--workdir", str(workdir)])
    assert rc == 0

    summary = json.loads((workdir / "profile_summary.json").read_text())
    top = summary["columns"]["email"]["top_values"]
    assert "jane@example.com" in top
