"""Data Profiling page: charts and per-column quality details."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from state import get_dataset
from ui import empty_state, hero, inject_css, quality_tone


def render() -> None:
    inject_css()
    hero("Data Profiling", "Read-only analysis of the loaded dataset: missingness, "
          "types, duplicates, distributions and anomalies.")
    ds = get_dataset()
    profile = st.session_state.get("dtk_profile")
    if ds is None or profile is None:
        empty_state("Load a dataset first (Upload & Import).")
        return
    p = profile.to_dict()

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Rows", f"{p['rows']:,}")
    m2.metric("Columns", p.get("column_count", "?"))
    m3.metric("Memory", f"{p['memory_mb']:.1f} MB")
    m4.metric("Missing cells", f"{p['total_missing']:,}", f"{p['missing_pct']}% of all cells")
    m5.metric("Duplicate rows", f"{p['duplicate_rows']:,}", f"{p['duplicate_pct']}% of rows")

    tone = quality_tone(p["quality_score"])
    color = {"ok": "#059669", "warn": "#d97706", "bad": "#dc2626"}[tone]
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=p["quality_score"],
            title={"text": "Quality score (0-100)"},
            gauge={
                "axis": {"range": [0, 100]},
                "bar": {"color": color},
                "steps": [
                    {"range": [0, 50], "color": "rgba(220,38,38,.12)"},
                    {"range": [50, 80], "color": "rgba(217,119,6,.12)"},
                    {"range": [80, 100], "color": "rgba(5,150,105,.12)"},
                ],
            },
        )
    )
    fig.update_layout(height=250, margin=dict(l=30, r=30, t=40, b=10), template="plotly_white")
    left, right = st.columns([1, 2])
    with left:
        st.plotly_chart(fig, width="stretch")
        st.caption(
            "Score = mean of completeness (missing cells), uniqueness "
            "(duplicate rows) and consistency (type/unit/label issues), "
            "documented in docs/architecture.md."
        )
    with right:
        cp = p["score_components"]
        comp = px.bar(
            x=[cp["completeness"], cp["uniqueness"], cp["consistency"]],
            y=["Completeness", "Uniqueness", "Consistency"],
            orientation="h",
            range_x=[0, 100],
            text_auto=".0f",
            title="Score components",
            color_discrete_sequence=["#2563eb"],
        )
        comp.update_layout(height=250, margin=dict(l=10, r=10, t=40, b=10),
                           template="plotly_white", yaxis=dict(autorange="reversed"))
        comp.update_xaxes(visible=False)
        st.plotly_chart(comp, width="stretch")

    st.divider()

    # missing values chart
    cols = p["columns"]
    missing_df = pd.DataFrame(
        [
            {"column": c["name"], "missing": c["missing"], "missing_pct": c["missing_pct"]}
            for c in cols
            if c["missing"] > 0
        ]
    ).sort_values("missing", ascending=False)
    if not missing_df.empty:
        fig = px.bar(
            missing_df.head(20), x="missing", y="column", orientation="h",
            title="Missing values by column (incl. text null markers)",
            text="missing_pct",
            color_discrete_sequence=["#d97706"],
        )
        fig.update_layout(
            height=min(460, 80 + 34 * len(missing_df.head(20))),
            template="plotly_white",
            yaxis=dict(autorange="reversed"),
        )
        fig.update_xaxes(title="missing cells")
        st.plotly_chart(fig, width="stretch")
    else:
        st.success("No missing values detected (including text markers like 'N/A').")

    # type distribution + unique counts
    c1, c2 = st.columns(2)
    with c1:
        kinds = pd.Series([c["inferred_kind"] for c in cols]).value_counts()
        fig = px.pie(
            names=kinds.index, values=kinds.values, title="Inferred column types",
            hole=0.45, color_discrete_sequence=px.colors.qualitative.Safe,
        )
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, width="stretch")
    with c2:
        uniq = pd.DataFrame(
            [
                {"column": c["name"], "unique": c["unique"],
                 "unique %": round(100 * c["unique"] / max(1, p["rows"]), 1)}
                for c in cols
            ]
        ).sort_values("unique %")
        fig = px.bar(
            uniq.head(20), x="unique %", y="column", orientation="h",
            title="Uniqueness by column (lowest 20)",
            color_discrete_sequence=["#2563eb"],
        )
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=40, b=10),
                          template="plotly_white", yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig, width="stretch")

    # numeric distributions
    numeric_cols = [
        c for c in cols
        if c.get("numeric_stats") and c["numeric_stats"].get("std") is not None
    ]
    if numeric_cols:
        st.markdown("##### Numeric distributions")
        selected = st.multiselect(
            "Columns", [c["name"] for c in numeric_cols],
            default=[c["name"] for c in numeric_cols][:4],
        )
        if selected:
            grid = st.columns(min(2, len(selected)))
            for i, name in enumerate(selected):
                col_prof = next(c for c in numeric_cols if c["name"] == name)
                series = pd.to_numeric(ds.dataframe[name], errors="coerce").dropna()
                if series.empty:
                    continue
                fig = px.histogram(x=series, nbins=40, title=name)
                st_n = col_prof["numeric_stats"]
                for bound, label in (("q1", "q1"), ("q3", "q3")):
                    fig.add_vline(x=st_n[bound], line_dash="dot",
                                  annotation_text=label, line_color="#6b7280")
                if st_n.get("outliers_iqr"):
                    fig.add_annotation(
                        text=f"{st_n['outliers_iqr']} IQR outliers", showarrow=False,
                        yref="paper", y=1.06, xref="paper", x=1, font=dict(color="#d97706"),
                    )
                fig.update_layout(height=280, margin=dict(l=10, r=10, t=46, b=10),
                                  template="plotly_white")
                with grid[i % len(grid)]:
                    st.plotly_chart(fig, width="stretch")

    # findings table
    st.markdown("##### Anomaly & issue breakdown")
    if p.get("findings"):
        findings = pd.DataFrame(p["findings"])
        findings.columns = ["severity", "area", "finding"]
        sev_color = findings["severity"].map(
            {"high": "#dc2626", "medium": "#d97706", "low": "#6b7280"}
        )
        styled = findings.style.apply(
            lambda s: [f"color: {c}; font-weight: 600" for c in sev_color]
        )
        st.dataframe(styled, width="stretch", hide_index=True)
    else:
        st.success("No anomalies detected.")

    # per-column detail
    st.markdown("##### Per-column detail")
    detail = pd.DataFrame(
        [
            {
                "column": c["name"],
                "kind": c["inferred_kind"],
                "dtype": c["pandas_dtype"],
                "missing": c["missing"],
                "missing %": c["missing_pct"],
                "unique": c["unique"],
                "notes": "; ".join(
                    filter(
                        None,
                        [
                            f"mixed types: {', '.join(c['mixed_types'])}" if c["mixed_types"] else "",
                            f"{c['whitespace_padded']} padded" if c["whitespace_padded"] else "",
                            f"{c['null_marker_count']} null markers" if c["null_marker_count"] else "",
                            (
                                f"units: {', '.join(c['distinct_units'])}"
                                if len(c["distinct_units"]) > 1
                                else ""
                            ),
                            f"{c['case_variants']} case variants" if c["case_variants"] else "",
                            f"{c['outlier_candidates']} outliers" if c["outlier_candidates"] else "",
                            f"{c['suspicious_values']} suspicious" if c["suspicious_values"] else "",
                            f"{c['parseable_dates']} date-like" if c["parseable_dates"] else "",
                        ],
                    )
                ),
                "top values": ", ".join(f"{v} ({n})" for v, n in c["top_values"][:3]),
            }
            for c in cols
        ]
    )
    st.dataframe(detail, width="stretch", hide_index=True)
