# Post-pipeline workflow guide

This guide covers what to do before, during, and after running `dictionary-pipeline`. It assumes you have read the [README](../README.md) and already have a dictionary YAML started — this document goes deeper on how to actually use the pipeline in practice.

---

## 1. Pre-run checklist

Before invoking the pipeline, confirm three things are ready.

### Input file

| Check | Notes |
|-------|-------|
| File is CSV, TSV, or Excel (`.xlsx`, `.xls`, `.xlsm`) | Other formats are not supported |
| File is not open in Excel | Excel write-locks the file; the pipeline will fail to copy it |
| Header row is at row 0 | If your export has preamble rows, use `--header <n>` to point to the correct row |
| File is the *original export*, not a version you edited | The pipeline archives this file as-is — start clean |

### Dictionary YAML

| Check | Notes |
|-------|-------|
| Every source column has a `fields` entry with a `source_column` value | Missing source columns silently become unmapped |
| Every `categorical` field has `allowed_values` set | Without it, Stage 4 skips the closed-set check |
| `dataset.grain` is filled in and accurate | This is the single line that prevents downstream LLM miscounting |
| `dataset.pii` and `pii_fields` are correct | Affects Stage 1 redaction and community export eligibility |
| `review_status` on each field is set honestly (`draft` vs `confirmed`) | Draft fields pass validation but flag your own intent |

If you do not yet have a dictionary, run Stage 1 first (see below), then use the profile output in Stage 2 (manual) to write one, then continue from Stage 3/4.

### Python environment

```bash
source .venv/bin/activate
python -m pip show dictionary-pipeline   # confirm it's installed
```

If LLM stages (3 and 6) are wired, also confirm:

```bash
echo $ANTHROPIC_API_KEY
```

---

## 2. Running the pipeline

### Full run

```bash
dictionary-pipeline run \
  --input  path/to/your_data.xlsx \
  --contract path/to/dictionary.yaml \
  --workdir runs/my_run \
  --sheet "Sheet1"
```

`--sheet` only matters for Excel inputs; omit for CSV/TSV.

### Common flags

| Flag | Effect |
|------|--------|
| `--redact-pii` | Replaces `top_values` entries in `profile_summary.json` with `[REDACTED_TYPE]` placeholders. Use when the profile will leave your machine (community export, sharing with collaborators). |
| `--header <n>` | Zero-based row index of the column header row. Default `0`. |
| `--nrows <n>` | Load only the first N rows. Useful for testing your contract against a sample before committing to a full run. |

### Running individual stages

The pipeline checkpoints to parquet between stages, so you can re-run a single stage without replaying everything:

```bash
dictionary-pipeline intake   --input file.xlsx --workdir runs/foo
dictionary-pipeline profile  --workdir runs/foo [--redact-pii]
dictionary-pipeline enforce  --workdir runs/foo --contract dict.yaml
dictionary-pipeline derive   --workdir runs/foo --contract dict.yaml
dictionary-pipeline export   --workdir runs/foo --contract dict.yaml
```

The typical iteration loop is: fix the YAML → re-run `enforce` → re-run `export`. You rarely need to redo `intake` or `profile` unless the source file itself changed.

---

## 3. Understanding output

After a successful run, `--workdir` contains:

```
runs/my_run/
├── intake/
│   └── your_data__20240415T143022Z.xlsx   # immutable archive of the original
├── intake_manifest.json                    # how the file was read
├── profile_summary.json                    # Stage 1 column statistics
├── validation_report.json                  # Stage 8 schema + diff results
├── transformation_log.jsonl                # every mutation, timestamped
└── your_data.xlsx                          # the delivered workbook
```

### `intake/your_data__<timestamp>.<ext>`

A verbatim copy of your source file, written before any processing. Never modified. Stage 8 reads this to compute the diff between what came in and what went out.

### `intake_manifest.json`

Records how the file was read: `reader`, `reader_params` (encoding, header row, sheet name), row and column count, and the column list with inferred dtypes. Useful for diagnosing why pandas saw different columns than you expected.

```json
{
  "source_path": "/abs/path/to/your_data.xlsx",
  "archive_path": "/abs/path/to/runs/my_run/intake/your_data__20240415T143022Z.xlsx",
  "ingested_at": "20240415T143022Z",
  "reader": "pandas.read_excel",
  "reader_params": {"sheet_name": "Sheet1", "header": 0},
  "row_count": 532,
  "column_count": 13,
  "columns": ["Order ID", "Product Name", ...],
  "dtypes": {"Order ID": "object", ...}
}
```

### `profile_summary.json`

Per-column statistics: null count and percentage, distinct count, top 5 values by frequency, and for numeric/date columns, min/max/mean/std. For string columns, min and max character lengths.

This is the document you hand to Claude in Stage 2 (manual) when drafting the initial dictionary. It answers "what values actually appear in this column?" without you having to open the file.

### `validation_report.json`

Written by Stage 8. Contains two keys:

- `schema_revalidation` — `"passed"` if the final DataFrame satisfies the pandera schema built from your contract. If this is anything other than `"passed"`, the pipeline halts and no Excel file is written.
- `original_vs_final_diff` — a per-column diff between the intake archive and the final output. Only columns that actually changed appear here.

### Delivered workbook (`your_data.xlsx`)

Three tabs:

| Tab | Contents |
|-----|----------|
| **your_data** | The cleaned, derived, validated data |
| **Data Dictionary** | Human-readable rendering of your `dictionary.yaml` |
| **Automated Changes** | Every transformation the pipeline applied, with stage and timestamp |

---

## 4. Interpreting the validation report

Open `validation_report.json` after every run. Two things to check:

### `schema_revalidation`

If `"passed"`: all columns matched their declared types, null constraints were satisfied, and closed categoricals contained only allowed values.

If the pipeline raised a `SchemaError` before even writing this file, the pandera output will be in your terminal. The error message names the column and the failing constraint — this is usually one of:

- Type mismatch (e.g., a column declared `Int64` has stray text values)
- Null violation (a non-nullable column has nulls)
- Categorical violation (a value appeared that is not in `allowed_values`)

### `original_vs_final_diff`

```json
{
  "schema_revalidation": "passed",
  "original_vs_final_diff": {
    "payment_method": {"mismatches": 14},
    "product_quantity": {"mismatches": 3}
  }
}
```

Each key is a column where at least one row changed between intake and output. The `mismatches` count is the number of rows that differ. This is informational — mismatches are expected when cleaning ran (Stage 5/6). What you are looking for is:

- **Columns you did not expect to change** — if `order_id` shows mismatches, something went wrong.
- **Mismatch counts much larger than expected** — 14 cleaned values in `payment_method` is plausible; 14,000 in a 15,000-row dataset suggests a bad transformation.
- **`row_count_changed`** — appears when intake and final have different row counts. This should not happen in the current pipeline (no deduplication or filtering stage). If you see it, a stage is dropping rows unexpectedly.

---

## 5. Common issues and troubleshooting

### Schema failure at Stage 4

**Symptom:** `SchemaError: column 'X' dtype mismatch` or `column 'X' not in DataFrame`.

**Causes and fixes:**

| Cause | Fix |
|-------|-----|
| `source_column` in YAML does not match the actual column header | Open `intake_manifest.json`, copy the exact column name from `columns`, paste into `source_column` |
| Column declared `Int64` but contains decimal values | Change `dtype` to `float64` or add a clean rule in Stage 5 to truncate |
| Column declared `not nullable` but has nulls | Either set `nullable: true` with a `null_tolerance`, or add a fill rule in Stage 5 |
| Categorical value appeared that is not in `allowed_values` | Add it to `allowed_values`, or if it should be cleaned, add a Stage 5 rule |

### Encoding errors on CSV intake

**Symptom:** `UnicodeDecodeError` or garbage characters in column values.

The pipeline auto-detects encoding via `chardet`. If detection fails:

1. Check `intake_manifest.json` → `reader_params.encoding` to see what was detected.
2. Run `file -i your_data.csv` to get the OS-level encoding guess.
3. Force the encoding by pre-converting the file: `iconv -f windows-1252 -t utf-8 input.csv > input_utf8.csv`

### Missing columns after rename

**Symptom:** Stage 4 or 5 fails with `KeyError` on a column name.

The rename happens during Stage 4 (`enforce`). If a `source_column` value does not match any column in the loaded DataFrame, that field is silently skipped. Check `intake_manifest.json` → `columns` against your YAML's `source_column` values — they must match exactly, including spaces and capitalisation.

### Derived column errors at Stage 7

**Symptom:** `NotImplementedError: unsupported transformation pattern`.

The `transformation` string in `derived_fields` must match one of the supported pattern families (arithmetic or groupby). Copy the exact pattern syntax from [`dictionary_contract_format.md`](../project_files/dictionary_contract_format.md). If your derivation does not fit a supported pattern, register a new one in `contract.apply_derivations()`.

### LLM stages not running (stages 3 and 6)

Stages 3 and 6 are stubs. `_call_claude()` in `s3_dictionary.py` and `s6_judgment.py` raises `NotImplementedError` until you wire in a Claude entry point. See the docstrings in those files for reference implementations. Until then, the pipeline runs stages 0, 1, 4, 5, 7, 8, 9.

---

## 6. Post-pipeline review (Stage 10 — manual)

Stage 10 is the only manual stage after pipeline completion. Open the delivered `.xlsx` in Excel (or Numbers/Sheets) with Claude in context.

### What to check

**Data Dictionary tab:**

- Does every field's `label` and `notes` accurately describe what you actually see in the data?
- Are any `review_status: draft` fields ready to be confirmed?
- Do `grain`, `pii`, and `pii_fields` still look right after seeing the cleaned output?

**Automated Changes tab:**

- Skim for unexpected transformations. The log is append-only and includes stage name, event type, and row counts. A `rows_affected` number that is much higher than expected signals a rule fired more broadly than intended.

**Data tab:**

- Spot-check a sample of rows where `validation_report.json` reported diffs. Confirm the cleaned value is correct, not just different.
- Verify that derived columns compute correctly on a few representative rows. Compute the expected value manually and compare.

### What Claude is doing in Stage 10

Stage 10 is a short, focused Claude session — not open-ended analysis. The narrow question is: **"Does this cleaned output match what the source was trying to say?"** Keep the session short and specific. The deterministic stages already handled the mechanical work; Claude here is doing a final sanity check on values that required judgment calls in Stage 6.

---

## 7. Re-running after fixes

The standard iteration loop after a validation failure or post-review correction:

```
1. Edit dictionary.yaml
2. dictionary-pipeline enforce --workdir runs/my_run --contract dictionary.yaml
3. dictionary-pipeline export  --workdir runs/my_run --contract dictionary.yaml
4. Recheck validation_report.json
```

You do not need to re-run `intake` or `profile` unless the *source file* changed. The archived copy is still there.

If Stage 5 (rule-based clean) needs a new rule:

```
1. Edit stages/s5_clean.py
2. dictionary-pipeline enforce --workdir runs/my_run --contract dictionary.yaml
3. dictionary-pipeline derive  --workdir runs/my_run --contract dictionary.yaml
4. dictionary-pipeline export  --workdir runs/my_run --contract dictionary.yaml
```

If you need to change the *source file* itself (e.g., you got an updated export):

```
1. dictionary-pipeline intake --input new_file.xlsx --workdir runs/my_run_v2
2. Run the full pipeline against the new workdir
```

Do not overwrite an existing workdir with a new source file — the archived intake copy is the paper trail.

### Updating `dataset.last_updated`

After any dictionary change that affects schema, derivations, or interpretation, update `dataset.last_updated` in your YAML to today's date. This is a lightweight changelog that costs nothing and matters when you are comparing two runs months apart.

---

## 8. Community sharing

Once your dictionary is stable and validated, you can contribute it to the `community/` folder so others working with the same dataset format can start with a tested contract rather than building from scratch.

```bash
dictionary-pipeline community-export \
  --contract path/to/your_dictionary.yaml \
  --output-dir community/your_dataset/
```

This command:

1. Drops any fields with `shareable: false`
2. Replaces `notes` with `community_notes` where set
3. Redacts PII substrings in free-text fields
4. Clears all `source_column` values (these are user-specific header names)
5. Runs a PII scan — if any unsafe content is detected, the export fails unless you pass `--force`

Even with `--force`, all sanitization still runs. The flag only bypasses the blocking check, not the redaction.

See [`community/CONTRIBUTING.md`](../community/CONTRIBUTING.md) for the full submission guide including what goes in the accompanying `README.md`.
