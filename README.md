# dictionary-pipeline

> 11-stage pipeline that turns messy spreadsheets into validated, documented datasets

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Version](https://img.shields.io/badge/version-0.2.0-informational)
![pandas-first](https://img.shields.io/badge/pandas--first-deterministic-orange)

The **data dictionary is the contract** — a single YAML file that *is* the schema, *generates* the pandera validator, *specifies* all derivations, and *renders* into the final Excel deliverable's documentation tab. LLM calls are scoped to exactly the two stages where judgment actually matters; everything else is deterministic Python.

---

## 🤔 Why This Exists

Two problems appear together in spreadsheet-driven analytical work:

| Problem | Without this tool | With this tool |
|---|---|---|
| **Data uncertainty** (GIGO from messy inputs) | Manual cleanup, no audit trail | Deterministic profiling → schema enforcement → logged transformations |
| **LLM drift in Excel** (context grows, Claude hallucinates) | Long chat sessions, silent errors | 90% deterministic Python; LLM limited to two short, scoped calls |

The data dictionary bridges both — it stops being prose documentation and becomes the executable contract that every stage reads.

---

## 🚀 Quick Start

Clone, install, and run on the included DoorDash example in under 60 seconds:

```bash
git clone <your-repo-url> dictionary-pipeline
cd dictionary-pipeline
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# Run the pipeline on your data
dictionary-pipeline run \
  --input path/to/your_data.xlsx \
  --contract path/to/dictionary.yaml \
  --workdir runs/my_run
```

> **Note:** The `examples/` directory is not bundled in this repo. Tests expect `examples/doordash/` and `examples/instacart/` — create them from the format described in [`project_files/dictionary_contract_format.md`](project_files/dictionary_contract_format.md), or copy a ready-made contract from [`community/`](community/).

**Optional extras:**

```bash
pip install -e ".[llm]"       # Anthropic SDK for stages 3 and 6
pip install -e ".[profiling]" # ydata-profiling for richer Stage 1 output
pip install -e ".[fuzzy]"     # rapidfuzz for fuzzy matching in Stage 5
```

---

## 🔄 How It Works

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

Yellow = manual step &nbsp;|&nbsp; Blue = LLM call &nbsp;|&nbsp; White = deterministic Python

---

## 📋 Pipeline Stages

| Stage | Name | Tool | Mutates data? | LLM? | Why it matters |
|---|---|---|---|---|---|
| 0 | Intake | Python | no (archive) | no | Preserves the original; loads with auto-encoding and auto-header detection |
| 1 | Profile | Python | no | no | Gives you stats, top values, and PII flags before you touch anything |
| 2 | Answer prompt | Claude (chat) | no | yes | You describe what each column means — feeds the dictionary draft |
| 3 | Draft dictionary | Claude API | no | yes | Produces the YAML contract from your descriptions and the profile |
| 4 | Schema enforce | pandera | coercion only | no | Rejects or coerces values that violate the contract; nothing slips through |
| 5 | Rule-based clean | Python | yes | no | Fast, auditable fixes: strip whitespace, map aliases, drop duplicates |
| 6 | Judgment clean | Claude API | yes (scoped) | yes | Normalizes values that rules can't handle (typos, cultural variants) |
| 7 | Derive columns | Python | adds columns | no | Computes new fields from YAML-specified transformations — no eval |
| 8 | Validate | Python | no | no | Re-runs the schema + diffs against the archive to catch any drift |
| 9 | Export to Excel | openpyxl | no | no | Writes a 3-tab workbook: cleaned data, data dictionary, change log |
| 10 | Final compare | Claude in Excel | no | yes | Short, bounded review session — Claude compares before/after, not free-form |

> Stages 0, 1, 4, 5, 7, 8, 9 run via the CLI today. Stages 3 and 6 are stubs awaiting your preferred Claude entry point. Stages 2 and 10 are manual.

---

## 📦 What You Get

After a run, your `--workdir` contains:

| File | Description |
|---|---|
| `archive/your_data.xlsx` | Original file, untouched, copied on intake |
| `manifest.json` | Row count, column list, encoding, detected header row |
| `profile.json` | Per-column stats: dtype, nulls, top values, PII flags |
| `profile_report.html` | Full HTML report (if `[profiling]` extra installed) |
| `enforced.parquet` | Post-schema-enforcement snapshot (checkpoint) |
| `cleaned.parquet` | Post-clean snapshot (checkpoint) |
| `derived.parquet` | Post-derivation snapshot (checkpoint) |
| `transformations.jsonl` | Every transformation logged with timestamps and stage |
| `your_data.xlsx` | Final 3-tab Excel workbook for delivery |

Stage state is checkpointed to parquet between stages, so you can rerun a single stage without starting over:

```bash
dictionary-pipeline enforce --workdir runs/my_run --contract dict.yaml
dictionary-pipeline derive  --workdir runs/my_run --contract dict.yaml
dictionary-pipeline export  --workdir runs/my_run --contract dict.yaml
```

---

## 🛠️ Stage-by-Stage CLI

Run any individual stage for iteration:

```bash
dictionary-pipeline intake  --input file.xlsx --workdir runs/foo
dictionary-pipeline profile --workdir runs/foo
dictionary-pipeline enforce --workdir runs/foo --contract dict.yaml
dictionary-pipeline derive  --workdir runs/foo --contract dict.yaml
dictionary-pipeline export  --workdir runs/foo --contract dict.yaml
```

For bulk intake of multiple files (auto-grouped by schema):

```bash
dictionary-pipeline bulk-intake \
  --input path/to/exports/*.csv \
  --workdir runs/bulk_run
```

---

## 🔌 Wiring Up the LLM Stages

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

The prompts are defined as `PROMPT_TEMPLATE` constants at the top of each stage file — worth tuning for your datasets.

---

## ➕ Adding a Derivation Pattern

`apply_derivations()` uses pattern matching, not `eval`, for safety. To add a new derivation:

1. Add the pattern to `dictionary.yaml`:
   ```yaml
   derived_fields:
     - name: tax_amount
       transformation: "product_price * 0.08"
   ```
2. Register the pattern in `contract.py`:
   ```python
   elif t == "product_price * 0.08":
       out[d.name] = out["product_price"] * 0.08
   ```

If patterns proliferate, factor them out to a registry module.

---

## 🏗️ Architecture

```
src/dictionary_pipeline/
├── bulk.py              # multi-file schema grouping + bulk intake orchestration
├── contract.py          # YAML <-> pandera schema bridge, derivation engine
├── logging.py           # JSONL transformation log
├── cli.py               # argparse entry point
├── pii.py               # PII detection (regex) + profile redaction
├── scrub.py             # encoding detection, formula injection scan, header detection
└── stages/
    ├── s0_intake.py     # archive original, load, manifest (auto-encoding, auto-header)
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

## 🧪 Testing

```bash
pytest tests/ -v
```

48 tests cover: contract layer (load, schema, validation, derivations, rename), intake (CSV/TSV/encoding/header detection), PII detection and profile redaction, bulk schema grouping, and scrub utilities.

> **Note:** `test_contract.py` expects `examples/doordash/` and `examples/instacart/`. Create your own following [`project_files/dictionary_contract_format.md`](project_files/dictionary_contract_format.md) to run those tests.

---

## 🌍 Community Dictionary Sharing

Pre-built dictionaries for common datasets (bank exports, retailer order history, etc.) live in [`community/`](community/). Each entry has a scrubbed `dictionary.yaml` and a `README.md`.

### Using a community dictionary

```bash
# Copy the contract next to your data
cp community/_template/dictionary.yaml my_run/

# Run as usual
dictionary-pipeline run \
  --input my_data.csv \
  --contract my_run/dictionary.yaml \
  --workdir runs/my_run
```

You'll likely need to adjust `source_column` mappings to match your export's headers — that field is stripped from community artifacts.

### Contributing a dictionary

Build a dictionary against a real dataset, then:

```bash
dictionary-pipeline community-export \
  --contract path/to/your_dictionary.yaml \
  --output-dir community/your_dataset/
```

This scans for PII, drops fields marked `shareable: false`, and redacts PII substrings (emails, SSNs, partial card numbers, phone numbers) from free-text fields. A PII-unsafe contract blocks export unless `--force` is passed — `--force` still runs full sanitization, it just bypasses the blocking check.

See [`community/CONTRIBUTING.md`](community/CONTRIBUTING.md) for the full guide.

### PII redaction in profiles

Stage 1's `top_values` entries can contain real data. Pass `--redact-pii` to replace them with `[REDACTED_TYPE]` placeholders before sharing:

```bash
dictionary-pipeline profile --workdir runs/foo --redact-pii
dictionary-pipeline run --input data.csv --contract dict.yaml --workdir runs/foo --redact-pii
```

---

## 📖 Detailed Usage

For a deep-dive on pre-run checklists, iterating on a single stage, and post-pipeline workflow see [**docs/workflow.md**](docs/workflow.md).

---

## 🤝 Contributing

1. Fork the repo and create a feature branch.
2. Add tests for any new behaviour (`pytest tests/ -v` must pass).
3. Open a PR — describe what problem it solves and link any relevant issues.

For dictionary contributions specifically, see [community/CONTRIBUTING.md](community/CONTRIBUTING.md).
