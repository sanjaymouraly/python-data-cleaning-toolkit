"""Before vs After page: side-by-side data, delta metrics, visual comparison."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data_cleaning_toolkit import profile_dataset
from state import get_dataset
from ui import empty_state, hero, inject_css


def render() -> None:
    inject_css()
    hero("Before vs After", "Compare the original dataset with the cleaned "
          "result of your approved plan.")
    ds = get_dataset()
    result = st.session_state.get("dtk_result")
    if ds is None:
        empty_state("Load a dataset first (Upload & Import).")
        return
    if result is None:
        empty_state(
            "No applied run yet. Configure and apply a plan in the "
            "**Cleaning Studio** (previews don't produce an 'after' state).",
        )
        return

    before_df, after_df = ds.dataframe, result.dataframe
    before_profile = st.session_state.get("dtk_profile") or profile_dataset(before_df)
    after_profile = profile_dataset(after_df)
    b, a = before_profile.to_dict(), after_profile.to_dict()

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Rows", f"{b['rows']:,}", f"{a['rows'] - b['rows']:+,}")
    c2.metric("Missing cells", f"{b['total_missing']:,}",
              f"{a['total_missing'] - b['total_missing']:+,}")
    c3.metric("Duplicate rows", f"{b['duplicate_rows']:,}",
              f"{a['duplicate_rows'] - b['duplicate_rows']:+,}")
    c4.metric("Quality score", f"{b['quality_score']:.0f}",
              f"{a['quality_score'] - b['quality_score']:+.1f}")
    c5.metric("Cells changed", f"{result.audit.total_changes:,}",
              f"{len(result.audit.flags)} flagged")

    fig = go.Figure()
    for label, prof, color in (("Before", b, "#94a3b8"), ("After", a, "#2563eb")):
        sc = prof["score_components"]
        fig.add_trace(
            go.Bar(
                name=label,
                x=["Completeness", "Uniqueness", "Consistency", "Overall"],
                y=[sc["completeness"], sc["uniqueness"], sc["consistency"],
                   prof["quality_score"]],
                marker_color=color,
                text=[f"{v:.0f}" for v in (sc["completeness"], sc["uniqueness"],
                                           sc["consistency"], prof["quality_score"])],
                textposition="outside",
            )
        )
    fig.update_layout(
        barmode="group", title="Quality metrics before vs after",
        yaxis=dict(range=[0, 110], title="score"),
        template="plotly_white", height=340, margin=dict(l=10, r=10, t=50, b=10),
    )
    st.plotly_chart(fig, width="stretch")

    st.divider()
    left_col, right_col = st.columns(2, gap="medium")
    common_cols = [c for c in before_df.columns if c in set(after_df.columns)]
    focus = st.multiselect(
        "Focus columns (empty = show all)", common_cols,
        default=common_cols[:6] if len(common_cols) > 6 else common_cols,
    )
    show_cols = focus or common_cols
    with left_col:
        st.markdown(f"**Before** - {len(before_df):,} rows")
        st.dataframe(before_df[show_cols].head(50), width="stretch")
    with right_col:
        st.markdown(f"**After** - {len(after_df):,} rows (first 50)")
        st.dataframe(after_df[show_cols].head(50), width="stretch")

    if result.audit.changes:
        st.divider()
        st.markdown("##### What changed (sample from the audit trail)")
        changes = pd.DataFrame(
            [
                {"rule": c.rule_id, "row": c.row, "column": c.column,
                 "before": c.original, "after": c.modified, "reason": c.reason}
                for c in result.audit.changes[:300]
            ]
        )
        st.dataframe(changes, width="stretch", hide_index=True)
        st.caption(f"Showing first {len(changes)} of {result.audit.total_changes:,} "
                   "recorded changes - full trail in Reports & Audit.")
