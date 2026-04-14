"""
Community sharing for dictionary-pipeline.

Produces PII-scrubbed, community-safe dictionary artifacts from an
existing workdir + contract, and provides scanning utilities for
validating contributed dictionaries before they land in the community/
folder.

The key asymmetry: a dictionary *contract* (field definitions, types,
derivations) is highly reusable across users with the same data source,
but the *profile* (top_values, samples) and the free-text *notes* may
contain real user data. This module separates the two:

  1. scan_contract(contract) — find PII in notes, allowed_values, etc.
  2. scan_profile(profile) — find PII in profile top_values
  3. sanitize_contract(contract) — produce a scrubbed contract copy
  4. render_community_markdown(...) — write a safe README.md
  5. community_export(...) — orchestrator that writes the final bundle
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field as dc_field
from pathlib import Path

import yaml

from .contract import Contract, FieldSpec, load_contract
from .pii import classify_pii, find_pii


@dataclass
class SafetyFinding:
    """A single PII detection inside a contract or profile."""
    location: str          # e.g. "field.contact.notes" or "profile.top_values.email"
    pii_type: str          # e.g. "email", "phone"
    value: str             # the matched text


@dataclass
class SafetyReport:
    """Result of scanning a contract or profile for PII."""
    findings: list[SafetyFinding] = dc_field(default_factory=list)

    @property
    def is_safe(self) -> bool:
        return len(self.findings) == 0

    def add(self, location: str, pii_type: str, value: str) -> None:
        self.findings.append(SafetyFinding(location=location, pii_type=pii_type, value=value))

    def summary(self) -> str:
        if self.is_safe:
            return "Safe (no PII detected)"
        by_type: dict[str, int] = {}
        for f in self.findings:
            by_type[f.pii_type] = by_type.get(f.pii_type, 0) + 1
        parts = [f"{t}:{n}" for t, n in sorted(by_type.items())]
        return f"Unsafe ({len(self.findings)} findings — {', '.join(parts)})"


def _scan_field_notes(f: FieldSpec, report: SafetyReport) -> None:
    """Scan notes and community_notes for PII substrings."""
    for label, text in [("notes", f.notes), ("community_notes", f.community_notes)]:
        if not text:
            continue
        for pii_type, matched in find_pii(text):
            report.add(f"field.{f.name}.{label}", pii_type, matched)


def _scan_field_allowed_values(f: FieldSpec, report: SafetyReport) -> None:
    """Scan allowed_values (categorical enumerations) for PII."""
    if not f.allowed_values:
        return
    for val in f.allowed_values:
        if not isinstance(val, str):
            continue
        pii_type = classify_pii(val)
        if pii_type:
            report.add(f"field.{f.name}.allowed_values", pii_type, val)
            continue
        # Also scan for embedded PII (e.g., "contact jane@example.com")
        for pii_type, matched in find_pii(val):
            report.add(f"field.{f.name}.allowed_values", pii_type, matched)


def scan_contract(contract: Contract) -> SafetyReport:
    """
    Scan a contract for PII in free-text and categorical fields.

    Fields with shareable=False are skipped — they will be dropped
    from the community export entirely, so their content doesn't matter.
    """
    report = SafetyReport()
    for f in contract.fields:
        if not f.shareable:
            continue
        _scan_field_notes(f, report)
        _scan_field_allowed_values(f, report)
    return report


def scan_profile(profile: dict) -> SafetyReport:
    """
    Scan a Stage 1 profile dict for PII in top_values entries.

    Uses classify_pii (exact match) plus a person-name heuristic for each
    value. This mirrors what redact_profile() in pii.py scrubs.
    """
    from .pii import _is_person_name  # private helper, safe to reuse

    report = SafetyReport()
    for col_name, col_info in profile.get("columns", {}).items():
        top_values = col_info.get("top_values") or {}
        for val in top_values.keys():
            pii_type = classify_pii(val)
            if pii_type is None and _is_person_name(val):
                pii_type = "person_name"
            if pii_type:
                report.add(f"profile.columns.{col_name}.top_values", pii_type, val)
    return report


def _redact_text(text: str) -> str:
    """Replace PII substrings in free-text with [REDACTED_TYPE] placeholders."""
    if not text:
        return text
    findings = find_pii(text)
    # Longest-first so we don't double-replace substrings
    findings.sort(key=lambda f: len(f[1]), reverse=True)
    out = text
    for pii_type, matched in findings:
        out = out.replace(matched, f"[REDACTED_{pii_type.upper()}]")
    return out


def _has_allowed_values_pii(values: list) -> bool:
    """True if any string value looks like PII."""
    for v in values:
        if not isinstance(v, str):
            continue
        if classify_pii(v):
            return True
        if find_pii(v):
            return True
    return False


def sanitize_contract(contract: Contract) -> Contract:
    """
    Return a deep-copied contract with PII scrubbed for community sharing.

    Rules applied:
      1. Fields with shareable=False are dropped entirely.
      2. If community_notes is set, it REPLACES notes (and community_notes is cleared).
      3. Otherwise, PII substrings in notes are replaced with [REDACTED_TYPE].
      4. Allowed_values containing PII are replaced with a count summary in notes.
      5. source_column is cleared (may contain user-specific header text).
    """
    sanitized = copy.deepcopy(contract)
    sanitized.fields = [f for f in sanitized.fields if f.shareable]

    for f in sanitized.fields:
        # Rule 2/3: notes
        if f.community_notes:
            f.notes = f.community_notes
            f.community_notes = ""
        else:
            f.notes = _redact_text(f.notes)

        # Rule 4: allowed_values PII
        if f.allowed_values and _has_allowed_values_pii(f.allowed_values):
            count = len(f.allowed_values)
            note_prefix = f"{count} unique values (redacted for community safety)."
            f.notes = f"{note_prefix} {f.notes}".strip()
            f.allowed_values = None

        # Rule 5: source_column
        f.source_column = None

    return sanitized


# Default values that should not appear in the dumped YAML
_FIELD_DEFAULTS = {
    "nullable": False,
    "allowed_values": None,
    "min": None,
    "max": None,
    "pattern": None,
    "null_tolerance": 0.0,
    "source_column": None,
    "notes": "",
    "review_status": "draft",
    "pii": False,
    "reliability": "reliable",
    "parse_format": None,
    "shareable": True,
    "community_notes": "",
}

_DERIVED_DEFAULTS = {
    "notes": "",
    "review_status": "draft",
}


def _field_to_dict(f: FieldSpec) -> dict:
    """Convert a FieldSpec to a dict, omitting default values."""
    out = {"name": f.name, "label": f.label, "type": f.type, "dtype": f.dtype}
    for key, default in _FIELD_DEFAULTS.items():
        val = getattr(f, key)
        if val != default:
            out[key] = val
    return out


def _derived_to_dict(d) -> dict:
    out = {
        "name": d.name,
        "label": d.label,
        "type": d.type,
        "dtype": d.dtype,
        "transformation": d.transformation,
    }
    for key, default in _DERIVED_DEFAULTS.items():
        val = getattr(d, key)
        if val != default:
            out[key] = val
    return out


def dump_contract_yaml(contract: Contract) -> str:
    """
    Serialize a Contract to a YAML string suitable for a community dictionary.

    Omits fields with default values and drops the shareable/community_notes
    flags (they're tooling-only, not part of the community artifact).
    """
    dataset = {
        "name": contract.dataset_name,
        "description": contract.description,
        "source": contract.source,
        "grain": contract.grain,
        "pii": contract.pii,
        "pii_fields": contract.pii_fields,
        "naming_convention": contract.naming_convention,
        "last_updated": contract.last_updated,
    }
    if contract.community_version:
        dataset["community_version"] = contract.community_version

    data: dict = {
        "dataset": dataset,
        "fields": [_field_to_dict(f) for f in contract.fields],
    }
    if contract.derived_fields:
        data["derived_fields"] = [_derived_to_dict(d) for d in contract.derived_fields]

    return yaml.safe_dump(data, sort_keys=False, width=100)


def render_community_markdown(contract: Contract) -> str:
    """
    Render a community dictionary as a human-readable markdown file.

    Structure:
      # <dataset_name>
      <description>

      **Source:** ...
      **Grain:** ...
      **Community version:** <version> (if set)
      **Last updated:** ...

      ## Fields
      | name | label | type | nullable | notes |

      ## Derived fields   (only if present)
      | name | transformation | notes |
    """
    lines: list[str] = []
    lines.append(f"# {contract.dataset_name}")
    lines.append("")
    if contract.description:
        lines.append(contract.description)
        lines.append("")

    meta: list[str] = []
    if contract.source:
        meta.append(f"**Source:** {contract.source}")
    if contract.grain:
        meta.append(f"**Grain:** {contract.grain}")
    if contract.community_version:
        meta.append(f"**Community version:** {contract.community_version}")
    if contract.last_updated:
        meta.append(f"**Last updated:** {contract.last_updated}")
    if meta:
        lines.extend(meta)
        lines.append("")

    # Fields table
    lines.append("## Fields")
    lines.append("")
    lines.append("| name | label | type | nullable | notes |")
    lines.append("|------|-------|------|----------|-------|")
    for f in contract.fields:
        notes = (f.notes or "").replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| `{f.name}` | {f.label} | {f.type} | {f.nullable} | {notes} |"
        )
    lines.append("")

    # Derived fields table
    if contract.derived_fields:
        lines.append("## Derived fields")
        lines.append("")
        lines.append("| name | transformation | notes |")
        lines.append("|------|----------------|-------|")
        for d in contract.derived_fields:
            notes = (d.notes or "").replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| `{d.name}` | `{d.transformation}` | {notes} |"
            )
        lines.append("")

    return "\n".join(lines)


class UnsafeContractError(Exception):
    """Raised when a contract fails the pre-export PII scan."""


def community_export(
    contract_path: str | Path,
    output_dir: str | Path,
    *,
    force: bool = False,
) -> dict:
    """
    Produce a community-safe dictionary bundle.

    Reads a contract YAML, scans it for PII, sanitizes it, and writes:
      - {output_dir}/dictionary.yaml
      - {output_dir}/README.md

    Parameters
    ----------
    contract_path : path to the source dictionary.yaml
    output_dir    : directory to write the sanitized bundle into
    force         : if True, proceed even if scan finds PII (after sanitization)

    Raises
    ------
    UnsafeContractError : if scan finds PII and force=False

    Returns
    -------
    dict with keys: yaml_path, md_path, scan_report (SafetyReport)
    """
    contract_path = Path(contract_path)
    output_dir = Path(output_dir)

    contract = load_contract(contract_path)
    report = scan_contract(contract)

    if not report.is_safe and not force:
        raise UnsafeContractError(
            f"Contract {contract_path} failed PII scan: {report.summary()}. "
            f"Either fix the findings, set shareable=false on affected fields, "
            f"provide community_notes overrides, or re-run with force=True "
            f"(sanitization will still be applied)."
        )

    sanitized = sanitize_contract(contract)
    output_dir.mkdir(parents=True, exist_ok=True)

    yaml_path = output_dir / "dictionary.yaml"
    yaml_path.write_text(dump_contract_yaml(sanitized), encoding="utf-8")

    md_path = output_dir / "README.md"
    md_path.write_text(render_community_markdown(sanitized), encoding="utf-8")

    return {
        "yaml_path": yaml_path,
        "md_path": md_path,
        "scan_report": report,
    }
