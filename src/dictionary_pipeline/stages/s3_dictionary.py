"""
Stage 3 — Draft Dictionary (LLM-in-the-loop, STUB).

Hands Claude the profile_summary.json + answer_prompt.md + a small sample,
asks for a YAML dictionary back, and writes it to disk.

This module is a STUB. Wire your preferred Claude entry point in `_call_claude`:
  - Anthropic API directly
  - claude-code as a subprocess (`claude code -p ...`)
  - your existing OpenClaw-style local proxy

The contract this stage must produce:
  - Output a YAML file matching the structure in examples/doordash/dictionary.yaml
  - Every source column from the profile must appear in `fields`
  - `derived_fields` is optional at this stage; can be added in a later iteration
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ..logging import TransformationLog

PROMPT_TEMPLATE = """You are drafting a data dictionary for a dataset.

ANSWER PROMPT (what this data needs to support):
{answer_prompt}

PROFILE SUMMARY:
{profile_json}

SAMPLE ROWS (first 50):
{sample_csv}

Produce a YAML dictionary matching this structure:

dataset:
  name: <snake_case_name>
  description: <one sentence>
  source: <where it came from>
  grain: <one row per WHAT?>
  pii: <true|false>
  pii_fields: [<list>]
  naming_convention: snake_case
  last_updated: "<YYYY-MM-DD>"

fields:
  - name: <snake_case_field_name>
    label: <human-readable label>
    type: <categorical|categorical_open|date|identifier|integer|decimal|text|bool>
    dtype: <pandas dtype string>
    nullable: <true|false>
    allowed_values: [<list>]   # categoricals only
    min: <number>              # numerics only
    max: <number>              # numerics only
    pattern: <regex>           # identifiers/text only
    null_tolerance: <0.0-1.0>  # only if nullable
    source_column: <original column name>
    notes: <free text>
    review_status: draft

Rules:
- Every column in the profile must appear as a field.
- Use snake_case for `name`, preserve original column header in `source_column`.
- Mark anything that looks like PII with `pii: true`.
- For text columns with no real cardinality (one value across all rows), say so in notes.
- For columns with truncated/unreliable data, set `reliability: unreliable`.

Return ONLY the YAML, no preamble or fences.
"""


def _call_claude(prompt: str) -> str:
    """
    REPLACE THIS with your preferred Claude entry point.

    Reference implementations:

    # Option A: Anthropic SDK
    # from anthropic import Anthropic
    # client = Anthropic()
    # resp = client.messages.create(
    #     model="claude-opus-4-6",
    #     max_tokens=8000,
    #     messages=[{"role": "user", "content": prompt}],
    # )
    # return resp.content[0].text

    # Option B: claude-code subprocess
    # import subprocess
    # r = subprocess.run(
    #     ["claude", "code", "-p", prompt],
    #     capture_output=True, text=True, check=True,
    # )
    # return r.stdout
    """
    raise NotImplementedError(
        "Stage 3 needs a Claude entry point. Edit _call_claude() in s3_dictionary.py."
    )


def run(
    df: pd.DataFrame,
    profile_summary: dict,
    answer_prompt_path: str | Path,
    workdir: str | Path,
    log: TransformationLog | None = None,
) -> Path:
    workdir = Path(workdir)
    answer_prompt = Path(answer_prompt_path).read_text()
    sample_csv = df.head(50).to_csv(index=False)

    prompt = PROMPT_TEMPLATE.format(
        answer_prompt=answer_prompt,
        profile_json=json.dumps(profile_summary, indent=2, default=str),
        sample_csv=sample_csv,
    )

    yaml_text = _call_claude(prompt)
    output_path = workdir / "dictionary_draft.yaml"
    output_path.write_text(yaml_text)

    if log:
        log.log(
            stage="s3_dictionary",
            event="dictionary_drafted",
            rows_affected=0,
            details={"output": str(output_path)},
        )
    return output_path
