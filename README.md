# dictionary-pipeline

A pandas-first data preparation pipeline where the **data dictionary is the contract**. Excel only at the boundaries — `.xlsx` in for intake, `.xlsx` out for delivery, deterministic Python in between. LLM calls are scoped to the two stages where judgment actually matters (drafting the dictionary, normalizing ambiguous values), and the dictionary itself is enforced mechanically by pandera so an LLM never silently drifts the data.

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

End-to-end run on the bundled DoorDash example:

```bash
dictionary-pipeline run \
  --input examples/doordash/DoorDash_2026_Purchased_Items.xlsx \
  --contract examples/doordash/dictionary.yaml \
  --workdir runs/doordash \
  --sheet "DoorDash 2026 Purchased Items"
```

Output:

```
[s0] intake: examples/doordash/DoorDash_2026_Purchased_Items.xlsx
     loaded 532 rows x 13 cols
[s1] profiling...
[s4] enforcing schema from examples/doordash/dictionary.yaml
     validated 532 rows against 13 fields
[s5] cleaning (rule-based)...
[s7] deriving 3 columns...
[s8] validating final output...
     schema: passed | drift columns: none
[s9] exporting workbook...
     wrote runs/doordash/doordash_2026_purchased_items.xlsx
```

The output workbook contains three tabs:
- **doordash_2026_purchased_items** — the cleaned data with derived columns
- **Data Dictionary** — rendered from `dictionary.yaml`
- **Automated Changes** — every transformation logged with timestamps

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
├── contract.py          # YAML <-> pandera schema bridge, derivation engine
├── logging.py           # JSONL transformation log
├── cli.py               # argparse entry point
└── stages/
    ├── s0_intake.py     # archive original, load, manifest
    ├── s1_profile.py    # deterministic profile (replaces /audit-xls)
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

The contract layer has 7 tests covering load, schema construction, validation pass/fail, derivations, and column rename. Add tests for your custom derivation patterns as you register them in `contract.apply_derivations()`.

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
