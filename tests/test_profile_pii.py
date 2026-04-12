"""Test that Stage 1 profile respects the redact flag."""

from pathlib import Path

import json
import pandas as pd

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
