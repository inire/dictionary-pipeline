"""
dictionary-pipeline CLI

Subcommands map 1:1 to pipeline stages so you can run the whole thing
end-to-end OR resume from a specific stage during iteration.

Usage:
    dictionary-pipeline run --input file.xlsx --contract dict.yaml --workdir runs/foo
    dictionary-pipeline intake --input file.xlsx --workdir runs/foo
    dictionary-pipeline profile --workdir runs/foo
    dictionary-pipeline enforce --contract dict.yaml --workdir runs/foo
    dictionary-pipeline derive --contract dict.yaml --workdir runs/foo
    dictionary-pipeline export --contract dict.yaml --workdir runs/foo
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from .logging import TransformationLog
from .stages import s0_intake, s1_profile, s4_enforce, s5_clean, s7_derive, s8_validate, s9_export


def _log(workdir: Path) -> TransformationLog:
    return TransformationLog(workdir / "transformations_log.jsonl")


def cmd_run(args: argparse.Namespace) -> int:
    """End-to-end pipeline run (skips Claude-stages 3 and 6)."""
    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    log = _log(workdir)

    print(f"[s0] intake: {args.input}")
    df, manifest = s0_intake.run(
        args.input,
        workdir,
        sheet_name=args.sheet,
        header_row=args.header_row,
        nrows=args.nrows,
        log=log,
    )
    print(f"     loaded {manifest['row_count']} rows x {manifest['column_count']} cols")
    archive = manifest["archive_path"]

    print("[s1] profiling...")
    s1_profile.run(df, workdir, log=log)

    print(f"[s4] enforcing schema from {args.contract}")
    df, contract = s4_enforce.run(df, args.contract, workdir, log=log)
    print(f"     validated {len(df)} rows against {len(contract.fields)} fields")

    print("[s5] cleaning (rule-based)...")
    df = s5_clean.run(df, contract, log=log)

    print(f"[s7] deriving {len(contract.derived_fields)} columns...")
    df = s7_derive.run(df, contract, log=log)

    print("[s8] validating final output...")
    report = s8_validate.run(df, contract, archive, workdir, sheet_name=args.sheet, log=log)
    diff_cols = list(report.get("original_vs_final_diff", {}).keys())
    print(f"     schema: passed | drift columns: {diff_cols or 'none'}")

    print("[s9] exporting workbook...")
    out_path = s9_export.run(
        df, contract, workdir,
        log_path=workdir / "transformations_log.jsonl",
        output_path=args.output,
        log=log,
    )
    print(f"     wrote {out_path}")
    print()
    print(f"Done. Artifacts in: {workdir}")
    return 0


def cmd_intake(args):
    workdir = Path(args.workdir); workdir.mkdir(parents=True, exist_ok=True)
    df, manifest = s0_intake.run(
        args.input,
        workdir,
        sheet_name=args.sheet,
        header_row=args.header_row,
        nrows=args.nrows,
        log=_log(workdir),
    )
    df.to_parquet(workdir / "stage0_df.parquet")
    print(json.dumps(manifest, indent=2))
    return 0


def cmd_profile(args):
    workdir = Path(args.workdir)
    df = pd.read_parquet(workdir / "stage0_df.parquet")
    summary = s1_profile.run(df, workdir, log=_log(workdir))
    print(json.dumps(summary, indent=2, default=str))
    return 0


def cmd_enforce(args):
    workdir = Path(args.workdir)
    df = pd.read_parquet(workdir / "stage0_df.parquet")
    df, contract = s4_enforce.run(df, args.contract, workdir, log=_log(workdir))
    df.to_parquet(workdir / "stage4_df.parquet")
    print(f"validated {len(df)} rows")
    return 0


def cmd_derive(args):
    from .contract import load_contract
    workdir = Path(args.workdir)
    df = pd.read_parquet(workdir / "stage4_df.parquet")
    contract = load_contract(args.contract)
    df = s7_derive.run(df, contract, log=_log(workdir))
    df.to_parquet(workdir / "stage7_df.parquet")
    print(f"derived columns: {[d.name for d in contract.derived_fields]}")
    return 0


def cmd_bulk_intake(args):
    from .bulk import bulk_intake_run
    report = bulk_intake_run(args.input, args.workdir)
    for g in report["groups"]:
        print(f"  group_{g['group_index']}: {g['file_count']} files, "
              f"{g['total_rows']} rows, columns: {g['columns'][:5]}{'...' if len(g['columns']) > 5 else ''}")
    return 0


def cmd_community_export(args):
    from .community import community_export, UnsafeContractError
    try:
        result = community_export(
            args.contract,
            args.output_dir,
            force=args.force,
        )
    except UnsafeContractError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    print(f"wrote {result['yaml_path']}")
    print(f"wrote {result['md_path']}")
    report = result["scan_report"]
    if not report.is_safe:
        print(f"  scan: {report.summary()} (sanitized before write)")
    return 0


def cmd_export(args):
    from .contract import load_contract
    workdir = Path(args.workdir)
    df = pd.read_parquet(workdir / "stage7_df.parquet")
    contract = load_contract(args.contract)
    out = s9_export.run(
        df, contract, workdir,
        log_path=workdir / "transformations_log.jsonl",
        output_path=args.output,
        log=_log(workdir),
    )
    print(f"wrote {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="dictionary-pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", help="run all non-LLM stages end-to-end")
    pr.add_argument("--input", required=True)
    pr.add_argument("--contract", required=True)
    pr.add_argument("--workdir", required=True)
    pr.add_argument("--sheet", default=0)
    pr.add_argument("--header-row", type=int, default=0, dest="header_row",
                    help="0-indexed row containing the column headers (default 0)")
    pr.add_argument("--nrows", type=int, default=None,
                    help="Maximum number of data rows to read (default: all)")
    pr.add_argument("--output", default=None)
    pr.set_defaults(func=cmd_run)

    pi = sub.add_parser("intake")
    pi.add_argument("--input", required=True)
    pi.add_argument("--workdir", required=True)
    pi.add_argument("--sheet", default=0)
    pi.add_argument("--header-row", type=int, default=0, dest="header_row",
                    help="0-indexed row containing the column headers (default 0)")
    pi.add_argument("--nrows", type=int, default=None,
                    help="Maximum number of data rows to read (default: all)")
    pi.set_defaults(func=cmd_intake)

    pp = sub.add_parser("profile")
    pp.add_argument("--workdir", required=True)
    pp.set_defaults(func=cmd_profile)

    pe = sub.add_parser("enforce")
    pe.add_argument("--workdir", required=True)
    pe.add_argument("--contract", required=True)
    pe.set_defaults(func=cmd_enforce)

    pd_ = sub.add_parser("derive")
    pd_.add_argument("--workdir", required=True)
    pd_.add_argument("--contract", required=True)
    pd_.set_defaults(func=cmd_derive)

    px = sub.add_parser("export")
    px.add_argument("--workdir", required=True)
    px.add_argument("--contract", required=True)
    px.add_argument("--output", default=None)
    px.set_defaults(func=cmd_export)

    pb = sub.add_parser("bulk-intake", help="intake + profile multiple files, grouped by schema")
    pb.add_argument("--input", required=True, nargs="+",
                    help="input files (supports glob patterns via shell expansion)")
    pb.add_argument("--workdir", required=True)
    pb.set_defaults(func=cmd_bulk_intake)

    pc = sub.add_parser("community-export",
                        help="produce a PII-scrubbed community-safe dictionary bundle")
    pc.add_argument("--contract", required=True)
    pc.add_argument("--output-dir", required=True, dest="output_dir")
    pc.add_argument("--force", action="store_true",
                    help="proceed even if pre-sanitization scan finds PII")
    pc.set_defaults(func=cmd_community_export)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
