# Pipeline Specification

## Design principles

1. **The dictionary is the contract.** Every other stage either produces, enforces, executes, or validates against the dictionary YAML. There is no out-of-band schema, no implicit type assumption, no cleaning rule that isn't traceable to a dictionary field.

2. **Deterministic by default, LLM only where judgment is required.** Two stages call Claude (3 and 6). All others are pure Python. This bounds the failure modes: LLM stages can hallucinate but their output is captured to disk and validated by deterministic stages downstream.

3. **Excel is a boundary, not a workspace.** `.xlsx` enters at Stage 0 and exits at Stage 9. Everything between is pandas DataFrames and parquet checkpoints. No Claude in Excel session is required to run the pipeline — Stage 10 is an optional final visual check, not a dependency.

4. **Drift is detectable.** Stages 4, 8, and the per-stage transformation log create three independent ways to catch unintended changes: schema re-validation, original-vs-final diff, and an append-only audit trail. Anything that mutates data writes to the log.

5. **State is recoverable between stages.** Each stage writes a parquet checkpoint so any stage can be re-run without re-running the whole pipeline. This matters during dictionary iteration — you re-run Stage 4 onward, not Stages 0 and 1.

## Stages

### Stage 0 — Intake & Quarantine

**Tool:** Python (`shutil`, `pandas.read_excel`)
**Input:** Source `.xlsx` file
**Output:** `runs/<workdir>/intake/<filename>__<timestamp>.xlsx`, `intake_manifest.json`, in-memory DataFrame

The original file is copied to an immutable archive before any processing. The archive is the comparison target for Stage 8. The manifest captures raw column names, dtypes, row count, and sheet name — useful both for reference and for Stage 1's profile to compare against.

**Failure modes:** file not found, sheet name wrong, file locked by Excel.

---

### Stage 1 — Automated Profile

**Tool:** Python (custom profiler; optionally ydata-profiling)
**Input:** Stage 0 DataFrame
**Output:** `profile_summary.json`

Replaces Claude in Excel's `/audit-xls` with deterministic, comprehensive output. For each column: dtype, null count and percentage, distinct count, top values, min/max/mean/std for numerics, min/max for dates, length stats for strings.

The JSON is structured for Stage 3's prompt template, not for human reading. (For human reading, swap in ydata-profiling and read the HTML report.)

**Why this beats `/audit-xls`:** identical output every run, no token budget, no risk of the LLM hallucinating distinct counts or skipping columns.

---

### Stage 2 — Answer Prompt Composition

**Tool:** Claude in chat (claude.ai with connectors enabled), manual
**Input:** Org context from Slack/Drive/Teams/Gmail/etc., Stage 1 profile
**Output:** `answer_prompt.md` written manually to the workdir

This stage is deliberately outside the CLI. It's where you decide what the data is *for* — what question it needs to answer, what stakeholders need to see, what edge cases matter. The output is a markdown file with two sections:

1. **The answer prompt itself** — what the cleaned data must support.
2. **Three test questions** — concrete queries the cleaned data must be able to answer. Stage 8 uses these as a validation gate before delivery.

**Why three test questions:** the smallest number that catches both "the answer prompt was incomplete" and "the cleaning corrupted something downstream." One question is too easy to game; five is overhead.

---

### Stage 3 — Draft Dictionary

**Tool:** Claude API (Sonnet or Opus)
**Input:** `profile_summary.json` + `answer_prompt.md` + 50-row sample
**Output:** `dictionary_draft.yaml`

The Claude call here is deliberately bounded:

- Profile JSON instead of raw data (smaller, structured, deterministic)
- 50-row sample only (enough to see formatting and edge cases, not enough to inflate context)
- Single-shot, single-purpose prompt
- YAML output, not prose — the contract format matches `dictionary_contract_format.md`

After Stage 3 produces the draft, **manual review is expected** before proceeding. The dictionary is the highest-leverage artifact in the pipeline; spending five minutes reviewing it saves hours of downstream debugging.

**Stub status:** `_call_claude()` in `s3_dictionary.py` raises `NotImplementedError` until you wire your preferred Claude entry point. Reference implementations are in the docstring.

---

### Stage 4 — Schema Enforcement

**Tool:** pandera
**Input:** Stage 0 DataFrame + dictionary YAML
**Output:** Validated/coerced DataFrame, optionally `schema_violations.csv`

The dictionary is parsed into a `pa.DataFrameSchema`. Each field becomes a `pa.Column` with type, nullable flag, and any applicable checks (`isin`, `ge`, `le`, `str_matches`). The `coerce=True` flag handles type conversion — strings to dates, strings to ints, etc. — using pandera's deterministic coercion rules.

The `strict="filter"` setting drops columns not in the contract. This is intentional: the contract is the source of truth for what fields exist. If a source column wasn't declared in the dictionary, it gets dropped here, which forces dictionary updates rather than silent column drift.

**Failure mode:** any row failing any check raises `pa.errors.SchemaErrors`. Failure cases are written to `schema_violations.csv` and the pipeline halts. Fix the data or the dictionary, then re-run from Stage 4.

---

### Stage 5 — Rule-Based Cleaning

**Tool:** Python
**Input:** Stage 4 validated DataFrame + Contract
**Output:** Cleaned DataFrame, transformation log entries

Deterministic cleaning only. Currently implements:

- Whitespace stripping on text/categorical/identifier columns (null-preserving — explicit `.where()` mask to avoid the NaN→"nan" string corruption bug we found during initial testing)
- Exact-match duplicate row removal

Extend with rapidfuzz, dateutil, etc. as datasets demand. Anything requiring judgment goes to Stage 6, not here.

**Anti-pattern to avoid:** putting rules in Stage 5 that the dictionary doesn't sanction. If you find yourself writing "all values matching X get changed to Y," that rule should be expressed in the dictionary's `notes` field (or a future `cleaning_rules` field) and read from there, not hardcoded.

---

### Stage 6 — Judgment Cleaning

**Tool:** Claude API
**Input:** Single column's distinct values + the dictionary entry for that column
**Output:** Original-to-canonical value mapping, applied to the DataFrame

Only invoked when Stage 5 leaves cases the rules can't decide. The classic example from the DoorDash dataset: `product_type` has twelve syntactic variants of "kids menu" and sixteen of "beverages." Rules can collapse `Kids` / `Kid's` / `Kids'` syntactically, but deciding whether "Family & Kids Meals" belongs in the same bucket is judgment.

The Claude call sees only:

- The field name and label
- The dictionary's `notes` for that field
- The list of distinct values with counts

It does **not** see the rest of the DataFrame, other columns, or any business context. This minimizes context and the surface area for drift.

**Stub status:** `_call_claude()` in `s6_judgment.py` raises `NotImplementedError`. Same wiring task as Stage 3.

---

### Stage 7 — Derived Columns

**Tool:** Python (`contract.apply_derivations`)
**Input:** Cleaned DataFrame + Contract
**Output:** DataFrame with derived columns appended

The `derived_fields` section of the dictionary is the spec; this stage executes it. `apply_derivations()` deliberately uses pattern matching, not eval, for safety. Each new derivation pattern needs an explicit `elif` branch.

For the DoorDash example: `unit_price` (price/quantity), `order_item_count` (groupby size), `order_total` (groupby sum) — all defined in the dictionary, all executed mechanically.

---

### Stage 8 — Validation

**Tool:** Python + pandera
**Input:** Final DataFrame + Contract + intake archive path
**Output:** `validation_report.json`

Three checks:

1. **Re-validate against the contract.** Catches any drift introduced by stages 5/6/7.
2. **Diff against the intake archive.** Per-column, position-aligned, null-aware. Surfaces unexpected value changes — including the kind that the original Stage 5 bug (NaN→"nan") would have introduced.
3. **(Manual)** Run the answer prompt's three test questions against the data. Not yet automated; future work would parse the test questions from `answer_prompt.md` and execute them.

If any check fails, the pipeline halts before Stage 9. No bad data reaches the deliverable.

---

### Stage 9 — Export to Excel

**Tool:** openpyxl
**Input:** Final DataFrame + Contract + transformation log
**Output:** Three-tab `.xlsx` workbook

- **Sheet 1:** the cleaned data (sheet named after `dataset.name`)
- **Sheet 2:** Data Dictionary, rendered from the contract — all 14 contract fields plus 3 derived fields, with labels, types, dtypes, allowed values, ranges, source columns, PII flags, reliability, review status, notes, and transformations
- **Sheet 3:** Automated Changes, rendered from `transformations_log.jsonl`

The dictionary tab in the output workbook matches what Stage 4 enforced. Stakeholders see the same contract the code ran against.

---

### Stage 10 — Final Compare (manual)

**Tool:** Claude in Excel, single short session
**Input:** Stage 0 archive + Stage 9 output, opened side-by-side
**Output:** Spot-check report or sign-off

The only Claude in Excel touch in the pipeline. Single focused session, fresh context, bounded scope: "compare these workbooks and flag any concerning differences in values, types, or structure. Reference the Data Dictionary tab in the new file for what each column should contain."

The drift cost can't accumulate because there's nothing to accumulate against — one prompt, one comparison, done.

## Error handling philosophy

- **Halt on validation failure.** Don't try to repair. Fix the data or the dictionary, then re-run.
- **Log every mutation.** The transformation log is the audit trail; if it isn't in the log, it didn't happen.
- **Checkpoint between stages.** Parquet files between stages mean iteration is cheap.
- **Make drift visible.** Stage 8's diff report is the canary. False positives there are bugs to fix in Stage 8, not warnings to ignore.
