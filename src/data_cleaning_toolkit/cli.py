"""Command-line interface: ``cleaner`` (and ``python -m data_cleaning_toolkit``).

Exit codes
----------
0  success
1  runtime error (unreadable input, failed run, ...)
2  usage error (bad arguments, invalid configuration)
4  validation command found violations (``cleaner validate`` only)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from typing import Any

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_VIOLATIONS = 4


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input", "-i", required=True, help="input CSV or XLSX file")
    parser.add_argument("--config", "-c", required=True, help="cleaning config (.yaml/.yml/.json)")
    parser.add_argument("--sheet", default=None, help="Excel worksheet name or 0-based index")
    parser.add_argument("--verbose", "-v", action="store_true", help="show detailed rule output")
    parser.add_argument("--quiet", "-q", action="store_true", help="suppress non-error output")


def _resolve_sheet(value: str | None) -> str | int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return value


def _load_config(path: str):
    from .config.schema import load_config_file

    return load_config_file(path)


def _print_outcome_line(outcome: dict[str, Any], verbose: bool) -> None:
    status = outcome["status"]
    marker = {
        "applied": "[changed]",
        "no_changes": "[ok     ]",
        "flagged_only": "[flagged]",
        "error": "[ERROR  ]",
    }.get(status, "[???????]")
    line = (
        f"  {marker} {outcome['rule_id']:<24} {outcome['rule_type']:<22} "
        f"cells={outcome['cells_changed']:<6} removed={outcome['rows_removed']:<5} "
        f"flags={outcome['flags']}"
    )
    print(line)
    for w in outcome.get("warnings", []) or []:
        print(f"           warning: {w}")
    if outcome.get("error"):
        print(f"           error: {outcome['error']}")
    if verbose and outcome.get("examples"):
        for ex in outcome["examples"][:5]:
            print(
                f"           row {ex['row']} [{ex['column']}]: "
                f"{ex['before']!r} -> {ex['after']!r} ({ex['reason']})"
            )


def cmd_profile(args: argparse.Namespace) -> int:
    from .core.pipeline import profile_file

    config = _load_config(args.config)
    ds, profile = profile_file(args.input, config, sheet=_resolve_sheet(args.sheet))
    if not args.quiet:
        m = ds.metadata
        print(f"file:        {m.filename}  ({m.fmt.upper()}"
              + (f", sheet {m.sheet}" if m.sheet else "")
              + f", {m.size_bytes / 1024:.1f} KB)")
        print(f"sha256:      {m.sha256}")
        if m.encoding:
            print(f"encoding:    {m.encoding}" + (f"  delimiter: {m.delimiter!r}" if m.delimiter else ""))
        for w in [*m.import_warnings, *m.workbook_warnings]:
            print(f"note:        {w}")
        p = profile.to_dict()
        print(f"shape:       {p['rows']:,} rows x {p['column_count']:,} columns")
        print(f"missing:     {p['total_missing']:,} cells ({p['missing_pct']:.1f}%)")
        print(f"duplicates:  {p['duplicate_rows']:,} rows in duplicate groups")
        print(f"quality:     {p['quality_score']:.1f}/100 "
              f"(completeness {p['score_components']['completeness']:.0f}, "
              f"uniqueness {p['score_components']['uniqueness']:.0f}, "
              f"consistency {p['score_components']['consistency']:.0f})")
        if p["findings"]:
            print("findings:")
            for f in p["findings"]:
                print(f"  [{f['severity']:<6}] {f['area']:<11} {f['message']}")
        if args.verbose:
            print("\nper-column:")
            for c in p["columns"]:
                notes = "; ".join(filter(None, [
                    f"missing {c['missing_pct']}%" if c["missing"] else "",
                    f"{c['unique']} unique",
                    *([f"mixed types: {', '.join(c['mixed_types'])}"] if c["mixed_types"] else []),
                    *([f"units: {', '.join(c['distinct_units'])}"] if len(c["distinct_units"]) > 1 else ""),
                ]))
                print(f"  {c['name']:<22} {c['inferred_kind']:<9} {notes}")
    if args.json:
        ds2, prof2 = (ds, profile)
        payload = {"source": ds2.metadata.to_dict(), "profile": prof2.to_dict()}
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False, default=str)
        if not args.quiet:
            print(f"\nJSON profile written to {args.json}")
    return EXIT_OK


def cmd_preview(args: argparse.Namespace) -> int:
    from .core.pipeline import process_file

    config = _load_config(args.config)
    summary = process_file(
        args.input, config, output_dir=args.output or "cleaned",
        sheet=_resolve_sheet(args.sheet), dry_run=True,
    )
    if not args.quiet:
        s = summary["summary"]
        print("DRY RUN - no files will be written")
        print(f"dataset:     {summary['dataset']}")
        print(f"rows:        {s['rows_in']:,} -> {s['rows_out']:,} "
              f"({s['rows_removed']:,} would be removed)")
        print(f"cells:       {s['cells_changed']:,} would change")
        print(f"flags:       {s['flags']:,} value(s) flagged for review")
        print("\nplanned rules:")
        for o in summary["outcomes"]:
            _print_outcome_line(o, args.verbose)
        if args.verbose and summary.get("profile"):
            for f in summary["profile"]["findings"]:
                print(f"  [{f['severity']:<6}] {f['message']}")
    return EXIT_OK


def cmd_clean(args: argparse.Namespace) -> int:
    from .core.pipeline import process_file

    config = _load_config(args.config)
    output_dir = args.output or config.export.directory
    if not args.dry_run and not args.yes and sys.stdin.isatty() and not args.quiet:
        reply = input(
            f"Apply cleaning and write outputs to '{output_dir}'? [y/N] "
        )
        if reply.strip().lower() not in {"y", "yes"}:
            print("aborted - nothing was written")
            return EXIT_OK
    summary = process_file(
        args.input, config, output_dir=output_dir,
        sheet=_resolve_sheet(args.sheet), dry_run=bool(args.dry_run),
        allow_overwrite=bool(args.force_overwrite),
    )
    if summary.get("dry_run"):
        if not args.quiet:
            s = summary["summary"]
            print("DRY RUN complete - nothing was written")
            print(f"rows: {s['rows_in']:,} -> {s['rows_out']:,}; "
                  f"{s['cells_changed']:,} cells would change; "
                  f"{s['flags']:,} flags. Run without --dry-run to apply.")
        return EXIT_OK
    if not summary.get("ok"):
        if not args.quiet:
            print(f"ERROR: cleaning failed: {summary.get('error')}", file=sys.stderr)
            for o in summary["outcomes"]:
                if o["status"] == "error":
                    print(f"  failed rule: {o['rule_id']}: {o.get('error')}", file=sys.stderr)
        return EXIT_ERROR
    if not args.quiet:
        s = summary["summary"]
        print(f"cleaned:     {summary['dataset']}")
        print(f"rows:        {s['rows_in']:,} -> {s['rows_out']:,} ({s['rows_removed']:,} removed)")
        print(f"cells:       {s['cells_changed']:,} changed; {s['flags']:,} flagged for review")
        if args.verbose:
            for o in summary["outcomes"]:
                _print_outcome_line(o, verbose=True)
        print(f"output:      {summary['output']}")
        print(f"run folder:  {summary['run_dir']}  (report.html, audit/, manifest.json)")
    return EXIT_OK


def cmd_validate(args: argparse.Namespace) -> int:
    from .core.pipeline import validation_report

    config = _load_config(args.config)
    report = validation_report(args.input, config, sheet=_resolve_sheet(args.sheet))
    if not args.quiet:
        p = report["profile"]
        print(f"dataset:            {report['dataset']}")
        print(f"shape:              {p['rows']:,} x {p['column_count']:,}")
        print(f"quality score:      {p['quality_score']:.1f}/100")
        print(f"duplicate rows:     {p['duplicate_rows']:,}")
        print(f"missing cells:      {p['total_missing']:,}")
        print(f"rule violations:    {report['validation_violations']:,} flagged")
        if args.verbose:
            for o in report["outcomes"]:
                _print_outcome_line(o, verbose=True)
        verdict = (
            "PASS - no rule violations found"
            if report["validation_violations"] == 0
            else f"FAIL - {report['validation_violations']} violation(s) detected"
        )
        print(f"validation:         {verdict}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False, default=str)
        if not args.quiet:
            print(f"\nJSON report written to {args.json}")
    return EXIT_OK if report["validation_violations"] == 0 else EXIT_VIOLATIONS


def cmd_batch(args: argparse.Namespace) -> int:
    from .core.pipeline import process_file
    from .readers.base import SUPPORTED_EXTENSIONS, check_extension

    config = _load_config(args.config)
    input_dir = args.input
    if not os.path.isdir(input_dir):
        print(f"ERROR: --input must be a directory for batch: {input_dir}", file=sys.stderr)
        return EXIT_USAGE
    files = sorted(
        os.path.join(input_dir, f)
        for f in os.listdir(input_dir)
        if os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS
    )
    if not files:
        print(f"no supported files ({', '.join(sorted(SUPPORTED_EXTENSIONS))}) in {input_dir}")
        return EXIT_OK
    failures = 0
    for i, path in enumerate(files, start=1):
        try:
            check_extension(path)
        except Exception as exc:
            print(f"[{i}/{len(files)}] SKIP {os.path.basename(path)}: {exc}")
            continue
        if not args.quiet:
            print(f"[{i}/{len(files)}] {os.path.basename(path)}")
        try:
            summary = process_file(
                path, config, output_dir=args.output or config.export.directory,
                sheet=_resolve_sheet(args.sheet),
                dry_run=bool(args.dry_run),
                allow_overwrite=args.force_overwrite,
            )
            if not summary.get("ok"):
                failures += 1
                print(f"    FAILED: {summary.get('error')}")
            elif not args.quiet:
                s = summary["summary"]
                mode = "preview" if summary.get("dry_run") else "cleaned"
                print(f"    {mode}: {s['rows_in']:,} -> {s['rows_out']:,} rows; "
                      f"{s['cells_changed']:,} cells; {s['flags']:,} flags")
        except Exception as exc:
            failures += 1
            print(f"    ERROR: {exc}")
    if failures:
        print(f"\n{failures} file(s) failed", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


def cmd_report(args: argparse.Namespace) -> int:
    from .auditing.run_io import regenerate_report

    run_dir = args.run_dir
    if not os.path.isdir(run_dir):
        print(f"ERROR: run directory not found: {run_dir}", file=sys.stderr)
        return EXIT_USAGE
    path = regenerate_report(run_dir)
    if not args.quiet:
        print(f"report rebuilt: {path}")
    return EXIT_OK


def cmd_config(args: argparse.Namespace) -> int:
    from importlib import resources

    from .config.schema import CleaningConfig, config_yaml

    if args.list_profiles:
        profiles = sorted(
            p.name for p in resources.files("data_cleaning_toolkit.config").joinpath("profiles").iterdir()
            if p.name.endswith((".yaml", ".yml"))
        )
        # bundled profile names
        print("bundled cleaning profiles:")
        for p in profiles:
            print(f"  - {p}")
        print("\nextract one with:  cleaner config --init <name.yaml> --profile <file>")
        return EXIT_OK
    if args.validate:
        cfg = _load_config(args.validate)
        print(f"OK: {args.validate} is a valid cleaning configuration")
        print(f"    name: {cfg.name}")
        print(f"    rules: {len(cfg.rules)}")
        for rid in cfg.rule_ids():
            print(f"      - {rid}")
        return EXIT_OK
    if args.init:
        if args.profile:
            import shutil

            src = resources.files("data_cleaning_toolkit.config").joinpath("profiles").joinpath(
                args.profile if args.profile.endswith((".yaml", ".yml")) else f"{args.profile}.yaml"
            )
            if not src.is_file():
                print(f"ERROR: bundled profile not found: {args.profile}", file=sys.stderr)
                return EXIT_USAGE
            shutil.copyfile(str(src), args.init)
            print(f"profile copied to {args.init}")
            return EXIT_OK
        template = CleaningConfig(
            name="my-cleaning-config",
            description="Template - edit rules below. See docs/configuration.md.",
        )
        with open(args.init, "w", encoding="utf-8") as fh:
            fh.write(config_yaml(template))
        print(f"template config written to {args.init}")
        return EXIT_OK
    print("nothing to do: use --init, --profile, --validate or --list-profiles", file=sys.stderr)
    return EXIT_USAGE


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cleaner",
        description="Advanced CSV & Excel data cleaner - profile, validate and clean "
        "tabular data safely with full audit trails.",
        epilog="Exit codes: 0=success, 1=runtime error, 2=usage error, "
        "4=validation violations found. "
        "Documentation: see README.md and docs/.",
    )
    parser.add_argument("--version", action="version", version="cleaner 1.0.0")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("profile", help="profile a dataset (structure, quality, anomalies)")
    _add_common(p)
    p.add_argument("--json", default=None, help="also write the profile as JSON to this path")
    p.set_defaults(func=cmd_profile)

    p = sub.add_parser("preview", help="dry-run: show what cleaning would do (writes nothing)")
    _add_common(p)
    p.add_argument("--output", "-o", default=None, help="(unused in preview; for symmetry)")
    p.set_defaults(func=cmd_preview)

    p = sub.add_parser("clean", help="clean a dataset and write outputs + audit trail")
    _add_common(p)
    p.add_argument("--output", "-o", default=None, help="output directory (default: config export.directory)")
    p.add_argument("--dry-run", action="store_true", help="preview instead of writing")
    p.add_argument("--yes", "-y", action="store_true", help="assume yes; skip interactive confirmation")
    p.add_argument("--force-overwrite", action="store_true",
                   help="overwrite existing output files (use with --yes for non-interactive runs)")
    p.set_defaults(func=cmd_clean)

    p = sub.add_parser("validate", help="validate a dataset against configured rules")
    _add_common(p)
    p.add_argument("--json", default=None, help="also write a JSON validation report")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("batch", help="clean every supported file in a directory")
    p.add_argument("--input", "-i", required=True, help="directory containing input files")
    p.add_argument("--config", "-c", required=True, help="cleaning config")
    p.add_argument("--output", "-o", default=None, help="output directory")
    p.add_argument("--sheet", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--yes", "-y", action="store_true",
                   help="accepted for interface consistency; batch is always non-interactive")
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument("--quiet", "-q", action="store_true")
    p.add_argument("--force-overwrite", action="store_true")
    p.set_defaults(func=cmd_batch)

    p = sub.add_parser("report", help="rebuild report.html from a previous run directory")
    p.add_argument("--run-dir", "-r", required=True, help="run directory containing audit/audit.json")
    p.add_argument("--quiet", "-q", action="store_true")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("config", help="create, validate or list cleaning configurations")
    p.add_argument("--init", default=None, metavar="PATH", help="write a template config to PATH")
    p.add_argument("--profile", default=None, metavar="NAME",
                   help="with --init: copy bundled profile NAME instead of the template")
    p.add_argument("--validate", default=None, metavar="PATH", help="validate a config file")
    p.add_argument("--list-profiles", action="store_true", help="list bundled profiles")
    p.set_defaults(func=cmd_config)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return int(args.func(args))
    except SystemExit as exc:  # argparse --help
        return int(exc.code or 0)
    except KeyboardInterrupt:
        print("\ninterrupted - nothing beyond the last completed step was written", file=sys.stderr)
        return EXIT_ERROR
    except Exception as exc:
        name = type(exc).__name__
        print(f"ERROR [{name}]: {exc}", file=sys.stderr)
        if getattr(args, "verbose", False):
            import traceback

            traceback.print_exc()
        code = EXIT_USAGE if isinstance(exc, (ValueError,)) and "config" in str(exc).lower() else EXIT_ERROR
        from .core.errors import ConfigError

        if isinstance(exc, ConfigError):
            code = EXIT_USAGE
        return code


if __name__ == "__main__":
    sys.exit(main())
