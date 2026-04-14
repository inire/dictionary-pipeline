# dictionary-pipeline

A pandas-first data preparation pipeline where the **data dictionary is the contract**. Tabular files in for intake (CSV, TSV, Excel), `.xlsx` out for delivery, deterministic Python in between. LLM calls are scoped to the two stages where judgment actually matters (drafting the dictionary, normalizing ambiguous values), and the dictionary itself is enforced mechanically by pandera so an LLM never silently drifts the data.

## Why this exists

Built to address two parallel problems in spreadsheet-driven analytical work:

1. **Data uncertainty** (GIGO from messy user inputs) — addressed with deterministic profiling, pandera schema enforcement, and a structured cleaning pipeline.
2. **LLM uncertainty** (Claude in Excel context drift over long sessions) — addressed by routing 90% of the work through deterministic Python and reducing Claude in Excel to a single short comparison session at the end.

The data dictionary stops being prose documentation and becomes a YAML file that *is* the schema, that *generates* the pandera validator, that *specifies* the derivations, and that *renders* into the final Excel deliverable's documentation tab.

## Pipeline stages

| Stage | Name              | Tool         | Mutates data? | LLM? |
|-------|-------------------|--------------|---------------|------|
| 0     | Intake            | Python       | no (archive)  | no   |
| 1     | Profile           | Python       | no            | no   |
| 2     | Answer prompt     | Claude (chat)| no            | yes  |
| 3     | Draft dictionary  | Claude API   | no            | yes  |
| 4     | Schema enforce    | pandera      | coercion only | no   |
| 5     | Rule-based clean  | Python       | yes           | no   |
| 6     | Judgment clean    | Claude API   | yes (scoped)  | yes  |
| 7     | Derive columns    | Python       | adds columns  | no   |
| 8     | Validate          | Python       | no            | no   |
| 9     | Export to Excel   | openpyxl     | no            | no   |
| 10    | Final compare     | Claude in Excel | no         | yes  |

Stages 0, 1, 4, 5, 7, 8, 9 run via the CLI today. Stages 3 and 6 are stubs awaiting your preferred Claude entry point. Stages 2 and 10 are manual.

## Install

```bash
git clone <your-repo-url> dictionary-pipeline
cd dictionary-pipeline
python -m venv .venv
source .venv/bin/activate    # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"
```

Optional extras:
- `pip install -e ".[llm]"` — Anthropic SDK for stages 3 and 6
- `pip install -e ".[profiling]"` — ydata-profiling for richer Stage 1 output
- `pip install -e ".[fuzzy]"` — rapidfuzz for fuzzy matching in Stage 5

## Quickstart

```bash
dictionary-pipeline run \
  --input path/to/your_data.xlsx \
  --contract path/to/dictionary.yaml \
  --workdir runs/my_run \
  --sheet "Sheet1"
```

The pipeline accepts CSV, TSV, and Excel files. For CSVs, encoding and header row are auto-detected.

Output:

```
[s0] intake: path/to/your_data.xlsx
     loaded 532 rows x 13 cols
[s1] profiling...
[s4] enforcing schema from path/to/dictionary.yaml
     validated 532 rows against 13 fields
[s5] cleaning (rule-based)...
[s7] deriving 3 columns...
[s8] validating final output...
     schema: passed | drift columns: none
[s9] exporting workbook...
     wrote runs/my_run/your_data.xlsx
```

The output workbook contains three tabs:
- **your_data** — the cleaned data with derived columns
- **Data Dictionary** — rendered from `dictionary.yaml`
- **Automated Changes** — every transformation logged with timestamps

For bulk intake of multiple files (grouped by schema automatically):

```bash
dictionary-pipeline bulk-intake \
  --input path/to/exports/*.csv \
  --workdir runs/bulk_run
```

## Stage-by-stage usage

Each stage can also be run individually for iteration:

```bash
dictionary-pipeline intake  --input file.xlsx --workdir runs/foo
dictionary-pipeline profile --workdir runs/foo
dictionary-pipeline enforce --workdir runs/foo --contract dict.yaml
dictionary-pipeline derive  --workdir runs/foo --contract dict.yaml
dictionary-pipeline export  --workdir runs/foo --contract dict.yaml
```

Stage state is checkpointed to parquet files between stages, so you can iterate on a single stage without re-running the whole pipeline.

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

## Wiring up the LLM stages

`s3_dictionary.py` and `s6_judgment.py` both have a `_call_claude(prompt)` function that raises `NotImplementedError`. Replace it with your preferred entry point. Reference implementations are in the docstrings — Anthropic SDK direct, Claude Code subprocess, or a local proxy.

The prompts themselves are defined as `PROMPT_TEMPLATE` constants at the top of each stage file. They're worth tuning for your specific datasets.

## Testing

```bash
pytest tests/ -v
```

The test suite has 48 tests covering the contract layer (load, schema, validation, derivations, rename), intake (CSV/TSV/encoding/header detection), PII detection and profile redaction, bulk schema grouping, and scrub utilities. Add tests for your custom derivation patterns as you register them in `contract.apply_derivations()`.

> **Note:** The `examples/` directory is not included in this repository. Some contract tests (`test_contract.py`) expect example dictionaries at `examples/doordash/` and `examples/instacart/`. To run those tests, create your own example datasets and dictionaries following the format in `project_files/dictionary_contract_format.md`.

## Adding a new derivation pattern

`apply_derivations()` in `contract.py` deliberately uses pattern matching, not eval, for safety. To add a new derivation:

1. Add the pattern to your `dictionary.yaml`:
   ```yaml
   derived_fields:
     - name: tax_amount
       transformation: "product_price * 0.08"
       ...
   ```
2. Register the pattern in `apply_derivations()`:
   ```python
   elif t == "product_price * 0.08":
       out[d.name] = out["product_price"] * 0.08
   ```

If patterns proliferate, factor them out to a registry module.

## Community dictionary sharing

Data dictionaries for common datasets (bank exports, retailer order history, etc.) are shared in the `community/` folder. Each entry contains a scrubbed `dictionary.yaml` and a human-readable `README.md`.

### Using a community dictionary

```bash
# Copy the contract next to your own data
cp community/shopping_orders/dictionary.yaml my_run/

# Run the pipeline as usual
dictionary-pipeline run \
  --input my_data.csv \
  --contract my_run/dictionary.yaml \
  --workdir runs/my_run
```

You will likely need to adjust `source_column` mappings to match your specific export's headers, since that field is stripped from community artifacts.

### Contributing a dictionary

Build your own dictionary against a real dataset, then:

```bash
dictionary-pipeline community-export \
  --contract path/to/your_dictionary.yaml \
  --output-dir community/your_dataset/
```

This scans for PII, drops fields marked `shareable: false`, replaces `notes` with `community_notes` if provided, and redacts PII substrings (emails, SSNs, partial card numbers, phone numbers) from free-text fields. A PII-unsafe contract fails the export unless `--force` is passed — and `--force` still runs full sanitization, it just bypasses the blocking check.

See [`community/CONTRIBUTING.md`](community/CONTRIBUTING.md) for the full guide.

### PII redaction in profiles

The Stage 1 profile's `top_values` entries can contain real data. Use `--redact-pii` to replace them with `[REDACTED_TYPE]` placeholders:

```bash
dictionary-pipeline profile --workdir runs/foo --redact-pii
dictionary-pipeline run --input data.csv --contract dict.yaml --workdir runs/foo --redact-pii
```
