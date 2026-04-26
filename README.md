# dictionary-pipeline

### Turn messy spreadsheets into validated, documented datasets.

[![Version 0.2.0](https://img.shields.io/badge/version-0.2.0-blue)](https://github.com/inire/dictionary-pipeline)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![pandas-first](https://img.shields.io/badge/pandas--first-deterministic-orange)](https://github.com/inire/dictionary-pipeline)
[![Tests: 48](https://img.shields.io/badge/tests-48_passing-brightgreen)](tests/)

The **data dictionary is the contract** — a single YAML file that *is* the schema, *generates* the pandera validator, *specifies* all derivations, and *renders* into the final Excel deliverable's documentation tab. LLM calls are scoped to exactly the two stages where judgment actually matters; everything else is deterministic Python.

| Problem | Without this tool | With this tool |
|---------|-------------------|----------------|
| **Data uncertainty** (GIGO from messy inputs) | Manual cleanup, no audit trail | Deterministic profiling → schema enforcement → logged transformations |
| **LLM drift in Excel** (context grows, Claude hallucinates) | Long chat sessions, silent errors | 90% deterministic Python; LLM limited to two short, scoped calls |

---

## Quick Start

```bash
git clone https://github.com/inire/dictionary-pipeline.git
cd dictionary-pipeline
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

dictionary-pipeline run \
  --input path/to/your_data.xlsx \
  --contract path/to/dictionary.yaml \
  --workdir runs/my_run
```

**Optional extras:**

```bash
pip install -e ".[llm]"       # Anthropic SDK for stages 3 and 6
pip install -e ".[profiling]" # ydata-profiling for richer Stage 1 output
pip install -e ".[fuzzy]"     # rapidfuzz for fuzzy matching in Stage 5
```

---

## How It Works

```mermaid
flowchart LR
    A[📄 Raw CSV / TSV / Excel] --> B(S0: Intake\narchive + load)
    B --> C(S1: Profile\nstats + PII scan)
    C --> D[/S2: Answer Prompt\nmanual/]
    D --> E(S3: Draft Dictionary\nClaude API ✨)
    E --> F(S4: Schema Enforce\npandera coercion)
    F --> G(S5: Rule-Based Clean\ndeterministic)
    G --> H(S6: Judgment Clean\nClaude API ✨)
    H --> I(S7: Derive Columns\nYAML-defined)
    I --> J(S8: Validate\ndrift check)
    J --> K(S9: Export\n3-tab workbook)
    K --> L[/S10: Final Compare\nClaude in Excel/]

    style D fill:#fffbe6,stroke:#f0c040
    style E fill:#e6f3ff,stroke:#4090d0
    style H fill:#e6f3ff,stroke:#4090d0
    style L fill:#fffbe6,stroke:#f0c040
```

Yellow = manual step · Blue = LLM call · White = deterministic Python

---

## Pipeline Stages

| Stage | Name | Mutates data? | LLM? | What it does |
|-------|------|:---:|:---:|-------------|
| 0 | Intake | no | no | Preserves the original; loads with auto-encoding and auto-header detection |
| 1 | Profile | no | no | Stats, top values, and PII flags before you touch anything |
| 2 | Answer prompt | no | yes | You describe what each column means — feeds the dictionary draft |
| 3 | Draft dictionary | no | yes | Produces the YAML contract from your descriptions and the profile |
| 4 | Schema enforce | coercion | no | Rejects or coerces values that violate the contract |
| 5 | Rule-based clean | yes | no | Fast, auditable fixes: strip whitespace, map aliases, drop duplicates |
| 6 | Judgment clean | yes (scoped) | yes | Normalizes values that rules can't handle (typos, cultural variants) |
| 7 | Derive columns | adds columns | no | Computes new fields from YAML-specified transformations — no eval |
| 8 | Validate | no | no | Re-runs the schema + diffs against the archive to catch any drift |
| 9 | Export to Excel | no | no | Writes a 3-tab workbook: cleaned data, data dictionary, change log |
| 10 | Final compare | no | yes | Short, bounded review — Claude compares before/after, not free-form |

> Stages 0, 1, 4, 5, 7, 8, 9 run via the CLI today. Stages 3 and 6 are stubs awaiting your preferred Claude entry point. Stages 2 and 10 are manual.

---

## What You Get

After a run, your `--workdir` contains:

| File | Description |
|------|-------------|
| `archive/your_data.xlsx` | Original file, untouched |
| `manifest.json` | Row count, column list, encoding, detected header row |
| `profile.json` | Per-column stats: dtype, nulls, top values, PII flags |
| `profile_report.html` | Full HTML report (if `[profiling]` extra installed) |
| `enforced.parquet` | Post-schema-enforcement checkpoint |
| `cleaned.parquet` | Post-clean checkpoint |
| `derived.parquet` | Post-derivation checkpoint |
| `transformations.jsonl` | Every transformation logged with timestamps and stage |
| `your_data.xlsx` | Final 3-tab Excel workbook for delivery |

Stage state is checkpointed to parquet, so you can rerun any single stage:

```bash
dictionary-pipeline enforce --workdir runs/my_run --contract dict.yaml
dictionary-pipeline derive  --workdir runs/my_run --contract dict.yaml
dictionary-pipeline export  --workdir runs/my_run --contract dict.yaml
```

---

## Wiring Up the LLM Stages

`s3_dictionary.py` and `s6_judgment.py` both have a `_call_claude(prompt)` function that raises `NotImplementedError`. Replace it with your preferred entry point:

```python
# Option 1: Anthropic SDK
import anthropic
client = anthropic.Anthropic()
response = client.messages.create(model="claude-opus-4-6", max_tokens=4096, ...)

# Option 2: Claude Code subprocess
import subprocess
result = subprocess.run(["claude", "-p", prompt], capture_output=True, text=True)

# Option 3: Local proxy / OpenAI-compatible endpoint
```

---

## Architecture

```
src/dictionary_pipeline/
├── bulk.py              # multi-file schema grouping + bulk intake orchestration
├── contract.py          # YAML <-> pandera schema bridge, derivation engine
├── logging.py           # JSONL transformation log
├── cli.py               # argparse entry point
├── pii.py               # PII detection (regex) + profile redaction
├── scrub.py             # encoding detection, formula injection scan, header detection
└── stages/
    ├── s0_intake.py     # archive original, load, manifest
    ├── s1_profile.py    # deterministic profile with optional PII redaction
    ├── s3_dictionary.py # STUB — Claude API: draft dictionary
    ├── s4_enforce.py    # pandera validation + coercion
    ├── s5_clean.py      # rule-based cleaning
    ├── s6_judgment.py   # STUB — Claude API: normalize ambiguous values
    ├── s7_derive.py     # execute derivations from contract
    ├── s8_validate.py   # re-validate + diff against archive
    └── s9_export.py     # write 3-tab Excel workbook
```

---

## Testing

```bash
pytest tests/ -v
```

48 tests cover: contract layer, intake (CSV/TSV/encoding/header detection), PII detection and profile redaction, bulk schema grouping, and scrub utilities.

---

## Community Dictionary Sharing

Pre-built dictionaries for common datasets live in [`community/`](community/). Each entry has a scrubbed `dictionary.yaml` and a `README.md`.

```bash
cp community/_template/dictionary.yaml my_run/
dictionary-pipeline run --input my_data.csv --contract my_run/dictionary.yaml --workdir runs/my_run
```

To contribute a dictionary:

```bash
dictionary-pipeline community-export \
  --contract path/to/your_dictionary.yaml \
  --output-dir community/your_dataset/
```

This scans for PII, drops fields marked `shareable: false`, and redacts PII substrings. See [`community/CONTRIBUTING.md`](community/CONTRIBUTING.md).

---

## Contributing

1. Fork the repo and create a feature branch.
2. Add tests for any new behaviour (`pytest tests/ -v` must pass).
3. Open a PR — describe what problem it solves and link any relevant issues.
