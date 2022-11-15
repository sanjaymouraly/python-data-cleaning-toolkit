"""Reports & Audit page: browse local runs, inspect audit trail, download artifacts."""

from __future__ import annotations

import json
import os

import pandas as pd
import streamlit as st

from state import list_local_runs
from ui import empty_state, format_int, hero, inject_css


def _download_button(path: str, label: str, key: str) -> None:
    if not path or not os.path.exists(path):
        st.caption(f"{label}: not available")
        return
    with open(path, "rb") as fh:
        data = fh.read()
    st.download_button(label, data=data, file_name=os.path.basename(path), key=key)


def render() -> None:
    inject_css()
    hero("Reports & Audit", "Every modification is recorded: what changed, where, "
          "why, and who approved the rule. Download machine-readable trails.")
    runs = list_local_runs()
    if not runs:
        empty_state(
            "No runs recorded yet. Clean a dataset in the **Cleaning Studio** "
            "or run the CLI (`cleaner clean ...`) - runs appear here."
        )
        return

    labels = [
        f"{m.get('run_id')} · {m.get('dataset')} · "
        f"{'preview' if m.get('is_preview') else 'apply'}"
        for m in runs
    ]
    selected = st.selectbox("Run", labels, index=0)
    manifest = runs[labels.index(selected)]
    run_dir = manifest["_dir"]

    s = manifest.get("summary", {})
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Rows", f"{s.get('rows_in', 0):,} → {s.get('rows_out', 0):,}")
    c2.metric("Cells changed", format_int(s.get("cells_changed")))
    c3.metric("Rows removed", format_int(s.get("rows_removed")))
    c4.metric("Flags", format_int(s.get("flags")))
    c5.metric("Rules", s.get("rules_executed", 0))

    st.caption(
        f"input: `{(manifest.get('input') or {}).get('filename', '?')}` · "
        f"sha256 `{(manifest.get('input') or {}).get('sha256', '?')[:16]}…` · "
        f"finished {manifest.get('finished_at', '?')}"
    )

    st.markdown("##### Rule outcomes")
    outcomes = pd.DataFrame(
        [
            {
                "rule": o.get("rule_id"),
                "type": o.get("rule_type"),
                "status": o.get("status"),
                "cells": o.get("cells_changed"),
                "removed": o.get("rows_removed"),
                "flags": o.get("flags"),
            }
            for o in manifest.get("outcomes", [])
        ]
    )
    if not outcomes.empty:
        st.dataframe(outcomes, width="stretch", hide_index=True)

    audit_path = os.path.join(run_dir, "audit", "audit.json")
    if os.path.exists(audit_path):
        with open(audit_path, encoding="utf-8") as fh:
            audit = json.load(fh).get("audit", {})
        tab_c, tab_f, tab_r = st.tabs(["Changes", "Flags", "Removed rows"])
        with tab_c:
            changes = audit.get("changes", [])
            if changes:
                st.dataframe(
                    pd.DataFrame(changes)[:400], width="stretch", hide_index=True
                )
                st.caption(f"{len(changes):,} retained record(s) "
                           f"({audit.get('totals', {}).get('change_records_dropped', 0)} "
                           "detail records capped; totals are exact)")
            else:
                st.caption("No cell changes recorded.")
        with tab_f:
            flags = audit.get("flags", [])
            if flags:
                st.dataframe(pd.DataFrame(flags)[:400], width="stretch",
                             hide_index=True)
            else:
                st.caption("No flagged values.")
        with tab_r:
            removed = audit.get("removed_rows", [])
            if removed:
                st.dataframe(pd.DataFrame(removed)[:400], width="stretch",
                             hide_index=True)
            else:
                st.caption("No rows were removed.")

    st.divider()
    st.markdown("##### Downloads")
    d1, d2, d3, d4 = st.columns(4)
    with d1:
        _download_button(os.path.join(run_dir, "report.html"),
                         "⬇️ report.html", "dl_report")
    with d2:
        _download_button(audit_path, "⬇️ audit.json", "dl_audit")
    with d3:
        _download_button(os.path.join(run_dir, "audit", "changes.csv"),
                         "⬇️ changes.csv", "dl_changes")
    with d4:
        outs = manifest.get("outputs", [])
        _download_button(outs[0]["path"] if outs else None,
                         "⬇️ cleaned file", "dl_cleaned")
    st.expander("manifest.json")
    with open(os.path.join(run_dir, "manifest.json"), encoding="utf-8") as fh:
        st.code(fh.read(), language="json")
