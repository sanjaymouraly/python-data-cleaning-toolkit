"""Run artifact persistence: audit logs, reports, manifest and config snapshot.

A completed run directory looks like::

    runs/<run_id>/
        manifest.json          # inputs, outputs, hashes, counters
        config_snapshot.yaml   # exact cleaning configuration used
        audit/audit.json       # machine-readable full audit trail
        audit/changes.csv      # per-modification log (row, column, before/after)
        audit/flags.csv        # review-needed items (optional)
        audit/audit_workbook.xlsx  # optional Excel audit workbook
        report.html            # human-readable report
        <dataset>_cleaned.csv|.xlsx|json
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

import pandas as pd

from ..auditing.audit import sha256_file, utc_now_iso
from ..core.engine import CleanResult
from ..core.errors import OutputError
from ..profiling.profiler import ProfileReport
from ..reporting.html_report import render_html_report, render_html_report_from_audit

ENGINE_VERSION = "1.0.0"


def outcome_records_frame(changes: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        changes,
        columns=["rule_id", "rule_type", "row", "column", "original", "modified", "reason", "kind"],
    )


def save_run(
    result: CleanResult,
    *,
    output_dir: str,
    dataset_name: str,
    exported_path: str | None = None,
    export_result: Any = None,
    profile: ProfileReport | None = None,
    profile_before: dict[str, Any] | None = None,
) -> str:
    """Persist all run artifacts; returns the run directory path."""
    run_id = f"run-{utc_now_iso().replace(':', '').replace('-', '')[:15]}-{uuid.uuid4().hex[:6]}"
    run_dir = os.path.join(output_dir, run_id)
    audit_dir = os.path.join(run_dir, "audit")
    os.makedirs(audit_dir, exist_ok=True)

    # -- config snapshot ---------------------------------------------------
    import yaml

    snapshot_path = os.path.join(run_dir, "config_snapshot.yaml")
    with open(snapshot_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(result.config_snapshot, fh, sort_keys=False, allow_unicode=True)
    # (context-managed above; lint pragmas are unnecessary here)

    # -- audit json --------------------------------------------------------
    audit_data = result.to_dict(include_audit_records=True)
    audit_path = os.path.join(audit_dir, "audit.json")
    with open(audit_path, "w", encoding="utf-8") as fh:
        json.dump(audit_data, fh, indent=2, ensure_ascii=False, default=str)

    # -- changes csv -------------------------------------------------------
    changes_df = pd.DataFrame(
        [
            {
                "rule_id": c.rule_id,
                "rule_type": c.rule_type,
                "row": c.row,
                "column": c.column,
                "original": c.original,
                "modified": c.modified,
                "reason": c.reason,
                "kind": c.kind,
            }
            for c in result.audit.changes
        ]
    )
    changes_df.to_csv(os.path.join(audit_dir, "changes.csv"), index=False)

    # -- flags csv ---------------------------------------------------------
    flags_df = pd.DataFrame(
        [
            {
                "rule_id": f.rule_id,
                "rule_type": f.rule_type,
                "row": f.row,
                "column": f.column,
                "value": f.value,
                "message": f.message,
            }
            for f in result.audit.flags
        ]
    )
    flags_df.to_csv(os.path.join(audit_dir, "flags.csv"), index=False)

    # -- removed rows csv --------------------------------------------------
    removed_df = pd.DataFrame(
        [
            {"rule_id": r.rule_id, "rule_type": r.rule_type, "row": r.row, "reason": r.reason,
             **{f"key:{k}": v for k, v in r.key_values.items()}}
            for r in result.audit.removed_rows
        ]
    )
    removed_df.to_csv(os.path.join(audit_dir, "removed_rows.csv"), index=False)


    # -- optional Excel audit workbook --------------------------------------
    excel_audit_path = None
    if result.config_snapshot["config"]["audit"].get("write_excel_workbook"):
        excel_audit_path = os.path.join(audit_dir, "audit_workbook.xlsx")
        _write_audit_workbook(result, excel_audit_path)

    # -- html report --------------------------------------------------------
    report_path = os.path.join(run_dir, "report.html")
    html = render_html_report(
        run_id=run_id,
        result=result,
        profile=profile,
        export_result=export_result,
        dataset_name=dataset_name,
        profile_before=profile_before,
    )
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(html)

    # -- manifest ------------------------------------------------------------
    manifest = {
        "run_id": run_id,
        "engine_version": ENGINE_VERSION,
        "finished_at": result.finished_at,
        "is_preview": result.is_preview,
        "dataset": dataset_name,
        "input": result.source_metadata,
        "summary": result.summary(),
        "outputs": [],
        "artifacts": {},
    }
    if exported_path and os.path.exists(exported_path):
        manifest["outputs"] = [
            {
                "path": exported_path,
                "sha256": sha256_file(exported_path),
                "size_bytes": os.path.getsize(exported_path),
                "validated": bool(export_result and export_result.validated),
            }
        ]
    artifact_paths = {
        "audit_json": audit_path,
        "changes_csv": os.path.join(audit_dir, "changes.csv"),
        "flags_csv": os.path.join(audit_dir, "flags.csv"),
        "removed_rows_csv": os.path.join(audit_dir, "removed_rows.csv"),
        "report_html": report_path,
        "config_snapshot_yaml": snapshot_path,
    }
    if excel_audit_path:
        artifact_paths["audit_workbook_xlsx"] = excel_audit_path
    for name, p in artifact_paths.items():
        if p and os.path.exists(p):
            manifest["artifacts"][name] = {
                "path": p,
                "sha256": sha256_file(p),
                "size_bytes": os.path.getsize(p),
            }
    manifest_path = os.path.join(run_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False, default=str)

    return run_dir


def _write_audit_workbook(result: CleanResult, path: str) -> None:
    """Write a multi-sheet Excel audit workbook (atomic via a temp sibling)."""
    tmp = path + ".tmp.xlsx"
    try:
        summary_rows = [
            {"metric": "is_preview", "value": result.is_preview},
            {"metric": "rows_in", "value": result.rows_in},
            {"metric": "rows_out", "value": result.rows_out},
            {"metric": "cells_changed", "value": result.audit.total_changes},
            {"metric": "rows_removed", "value": len(result.audit.removed_rows)},
            {"metric": "flags", "value": len(result.audit.flags)},
            {"metric": "finished_at", "value": result.finished_at},
        ]
        _df_to_sheet(pd.DataFrame(summary_rows), tmp, "Summary")
        changes = pd.DataFrame([c.to_dict() for c in result.audit.changes])
        if not changes.empty:
            _append_sheet(changes, tmp, "Changes")
        removed = pd.DataFrame([r.to_dict() for r in result.audit.removed_rows])
        if not removed.empty:
            _append_sheet(removed, tmp, "RemovedRows")
        flags = pd.DataFrame([f.to_dict() for f in result.audit.flags])
        if not flags.empty:
            _append_sheet(flags, tmp, "Flags")
        os.replace(tmp, path)
    except Exception as exc:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise OutputError(f"failed to write Excel audit workbook: {exc}") from exc


def _df_to_sheet(df: pd.DataFrame, path: str, sheet: str) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=sheet[:31], index=False)


def _append_sheet(df: pd.DataFrame, path: str, sheet: str) -> None:
    from openpyxl import load_workbook

    wb = load_workbook(path)
    ws = wb.create_sheet(sheet[:31])
    ws.append([str(c) for c in df.columns])
    for _, row in df.iterrows():
        ws.append([str(v) if not isinstance(v, (int, float, bool)) else v for v in row])
    wb.save(path)
    wb.close()


def regenerate_report(run_dir: str) -> str:
    """Rebuild report.html from a run directory's audit.json (CLI ``report``)."""
    audit_path = os.path.join(run_dir, "audit", "audit.json")
    if not os.path.exists(audit_path):
        raise OutputError(f"no audit.json found in {run_dir}")
    with open(audit_path, encoding="utf-8") as fh:
        data = json.load(fh)
    report_path = os.path.join(run_dir, "report.html")
    src_name = str((data.get("source") or {}).get("filename", "dataset"))
    html = render_html_report_from_audit(data, dataset_name=src_name)
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return report_path


def _append_sheet_unused():  # pragma: no cover
    pass
