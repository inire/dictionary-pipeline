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

from dataclasses import dataclass, field as dc_field

from .contract import Contract, FieldSpec
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
