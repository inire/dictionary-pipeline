# New Dataset Prompt Template

Copy this template, fill in the blanks, and paste it into a Claude Code session opened in the dictionary-pipeline repo. Claude will run the full pipeline using the existing stages, pausing for your review at the dictionary checkpoint.

---

## The Prompt

```
I have a new dataset to run through the dictionary-pipeline.

**File:** <full path to the file, e.g. D:/AI/Claude/My Export 2025.csv>
**What it is:** <one sentence — what this data represents and where it came from>
**Grain:** <one row per WHAT? e.g. "one row per purchased item per order">
**PII concerns:** <any columns with personal data, or "none">
**Known quirks:** <anything unusual — footer rows, preamble headers, date formats, ID artifacts, or "none that I know of">
**Workdir:** <where to put run artifacts, OUTSIDE the repo, e.g. D:/AI/Claude/myrun_1>

Run the dictionary-pipeline on this file. Follow the stages in order:

1. **Stage 0+1:** Intake and profile the file. If there are preamble or footer rows,
   use --header-row and --nrows to slice them. Show me the profile output.

2. **Stage 2:** Compose an answer_prompt.md based on the profile, the dataset
   description above, and the stage_prompts.md template. Write it to the workdir.

3. **Stage 3 (manual):** Hand-draft a dictionary.yaml in the workdir using the
   profile output, the answer prompt, and the contract format in
   project_files/dictionary_contract_format.md. Use the Instacart and DoorDash
   examples in examples/ as references for style and completeness.

4. **PAUSE.** Show me the dictionary and your key decisions before proceeding.
   I will review and approve or request changes.

5. **Stages 4-9:** After I approve the dictionary, run the full pipeline:
   enforce → clean → derive → validate → export. Show me the validation
   report and a quick sanity check (run the 3 test questions from the answer prompt
   against the final DataFrame).

References:
- Pipeline spec: project_files/pipeline_spec.md
- Contract format: project_files/dictionary_contract_format.md
- Stage prompts: project_files/stage_prompts.md
- Examples: examples/doordash/, examples/instacart/
```

---

## Filling in the blanks

| Field | What to write | Example |
|---|---|---|
| **File** | Absolute path. Any format the pipeline supports (.csv, .tsv, .xlsx, .xls, etc.) | `D:/AI/Claude/Instacart 2025 Purchased Items.csv` |
| **What it is** | One sentence. Mention the source and time period. | `My Instacart purchase history for calendar year 2025, exported from my account.` |
| **Grain** | The unit of one row. This prevents the most common analytical error. | `one row per purchased item per order` |
| **PII concerns** | Column names or "none". Gets flagged in dictionary + dataset.pii_fields. | `Shipping Address column has my home address` |
| **Known quirks** | Anything you noticed opening the file. Or "none" — the profile will catch most issues. | `Last 2 rows are a totals footer, not data. Order IDs have a leading apostrophe.` |
| **Workdir** | A path OUTSIDE the git repo, so run artifacts don't pollute version control. | `D:/AI/Claude/instacart_run_1` |

## What to expect

The session will pause once after showing you the draft dictionary. This is the highest-leverage review point — five minutes here saves hours later. Look for:

- **Grain statement** — does it match your understanding of what a row is?
- **Categorical allowed_values** — are all valid values listed? Any missing?
- **PII flags** — did it catch everything sensitive?
- **Derived fields** — do the derivations answer your test questions?
- **Nullable/tolerance** — do the null rules match what the profile showed?

After you approve, Stages 4-9 run automatically and produce a 3-tab Excel workbook.
