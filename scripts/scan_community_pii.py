#!/usr/bin/env python3
"""
scan_community_pii.py — gate community dictionary submissions for PII.

Usage:
    python scripts/scan_community_pii.py community/

Scans every .md and .yaml file under the given directory. Reports any
PII findings (email, SSN, credit card, partial card, phone). Exits:
  0 — clean
  1 — PII found (prints findings to stdout)
  2 — usage error

For YAML files, it parses as a contract (if possible) and runs scan_contract;
otherwise it falls back to treating the whole file as free-text. Markdown
files are always scanned as free-text.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the package importable when run from the repo root
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from dictionary_pipeline.community import scan_contract  # noqa: E402
from dictionary_pipeline.contract import load_contract  # noqa: E402
from dictionary_pipeline.pii import find_pii  # noqa: E402


def scan_text_file(path: Path) -> list[tuple[str, str]]:
    """Scan a file's contents as free-text. Returns list of (pii_type, matched)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return find_pii(text)


def scan_yaml_file(path: Path) -> list[tuple[str, str, str]]:
    """
    Scan a YAML file. If it's a valid contract, use scan_contract.
    Otherwise, fall back to free-text scanning.

    Returns list of (location, pii_type, matched).
    """
    try:
        contract = load_contract(path)
    except Exception:
        return [
            (f"{path}:freetext", t, m)
            for t, m in scan_text_file(path)
        ]

    report = scan_contract(contract)
    return [(f"{path}:{f.location}", f.pii_type, f.value) for f in report.findings]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: scan_community_pii.py <directory>", file=sys.stderr)
        return 2

    target = Path(argv[1])
    if not target.exists():
        # Missing directory is treated as clean (nothing to scan)
        return 0

    findings: list[tuple[str, str, str]] = []

    for path in sorted(target.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix in {".yaml", ".yml"}:
            findings.extend(scan_yaml_file(path))
        elif path.suffix == ".md":
            for pii_type, matched in scan_text_file(path):
                findings.append((str(path), pii_type, matched))

    if not findings:
        print(f"[OK] No PII detected under {target}")
        return 0

    print(f"[FAIL] PII detected under {target}:")
    for location, pii_type, matched in findings:
        # Mask the match so we don't echo real PII in CI logs
        preview = matched[:3] + "..." if len(matched) > 6 else "..."
        print(f"  {location} — {pii_type} ({preview})")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
