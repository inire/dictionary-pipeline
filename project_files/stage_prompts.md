# Stage Prompts

The four prompts that drive the LLM-in-the-loop stages. Stages 3 and 6 are also embedded as `PROMPT_TEMPLATE` constants in their respective stage modules — keep both copies in sync if you edit one.

---

## Stage 2 — Answer Prompt Composition

**Where it runs:** Claude in chat (claude.ai), with connectors enabled (Slack, Drive, Gmail, Notion, etc.). Manual stage, not automated.

**Goal:** Decide what the cleaned data needs to support, and produce three concrete test questions Stage 8 will use as a validation gate.

**Prompt template:**

```
I'm preparing a dataset for analysis. The dataset is: <one-sentence description>.

Help me compose an answer prompt for the data preparation pipeline. I need to end up with:

1. A clear statement of what the cleaned dataset must support — what question(s) it
   needs to answer, what stakeholders need to see, what edge cases matter.
2. Three concrete test questions that the cleaned data must be able to answer.
   These will be used as a validation gate before the data is delivered. Make them
   specific enough that "yes/no, the data answers this" is unambiguous.

Context to gather first (use connectors as needed):
- Any prior analyses or reports related to this dataset
- The original requester's stated need
- Any known downstream consumers and what they care about
- Any compliance/PII concerns

Output format:

# Answer Prompt: <dataset name>

## What this data must support

<2-4 sentences>

## Test questions

1. <specific question>
2. <specific question>
3. <specific question>

## Notes

<any context about edge cases, gotchas, or known issues>
```

**Save the output** as `runs/<workdir>/answer_prompt.md`. Stage 3 reads it directly.

---

## Stage 3 — Draft Dictionary

**Where it runs:** Claude API call from `s3_dictionary.py`. Currently a stub — wire your preferred entry point to `_call_claude()`.

**Goal:** Produce a complete YAML dictionary covering every column in the profile, with types, edge cases, and PII flags.

**Prompt template** (also in `s3_dictionary.py` as `PROMPT_TEMPLATE`):

```
You are drafting a data dictionary for a dataset.

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
```

**Tuning notes:**

- Opus 4.6 is recommended for this stage. Sonnet works for simple datasets but Opus catches more edge cases on complex ones.
- The 50-row sample is a token-budget compromise. For datasets where the first 50 rows aren't representative (sorted data, time-series with regime changes), consider sampling randomly.
- If the LLM produces commentary alongside the YAML, post-process to strip everything before the first `dataset:` line and after the last YAML-shaped block.
- After generation, **always manually review** before running Stage 4. The dictionary is the highest-leverage artifact in the pipeline; five minutes of review saves hours of downstream debugging.

---

## Stage 6 — Judgment Cleaning

**Where it runs:** Claude API call from `s6_judgment.py`. Currently a stub.

**Goal:** Normalize ambiguous values in a single column where syntactic rules can't decide.

**Prompt template** (also in `s6_judgment.py` as `PROMPT_TEMPLATE`):

```
You are normalizing values in a single column.

COLUMN: {field_name}
COLUMN PURPOSE: {field_label}
NOTES FROM DICTIONARY: {field_notes}

DISTINCT VALUES TO NORMALIZE (with counts):
{value_counts}

Return a JSON object mapping each original value to a normalized canonical value.
Group syntactic variants together (e.g., "Kids Menu" / "Kid's Menu" / "Kids' Menu").
Do NOT merge values that represent semantically distinct things even if similar.

Return ONLY the JSON object, no preamble.
```

**Tuning notes:**

- Pass the dictionary's `notes` field for the column. The notes often contain the resolved-edge-case context the LLM needs to make good merge decisions (e.g., "the * suffix is cosmetic, not a flag").
- For columns with hundreds of distinct values, consider chunking — pass the top 100 by count, get a mapping, then pass the next 100 with the previous mapping as context.
- Output validation matters here: if Claude returns a mapping that includes keys not in the original column, log it but don't fail. If it returns a mapping missing keys, those values pass through unchanged.

---

## Stage 10 — Final Compare

**Where it runs:** Claude in Excel sidebar. Manual stage. Single short session.

**Goal:** Visual sanity check between the original and final workbooks. The only Claude in Excel touch in the entire pipeline.

**Setup:**

1. Open the intake archive (`runs/<workdir>/intake/<filename>__<timestamp>.xlsx`)
2. Open the final output (`runs/<workdir>/<dataset_name>.xlsx`)
3. Open Claude in Excel sidebar in the *final* workbook
4. Send the prompt below

**Prompt:**

```
I have the original source workbook open in another window and this final processed
workbook open here. The processed workbook has three tabs: the cleaned data, a Data
Dictionary tab describing every field, and an Automated Changes tab logging every
transformation.

Please:

1. Read the Data Dictionary tab and tell me what this dataset is, what each field
   means, and what derivations were added.

2. Read the Automated Changes tab and summarize what the pipeline did. Flag anything
   that surprises you.

3. Spot-check a random sample of 5 rows in the cleaned data against what the
   dictionary says they should look like. Flag any mismatches.

4. Confirm whether the derived columns (unit_price, order_item_count, order_total
   for the DoorDash example, or whatever applies here) are computed correctly on
   those 5 rows.

Do NOT modify the workbook. This is a read-only sanity check.
```

**Why this prompt works:**

- It treats the dictionary tab as the source of truth, not the LLM's prior assumptions
- It bounds the work to 5 rows so the session stays short and context stays clean
- It explicitly forbids modification — Stage 10 is verification, not cleanup
- The "spot-check + derivation check" combo catches both data corruption and computation bugs
- It surfaces surprises in the audit log, which is the cheapest way to catch a Stage 5 or Stage 6 bug that Stage 8 missed

**If Stage 10 finds issues:** do not fix them in the sidebar. Note them, close the session, fix the dictionary or stage code, re-run from the appropriate stage. The whole point is that the pipeline is reproducible.
