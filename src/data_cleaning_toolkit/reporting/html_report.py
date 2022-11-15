"""Self-contained HTML reports (inline CSS, no external resources)."""

from __future__ import annotations

import html
from typing import Any

_CSS = """
:root { --bg:#f6f8fa; --card:#ffffff; --ink:#1f2937; --muted:#6b7280;
        --accent:#2563eb; --ok:#059669; --warn:#d97706; --bad:#dc2626; --line:#e5e7eb; }
* { box-sizing: border-box; }
body { margin:0; padding:24px; background:var(--bg); color:var(--ink);
       font:14px/1.55 -apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; }
.wrap { max-width:1080px; margin:0 auto; }
h1 { font-size:22px; margin:0 0 4px; } h2 { font-size:17px; margin:28px 0 10px; }
.sub { color:var(--muted); margin-bottom:20px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px;
        padding:16px 18px; margin-bottom:14px; }
.metrics { display:flex; gap:12px; flex-wrap:wrap; }
.metric { flex:1 1 130px; background:var(--card); border:1px solid var(--line);
          border-radius:10px; padding:12px 14px; }
.metric .v { font-size:22px; font-weight:700; } .metric .k { color:var(--muted); font-size:12px; }
table { border-collapse:collapse; width:100%; font-size:13px; }
th,td { text-align:left; padding:7px 10px; border-bottom:1px solid var(--line); vertical-align:top; }
th { background:#f1f5f9; font-weight:600; }
.badge { display:inline-block; padding:2px 9px; border-radius:99px; font-size:12px; font-weight:600; }
.b-applied { background:#d1fae5; color:#065f46; } .b-no { background:#e5e7eb; color:#374151; }
.b-flag { background:#fef3c7; color:#92400e; } .b-error { background:#fee2e2; color:#991b1b; }
.warn { color:var(--warn); } .ok { color:var(--ok); } .bad { color:var(--bad); }
code, .mono { font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; font-size:12px; }
details { margin:6px 0; } summary { cursor:pointer; color:var(--accent); }
footer { color:var(--muted); margin-top:26px; font-size:12px; }
"""

STATUS_BADGE = {
    "applied": ("b-applied", "applied"),
    "no_changes": ("b-no", "no changes"),
    "flagged_only": ("b-flag", "flagged only"),
    "error": ("b-error", "error"),
}


def _esc(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def _badge(status: str) -> str:
    cls, label = STATUS_BADGE.get(status, ("b-no", status))
    return f'<span class="badge {cls}">{_esc(label)}</span>'


def _metric(v: Any, k: str) -> str:
    return f'<div class="metric"><div class="v">{_esc(v)}</div><div class="k">{_esc(k)}</div></div>'


def render_html_report(
    *,
    run_id: str,
    result: Any,
    profile: Any | None = None,
    export_result: Any | None = None,
    dataset_name: str = "dataset",
    profile_before: dict[str, Any] | None = None,
) -> str:
    summary = result.summary()
    parts: list[str] = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        f"<title>Cleaning report - {_esc(dataset_name)}</title>",
        f"<style>{_CSS}</style></head><body><div class='wrap'>",
        "<h1>Data Cleaning Report</h1>",
        f"<div class='sub'>run <code>{_esc(run_id)}</code> &middot; dataset "
        f"<b>{_esc(dataset_name)}</b> &middot; finished {_esc(result.finished_at)}"
        f" &middot; mode: <b>{'PREVIEW' if result.is_preview else 'APPLY'}</b></div>",
    ]

    src = result.source_metadata or {}
    if src:
        parts.append(
            "<div class='card'><b>Source</b><br>"
            f"<span class='mono'>{_esc(src.get('filename', ''))}</span><br>"
            f"<span class='mono'>sha256: {_esc(src.get('sha256', ''))}</span>"
            + (f"<br><span class='mono'>sheet: {_esc(src.get('sheet'))}</span>" if src.get("sheet") else "")
            + "</div>"
        )

    parts.append("<div class='metrics'>" + "".join([
        _metric(f"{summary['rows_in']:,}", "rows in"),
        _metric(f"{summary['rows_out']:,}", "rows out"),
        _metric(f"{summary['rows_removed']:,}", "rows removed"),
        _metric(f"{summary['cells_changed']:,}", "cells changed"),
        _metric(f"{summary['flags']:,}", "flagged for review"),
    ]) + "</div>")

    if summary.get("stopped_early"):
        parts.append(
            f"<div class='card bad'><b>Run stopped early:</b> {_esc(summary.get('error'))}<br>"
            "No further rules were executed (fail-safe). Preview mode means no "
            "output was written.</div>"
            if result.is_preview
            else f"<div class='card bad'><b>Run stopped early:</b> {_esc(summary.get('error'))}</div>"
        )

    parts.append("<h2>Rules executed</h2><div class='card'><table><tr>"
                 "<th>Rule</th><th>Type</th><th>Status</th><th>Cells</th>"
                 "<th>Rows removed</th><th>Flags</th><th>Warnings</th></tr>")
    for o in result.outcomes:
        parts.append(
            f"<tr><td><code>{_esc(o.rule_id)}</code></td><td>{_esc(o.rule_type)}</td>"
            f"<td>{_badge(o.status)}</td><td>{o.cells_changed:,}</td>"
            f"<td>{o.rows_removed:,}</td><td>{o.flags:,}</td>"
            f"<td class='warn'>{_esc('; '.join(o.warnings))}</td></tr>"
        )
    parts.append("</table>")

    examples = [(o.rule_id, ex) for o in result.outcomes for ex in o.examples]
    if examples:
        parts.append("<details><summary>Before / after examples</summary>"
                     "<table><tr><th>Rule</th><th>Row</th><th>Column</th>"
                     "<th>Before</th><th>After</th><th>Reason</th></tr>")
        for rid, ex in examples[:200]:
            parts.append(
                f"<tr><td><code>{_esc(rid)}</code></td><td>{_esc(ex.get('row'))}</td>"
                f"<td>{_esc(ex.get('column'))}</td><td class='mono'>{_esc(ex.get('before'))}</td>"
                f"<td class='mono'>{_esc(ex.get('after'))}</td><td>{_esc(ex.get('reason'))}</td></tr>"
            )
        parts.append("</table></details>")
    parts.append("</div>")

    if result.audit.flags:
        parts.append("<h2>Flagged for review (not modified)</h2><div class='card'>"
                     "<table><tr><th>Row</th><th>Column</th><th>Value</th><th>Reason</th></tr>")
        for f in result.audit.flags[:400]:
            parts.append(
                f"<tr><td>{_esc(f.row)}</td><td>{_esc(f.column)}</td>"
                f"<td class='mono'>{_esc(f.value)}</td><td>{_esc(f.message)}</td></tr>"
            )
        shown = min(400, len(result.audit.flags))
        if len(result.audit.flags) > shown:
            parts.append(f"<tr><td colspan='4'>...and {len(result.audit.flags) - shown} more "
                         "(see audit/flags.csv)</td></tr>")
        parts.append("</table></div>")

    if result.audit.removed_rows:
        parts.append("<h2>Removed rows provenance</h2><div class='card'><table>"
                     "<tr><th>Row</th><th>Rule</th><th>Reason</th><th>Key values</th></tr>")
        for r in result.audit.removed_rows[:400]:
            keys = ", ".join(f"{k}={v}" for k, v in r.key_values.items())
            parts.append(
                f"<tr><td>{_esc(r.row)}</td><td><code>{_esc(r.rule_id)}</code></td>"
                f"<td>{_esc(r.reason)}</td><td class='mono'>{_esc(keys)}</td></tr>"
            )
        parts.append("</table></div>")

    if export_result is not None:
        parts.append(
            "<h2>Output</h2><div class='card'>"
            f"<span class='mono'>{_esc(export_result.path)}</span><br>"
            f"format {export_result.fmt.upper()} &middot; {export_result.rows:,} rows &times; "
            f"{export_result.columns:,} columns"
            + (f" &middot; <span class='warn'>{export_result.guarded_cells:,} cell(s) "
               "guarded against formula injection</span>" if export_result.guarded_cells else "")
            + (" &middot; <span class='ok'>validated by reopening</span>" if export_result.validated else "")
            + "</div>"
        )

    if profile is not None:
        p = profile.to_dict()
        parts.append(
            "<h2>Input dataset profile</h2><div class='metrics'>" + "".join([
                _metric(f"{p['rows']:,}", "rows"),
                _metric(f"{p.get('column_count', '?'):,}", "columns"),
                _metric(f"{p['missing_pct']}%", "missing cells"),
                _metric(f"{p['duplicate_rows']:,}", "duplicate rows"),
                _metric(f"{p['quality_score']}", "quality score /100"),
            ]) + "</div>"
        )
        if p.get("findings"):
            parts.append("<div class='card'><table><tr><th>Severity</th><th>Area</th>"
                         "<th>Finding</th></tr>")
            for f in p["findings"]:
                sev_cls = {"high": "bad", "medium": "warn", "low": ""}.get(f["severity"], "")
                parts.append(
                    f"<tr><td class='{sev_cls}'>{_esc(f['severity'])}</td>"
                    f"<td>{_esc(f['area'])}</td><td>{_esc(f['message'])}</td></tr>"
                )
            parts.append("</table></div>")

    parts.append(
        "<footer>Generated by data-cleaning-toolkit "
        f"{_esc(result.engine_version)} &middot; preview runs never modify "
        "source data &middot; full machine-readable trail in audit/audit.json</footer>"
        "</div></body></html>"
    )
    return "".join(parts)


def render_html_report_from_audit(data: dict[str, Any], dataset_name: str = "dataset") -> str:
    """Rebuild a report from persisted audit.json (CLI ``report`` command)."""
    summary = data.get("summary", {})
    outcomes = data.get("outcomes", [])
    audit = data.get("audit", {})
    src = data.get("source") or {}
    finished = data.get("finished_at", "")
    version = data.get("engine_version", "?")
    is_preview = bool(summary.get("is_preview"))

    parts: list[str] = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        f"<title>Cleaning report - {_esc(dataset_name)}</title>",
        f"<style>{_CSS}</style></head><body><div class='wrap'>",
        "<h1>Data Cleaning Report (rebuilt from audit log)</h1>",
        f"<div class='sub'>dataset <b>{_esc(dataset_name)}</b> &middot; finished "
        f"{_esc(finished)} &middot; mode: <b>{'PREVIEW' if is_preview else 'APPLY'}</b></div>",
        f"<div class='card'><span class='mono'>sha256: {_esc(src.get('sha256', 'n/a'))}</span></div>",
        "<div class='metrics'>" + "".join([
            _metric(f"{summary.get('rows_in', 0):,}", "rows in"),
            _metric(f"{summary.get('rows_out', 0):,}", "rows out"),
            _metric(f"{summary.get('rows_removed', 0):,}", "rows removed"),
            _metric(f"{summary.get('cells_changed', 0):,}", "cells changed"),
            _metric(f"{summary.get('flags', 0):,}", "flagged"),
        ]) + "</div>",
        "<h2>Rules executed</h2><div class='card'><table><tr><th>Rule</th><th>Type</th>"
        "<th>Status</th><th>Cells</th><th>Rows removed</th><th>Flags</th></tr>",
    ]
    for o in outcomes:
        parts.append(
            f"<tr><td><code>{_esc(o.get('rule_id'))}</code></td>"
            f"<td>{_esc(o.get('rule_type'))}</td><td>{_badge(o.get('status', ''))}</td>"
            f"<td>{o.get('cells_changed', 0):,}</td><td>{o.get('rows_removed', 0):,}</td>"
            f"<td>{o.get('flags', 0):,}</td></tr>"
        )
    parts.append("</table></div>")

    flags = audit.get("flags", [])
    if flags:
        parts.append("<h2>Flagged for review</h2><div class='card'><table>"
                     "<tr><th>Row</th><th>Column</th><th>Value</th><th>Reason</th></tr>")
        for f in flags[:400]:
            parts.append(
                f"<tr><td>{_esc(f.get('row'))}</td><td>{_esc(f.get('column'))}</td>"
                f"<td class='mono'>{_esc(f.get('value'))}</td><td>{_esc(f.get('message'))}</td></tr>"
            )
        parts.append("</table></div>")

    removed = audit.get("removed_rows", [])
    if removed:
        parts.append("<h2>Removed rows provenance</h2><div class='card'><table>"
                     "<tr><th>Row</th><th>Rule</th><th>Reason</th><th>Key values</th></tr>")
        for r in removed[:400]:
            keys = ", ".join(f"{k}={v}" for k, v in (r.get("key_values") or {}).items())
            parts.append(
                f"<tr><td>{_esc(r.get('row'))}</td><td><code>{_esc(r.get('rule_id'))}</code></td>"
                f"<td>{_esc(r.get('reason'))}</td><td class='mono'>{_esc(keys)}</td></tr>"
            )
        parts.append("</table></div>")

    parts.append(
        f"<footer>Rebuilt from audit/audit.json &middot; engine {version}</footer>"
        "</div></body></html>"
    )
    return "".join(parts)
