"""Settings page: import/output preferences, limits, profile management."""

from __future__ import annotations

import os

import streamlit as st

from data_cleaning_toolkit import __version__, config_yaml
from data_cleaning_toolkit.config.schema import LimitsConfig
from state import (
    clear_all,
    get_config,
    init_state,
    list_local_runs,
    saved_profiles_dir,
    workspace_dir,
)
from ui import hero, inject_css


def render() -> None:
    inject_css()
    hero("Settings", "Dashboard preferences, safety limits and reusable "
          "cleaning profiles. Everything stays on this machine.")
    init_state()
    settings = st.session_state["dtk_settings"]

    st.markdown("##### Defaults")
    c1, c2 = st.columns(2)
    settings["export_fmt"] = c1.selectbox(
        "Default output format", ["csv", "xlsx", "json"],
        index=["csv", "xlsx", "json"].index(settings.get("export_fmt", "csv")),
    )
    settings["excel_audit_workbook"] = c2.checkbox(
        "Also write an Excel audit workbook", value=settings.get("excel_audit_workbook", False)
    )
    settings["redact"] = c1.checkbox(
        "Redact configured columns in audit logs (profiles set redact_columns)",
        value=settings.get("redact", False),
    )
    settings["header_row"] = c2.number_input(
        "Default header row", 0, 50, value=int(settings.get("header_row", 0))
    )

    st.markdown("##### Safety limits (from the active cleaning config)")
    cfg = get_config()
    limits = cfg.limits if cfg is not None else LimitsConfig()
    c1, c2, c3 = st.columns(3)
    c1.metric("Max file size", f"{limits.max_file_mb:g} MB")
    c2.metric("Max rows", f"{limits.max_rows:,}")
    c3.metric("Max columns", f"{limits.max_columns:,}")
    upload_cap = os.environ.get("DTK_MAX_UPLOAD_MB")
    st.caption(
        "Limits live in each cleaning config (`limits:` section). "
        + (
            f"Dashboard upload cap from DTK_MAX_UPLOAD_MB: {upload_cap} MB."
            if upload_cap
            else "Set DTK_MAX_UPLOAD_MB to cap dashboard upload size explicitly."
        )
    )

    st.markdown("##### Save the active plan as a reusable profile")
    if cfg is not None:
        profile_name = st.text_input("Profile name", value=cfg.name or "my-profile")
        if st.button("Save profile"):
            target = os.path.join(saved_profiles_dir(), f"{profile_name}.yaml")
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(config_yaml(cfg))
            st.success(f"Saved to {target} - it now appears as 'saved: {profile_name}' "
                       "in the Cleaning Studio.")
        with st.expander("Download current YAML"):
            st.download_button("⬇️ config.yaml", data=config_yaml(cfg),
                               file_name=f"{cfg.name or 'config'}.yaml")
    else:
        st.caption("No active plan - configure one in the Cleaning Studio first.")

    st.markdown("##### Workspace")
    st.caption(f"Local workspace: `{workspace_dir()}`")
    st.caption(f"Runs recorded: {len(list_local_runs())}")
    if st.button("Clear session (dataset, plan, results)"):
        clear_all()
        st.rerun()

    st.markdown("##### About")
    st.caption(
        f"data-cleaning-toolkit v{__version__} · MIT license · pandas-based, "
        "fully offline. Excel export re-writes cell values: original workbook "
        "formatting, charts and macros are not preserved (by design)."
    )
