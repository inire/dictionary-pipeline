# Dictionary Contract Format

The dictionary YAML is the source of truth for everything the pipeline does. This document specifies its structure so that hand-written, LLM-generated, and tool-generated dictionaries are all interchangeable.

## Top-level structure

```yaml
dataset:        # metadata about the whole dataset
fields:         # source columns, one entry each
derived_fields: # computed columns added by Stage 7
```

## `dataset`

```yaml
dataset:
  name: snake_case_identifier         # required, used as Excel sheet name
  description: One-sentence summary   # required
  source: Where it came from          # required
  grain: One row per WHAT?            # required — clarify the rowwise unit
  pii: true|false                     # required
  pii_fields: [list, of, field_names] # required if pii: true
  naming_convention: snake_case       # required, currently always snake_case
  last_updated: "YYYY-MM-DD"          # required
```

The `grain` field exists because grain confusion is the single most common analytical error on commerce/order data. The DoorDash example explicitly says "one row per purchased item (NOT one row per order)" — this prevents anyone (human or LLM) from miscounting orders downstream.

## `fields`

Each entry describes one source column:

```yaml
- name: field_name              # required, snake_case, becomes the pandas column name
  label: Human-readable label   # required, shown in Data Dictionary tab
  type: <type-tag>              # required, see type tags below
  dtype: <pandas-dtype>         # required, see dtype map below
  nullable: true|false          # required
  source_column: Original Name  # required, used by rename_to_contract()

  # Optional, type-dependent:
  allowed_values: [list]        # categoricals only
  min: <number>                 # numerics only
  max: <number>                 # numerics only
  pattern: <regex>              # text/identifier only
  null_tolerance: 0.0-1.0       # if nullable, max acceptable null fraction
  parse_format: <strftime>      # dates only, if non-default

  # Metadata:
  pii: true|false               # default false; flag PII fields
  reliability: reliable|unreliable  # default reliable; flag truncated/lossy data
  review_status: draft|confirmed    # default draft; manual review marker
  notes: |
    Multi-line free text.
    Edge cases, decisions, history.
```

### Type tags

| Tag                  | Meaning                                              |
|----------------------|------------------------------------------------------|
| `categorical`        | Closed value set; use with `allowed_values`          |
| `categorical_open`   | Categorical but new values may appear over time      |
| `date`               | Date or datetime                                     |
| `identifier`         | Unique-ish key (UUID, account number, etc.)          |
| `integer`            | Whole number                                         |
| `decimal`            | Floating point                                       |
| `text`               | Free-form text                                       |
| `bool`               | True/false                                           |

### Dtype map

The `dtype` field is the pandas dtype string. Currently supported:

| dtype             | pandera type |
|-------------------|--------------|
| `string`          | `pa.String`  |
| `Int64`, `int64`  | `pa.Int64`   |
| `float64`         | `pa.Float64` |
| `datetime64[ns]`  | `pa.DateTime`|
| `bool`            | `pa.Bool`    |

Add new mappings to `_DTYPE_MAP` in `contract.py` as needed.

## `derived_fields`

Computed columns added by Stage 7. They have a subset of field properties plus a `transformation` string:

```yaml
- name: unit_price
  label: Estimated per-unit price
  type: decimal
  dtype: float64
  transformation: "product_price / product_quantity"
  notes: Calculated as line total / quantity.
  review_status: confirmed
```

### Derivation patterns

The `transformation` string is parsed by regex in `contract.apply_derivations()`. No `eval()` is used — each pattern family is matched and dispatched safely. Field names must be valid contract field names (post-rename).

**Arithmetic (element-wise on two columns):**

| Pattern | Operation |
|---------|-----------|
| `<field_a> / <field_b>` | Division |
| `<field_a> * <field_b>` | Multiplication |
| `<field_a> + <field_b>` | Addition |
| `<field_a> - <field_b>` | Subtraction |

**Groupby aggregations (broadcast back to every row):**

| Pattern | Operation |
|---------|-----------|
| `groupby(<key>).size()` | Per-group row count |
| `groupby(<key>).<field>.sum()` | Per-group sum |
| `groupby(<key>).<field>.mean()` | Per-group mean |
| `groupby(<key>).<field>.min()` | Per-group min |
| `groupby(<key>).<field>.max()` | Per-group max |

Unrecognized patterns raise `NotImplementedError` with a message listing the supported families. To add a new pattern family, add a compiled regex + handler to `apply_derivations()` in `contract.py`.

## Worked example

See `examples/doordash/dictionary.yaml` for a complete, working dictionary against a real dataset. Notable patterns demonstrated there:

- **Renaming during ingest.** `Payment Methods` (plural in source) becomes `payment_method` (singular). The `source_column` field handles the mapping; the dictionary's `notes` documents why.
- **Resolved edge cases preserved in notes.** The `*` suffix on some `product_type` values is documented as a Fruit & Salad store-specific cosmetic artifact, not a system flag.
- **PII flagged at the field level.** `delivery_address` has `pii: true` and is also listed in `dataset.pii_fields`.
- **Unreliable data flagged.** `product_image` has `reliability: unreliable` because the URLs were truncated during export.
- **Nullable columns with tolerance.** `product_image` has `nullable: true, null_tolerance: 0.15` — acknowledges ~9% observed nulls with headroom.
- **Pattern enforcement on identifiers.** `order_id` requires UUID v4 format via regex; `invoice_url` requires the DoorDash URL format.
- **Single-value columns documented as such.** `currency` (USD only) and `delivery_address` (one home address only) are explicitly noted as having zero analytical variance.

## Versioning

The dictionary is itself a versioned artifact. Recommended convention:

- Keep `dictionary.yaml` in version control alongside the code that consumes it
- Update `dataset.last_updated` whenever the contract changes
- Update `review_status` per field as decisions get confirmed or revisited
- For breaking changes (renamed fields, removed fields, type changes), bump a `dataset.schema_version` field — currently optional but worth adding before the second downstream consumer of the same dictionary appears

## Community sharing fields

These fields control how a dictionary is scrubbed when `dictionary-pipeline community-export` builds a community-safe bundle.

### Field-level

```yaml
- name: account_number
  label: Account number
  type: identifier
  dtype: string
  nullable: false
  shareable: false   # drop this field entirely from community exports
```

```yaml
- name: merchant
  label: Merchant
  type: text
  dtype: string
  nullable: false
  notes: |
    Real-world notes — may reference specific merchants, dates,
    or values from your personal data.
  community_notes: |
    Generic description of the merchant field suitable for sharing.
    Replaces `notes` in community exports.
```

**Rules applied during `community-export`:**
1. Fields with `shareable: false` are dropped.
2. If `community_notes` is set, it replaces `notes`.
3. If only `notes` is set, PII substrings (email, SSN, partial card, phone) are redacted with `[REDACTED_TYPE]`.
4. `allowed_values` containing PII are replaced with a count summary in notes.
5. `source_column` is always cleared (user-specific header text).

### Dataset-level

```yaml
dataset:
  ...
  community_version: "1.0.0"   # optional: version tag for shared artifacts
```

When set, `community_version` is preserved in the exported YAML and shown in the rendered markdown. Use semver and bump when the shared schema changes in ways that matter to consumers.
