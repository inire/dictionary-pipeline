# Community Dictionaries

A shared collection of data dictionaries for common datasets. Each entry lives in its own subdirectory and contains:

- `dictionary.yaml` — the contract (field definitions, types, derivations)
- `README.md` — human-readable overview of the dataset

These dictionaries are a starting point. Drop them next to your own data, adjust field names and types to match your specific export, and use them with `dictionary-pipeline run`.

## Index

_(Add entries here as they land.)_

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to submit a new dictionary.

## Safety

Every file in this directory is scanned for PII before merge by `scripts/scan_community_pii.py`. No real user data — names, emails, account numbers, partial cards, phone numbers — is ever accepted. Use `dictionary-pipeline community-export` to generate a safe bundle from your local workdir before submitting.
