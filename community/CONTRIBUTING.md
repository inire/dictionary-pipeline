# Contributing a Community Dictionary

Thanks for sharing! These dictionaries help everyone else who's wrangling the same kind of export.

## Quick path (recommended)

1. Run the pipeline on your own dataset until you have a working `dictionary.yaml`.
2. For any field whose notes or allowed_values reference your actual data, either:
   - Add `shareable: false` to drop the field from the community export, OR
   - Add a `community_notes:` block with a generic description that replaces your real notes.
3. Run the community exporter:
   ```bash
   dictionary-pipeline community-export \
     --contract path/to/your_dictionary.yaml \
     --output-dir community/your_dataset_name/
   ```
4. Verify the output locally:
   ```bash
   python scripts/scan_community_pii.py community/your_dataset_name/
   ```
5. Add an entry to `community/README.md`'s Index table.
6. Open a PR.

## What gets stripped automatically

The `community-export` command will:
- Drop fields marked `shareable: false`
- Replace `notes` with `community_notes` if both are set
- Scrub email, SSN, credit card, partial card (e.g. "ending XXXX"), and phone number substrings from notes
- Replace `allowed_values` lists containing PII with a count summary
- Clear `source_column` (original header text can be user-specific)

## What you should still check by hand

- Field labels and descriptions that contain merchant names, store addresses, or household member names
- Anything in `dataset.description` or `dataset.source` that identifies you
- Derivation `notes` fields (these go through verbatim)

If the PII gate rejects your submission, read the finding list, fix the source contract, and re-run `community-export`. The gate script is the same one CI uses, so a local pass means a CI pass.

## Template

See `community/_template/` for a skeleton you can copy and fill in.

## What we won't accept

- Dictionaries derived from someone else's data without permission
- Dictionaries for proprietary datasets where sharing the schema would breach a ToS
- Anything that references a specific person, household, or identifiable account
