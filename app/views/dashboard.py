"""Dashboard page: dataset overview, quality indicators, recent runs."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from state import get_dataset, list_local_runs
from ui import empty_state, format_int, hero, inject_css, quality_tone


def render() -> None:
    inject_css()
    ds = get_dataset()
    profile = st.session_state.get("dtk_profile")

    if ds is None:
        hero(
            "Advanced CSV & Excel Data Cleaner",
            "Profile datasets, preview safe cleaning rules, and export audited "
            "results - all locally.",
        )
        st.markdown("##### Get started")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(
                "**1. Import data**\n\nGo to *Upload & Import* and drop a CSV "
                "or XLSX file. Try the bundled examples in `examples/data/`."
            )
        with c2:
            st.markdown(
                "**2. Review & preview**\n\nInspect the automatic profile, pick "
                "a cleaning profile, and preview every proposed change."
            )
        with c3:
            st.markdown(
                "**3. Apply & audit**\n\nApprove the plan, download cleaned "
                "files, and review the full audit trail."
            )
    else:
        p = profile.to_dict() if profile else {}
        tone = quality_tone(p.get("quality_score", 0)) if p else ""
        hero(
            ds.name,
            f"{ds.metadata.fmt.upper()} source · processed locally, nothing uploaded",
            chips=[
                (f"quality {p.get('quality_score', 0):.0f}/100", tone),
                (f"{format_int(p.get('rows'))} rows", ""),
                (
                    f"{p.get('missing_pct', 0)}% missing",
                    "warn" if p.get("missing_pct", 0) > 5 else "ok",
                ),
                (
                    f"{format_int(p.get('duplicate_rows'))} dup rows",
                    "warn" if p.get("duplicate_rows") else "ok",
                ),
            ],
        )
        if p:
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Rows", format_int(p["rows"]))
            m2.metric("Columns", p.get("column_count", "?"))
            m3.metric("Missing cells", format_int(p["total_missing"]), f"{p['missing_pct']}%")
            m4.metric("Duplicate rows", format_int(p["duplicate_rows"]))
            sc = p["score_components"]
            m5.metric(
                "Quality score",
                f"{p['quality_score']:.0f}/100",
                f"c{sc['completeness']:.0f}/u{sc['uniqueness']:.0f}/k{sc['consistency']:.0f}",
            )
            findings = p.get("findings", [])
            if findings:
                st.markdown("##### Top findings")
                sev_order = {"high": 0, "medium": 1, "low": 2}
                rows = sorted(findings, key=lambda f: sev_order.get(f["severity"], 3))[:8]
                findings_df = pd.DataFrame(
                    [
                        {"severity": f["severity"], "area": f["area"], "finding": f["message"]}
                        for f in rows
                    ]
                )
                st.dataframe(findings_df, width="stretch", hide_index=True)
            else:
                st.success("No structural issues detected by the profiler.")

    st.markdown("##### Recent local runs")
    runs = list_local_runs()
    if not runs:
        empty_state(
            "No cleaning runs recorded yet in this workspace. Completed runs "
            "(from the Cleaning Studio or the CLI) appear here with their "
            "audit trails."
        )
    else:
        rows = []
        for m in runs:
            s = m.get("summary", {})
            rows.append(
                {
                    "run": m.get("run_id"),
                    "dataset": m.get("dataset"),
                    "mode": "preview" if m.get("is_preview") else "apply",
                    "rows in": s.get("rows_in"),
                    "rows out": s.get("rows_out"),
                    "cells changed": s.get("cells_changed"),
                    "flags": s.get("flags"),
                    "finished": m.get("finished_at", "")[:19],
                }
            )
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        st.caption("Open *Reports & Audit* to browse run artifacts and download reports.")
