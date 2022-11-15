"""Cleaning Studio: choose/build rules, preview, then apply with approval."""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st
import yaml

from data_cleaning_toolkit import CleaningEngine, ConfigError, config_yaml, parse_config
from data_cleaning_toolkit.auditing.run_io import save_run
from data_cleaning_toolkit.exporters.exporters import sanitize_filename
from state import (
    get_config,
    get_dataset,
    runs_dir,
    saved_profiles_dir,
    set_config,
)
from ui import empty_state, hero, inject_css

RULE_TYPES = {
    "missing_values": "Normalize null markers + fill/remove strategy",
    "duplicates": "Exact / key-based duplicate policy",
    "type_conversion": "Convert a column to a typed representation",
    "date_normalize": "Parse & normalize dates (ambiguity-aware)",
    "string_standardize": "Trim, case, unicode, label mappings",
    "numeric_validate": "Bounds, signs, outliers (flag by default)",
    "unit_normalize": "Convert units (mass/length/temperature)",
    "allowed_values": "Restrict a column to allowed values",
    "regex_match": "Pattern check on a column",
    "required_column": "Required field check",
    "unique_key": "Uniqueness on key columns",
    "cross_column": "Compare columns (e.g. total = price x qty)",
    "conditional_required": "Required when a condition holds",
}


def render() -> None:
    inject_css()
    hero("Cleaning Studio", "Configure rules, preview every proposed change, "
          "then apply only what you approve. Previews never modify data.")
    ds = get_dataset()
    if ds is None:
        empty_state("Load a dataset first (Upload & Import).")
        return

    tab_config, tab_preview, tab_apply = st.tabs(
        ["1 · Configure rules", "2 · Preview", "3 · Apply"]
    )
    with tab_config:
        _config_tab(ds)
    with tab_preview:
        _preview_tab(ds)
    with tab_apply:
        _apply_tab(ds)


# ---------------------------------------------------------------------------
# config tab
# ---------------------------------------------------------------------------


def _available_profiles() -> dict[str, str]:
    """name -> path for bundled + example + user-saved profiles."""
    import importlib.resources

    out: dict[str, str] = {}
    try:
        base = importlib.resources.files("data_cleaning_toolkit.config").joinpath("profiles")
        for p in sorted(base.iterdir()):
            if p.name.endswith((".yaml", ".yml")):
                out[f"bundled: {p.name[:-5]}"] = str(p)
    except (FileNotFoundError, ModuleNotFoundError):  # pragma: no cover
        pass
    repo_configs = os.path.join(os.getcwd(), "configs")
    if os.path.isdir(repo_configs):
        for f in sorted(os.listdir(repo_configs)):
            if f.endswith((".yaml", ".yml")):
                out[f"example: {f[:-5]}"] = os.path.join(repo_configs, f)
    for d in (saved_profiles_dir(),):
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if f.endswith((".yaml", ".yml")):
                    out[f"saved: {f[:-5]}"] = os.path.join(d, f)
    return out


def _config_tab(ds) -> None:
    profiles = _available_profiles()
    c1, c2 = st.columns([2, 1])
    with c1:
        source = st.radio(
            "Configuration source",
            ["Pick a cleaning profile", "Paste / edit YAML", "Build rules in the UI"],
            horizontal=True,
        )
    cfg = None

    if source == "Pick a cleaning profile":
        with c2:
            st.caption(f"{len(profiles)} profiles found")
        choice = st.selectbox("Profile", list(profiles) or ["(none found)"])
        if choice in profiles and st.button("Load profile", type="primary"):
            try:
                from data_cleaning_toolkit import load_config_file

                set_config(load_config_file(profiles[choice]), choice)
                st.rerun()
            except ConfigError as exc:
                st.error(str(exc))
    elif source == "Paste / edit YAML":
        current = get_config()
        initial = st.session_state.get("dtk_yaml_text") or (
            config_yaml(current) if current else _starter_yaml(ds)
        )
        text = st.text_area(
            "Cleaning configuration (YAML)", value=initial, height=420,
            key="dtk_yaml_editor",
        )
        if st.button("Validate & use this YAML", type="primary"):
            try:
                cfg = parse_config(text)
                st.session_state["dtk_yaml_text"] = text
                set_config(cfg, "custom YAML")
                st.success(f"Configuration valid - {len(cfg.rules)} rule(s).")
            except ConfigError as exc:
                st.error(f"Invalid configuration:\n\n{exc}")
    else:
        cfg = _ui_builder(ds)
        if cfg is not None:
            set_config(cfg, "UI-built")

    current = get_config()
    if current is not None and source != "Build rules in the UI":
        st.divider()
        st.markdown(f"**Active configuration:** `{st.session_state.get('dtk_config_name')}` "
                    f"- {len(current.rules)} rule(s)")
        with st.expander("Show YAML"):
            st.code(config_yaml(current), language="yaml")


def _starter_yaml(ds) -> str:
    cols = [str(c) for c in ds.dataframe.columns]
    first_text = next((c for c in cols if ds.dataframe[c].dtype == object), cols[0] if cols else "column")
    return f"""version: "1.0"
name: my-plan
description: Edited in the Cleaning Studio
rules:
  - id: null-markers
    type: missing_values
    strategy: retain
    null_markers: ["", "n/a", "null", "unknown", "-"]
  - id: trim-{first_text}
    type: string_standardize
    columns: [{first_text}]
    trim_whitespace: true
  - id: exact-duplicates
    type: duplicates
    keep: first
export:
  fmt: csv
audit:
  key_columns: [{cols[0] if cols else ""}]
"""


def _ui_builder(ds) -> None:
    """Add-rule form; edits are merged into the active config."""
    cols = [str(c) for c in ds.dataframe.columns]
    current = get_config()
    with st.expander("➕ Add a rule", expanded=current is None):
        rtype = st.selectbox("Rule type", list(RULE_TYPES), format_func=RULE_TYPES.get)
        next_num = len(current.rules) + 1 if current else 1
        rid = st.text_input("Rule id", value=f"{rtype}-{next_num:02d}")
        cfg_map: dict = {"type": rtype, "id": rid}

        multi = rtype in {
            "missing_values", "date_normalize", "numeric_validate",
            "string_standardize", "unique_key",
        }
        single = rtype in {"type_conversion", "unit_normalize", "allowed_values",
                           "regex_match", "required_column", "conditional_required",
                           "cross_column"}
        picked: list[str] = []
        if multi:
            picked = st.multiselect("Columns (empty = all)", cols)
        col = st.selectbox("Column", cols) if single else None

        if rtype == "missing_values":
            cfg_map["strategy"] = st.selectbox(
                "Strategy",
                ["retain", "remove_rows", "remove_columns", "fill_constant",
                 "mean", "median", "mode", "ffill", "bfill"],
            )
            if cfg_map["strategy"] == "fill_constant":
                cfg_map["fill_value"] = st.text_input("Fill value", value="0")
            if picked:
                cfg_map["columns"] = picked
        elif rtype == "duplicates":
            cfg_map["keep"] = st.selectbox("Keep", ["first", "last", "none"])
            cfg_map["flag_only"] = st.checkbox("Flag only (review, don't delete)", value=True)
            if picked := st.multiselect("Key columns (empty = whole row)", cols):
                cfg_map["columns"] = picked
        elif rtype == "type_conversion":
            cfg_map["column"] = col
            cfg_map["target"] = st.selectbox(
                "Target type", ["integer", "decimal", "boolean", "text", "category"]
            )
            if cfg_map["target"] in {"integer", "decimal"}:
                cfg_map["on_error"] = st.selectbox("On error", ["flag", "set_null", "remove_row", "fail"])
        elif rtype == "date_normalize":
            cfg_map["columns"] = picked or [st.selectbox("Date column", cols)]
            cfg_map["dayfirst"] = st.selectbox(
                "Day-first for ambiguous d/m dates",
                ["(flag, don't guess)", "true", "false"],
            )
            if cfg_map["dayfirst"] == "true":
                cfg_map["dayfirst"] = True
            elif cfg_map["dayfirst"] == "false":
                cfg_map["dayfirst"] = False
            else:
                cfg_map.pop("dayfirst")
        elif rtype == "string_standardize":
            if picked:
                cfg_map["columns"] = picked
            cfg_map["trim_whitespace"] = st.checkbox("Trim whitespace", value=True)
            case = st.selectbox("Case", ["none", "lower", "upper", "title", "sentence"])
            if case != "none":
                cfg_map["case"] = case
        elif rtype == "numeric_validate":
            cfg_map["columns"] = picked or [st.selectbox("Numeric column", cols, key="numcol")]
            c1, c2 = st.columns(2)
            if v := c1.text_input("Minimum (blank = none)"):
                cfg_map["min"] = float(v)
            if v := c2.text_input("Maximum (blank = none)"):
                cfg_map["max"] = float(v)
            cfg_map["allow_negative"] = st.checkbox("Allow negatives", value=True)
        elif rtype == "unit_normalize":
            cfg_map["value_column"] = st.selectbox("Value column", cols)
            uc = st.selectbox("Unit column", ["(fixed source unit)"] + cols)
            if uc != "(fixed source unit)":
                cfg_map["unit_column"] = uc
                cfg_map["source_unit"] = st.text_input("Source unit (when fixed)")
            else:
                cfg_map["source_unit"] = st.text_input("Source unit", value="kg")
            cfg_map["category"] = st.selectbox("Category", ["mass", "length", "temperature"])
            cfg_map["target_unit"] = st.text_input("Target unit", value="g")
        elif rtype == "allowed_values":
            cfg_map["column"] = col
            raw = st.text_input("Allowed values (comma-separated)", value="a, b, c")
            cfg_map["values"] = [v.strip() for v in raw.split(",") if v.strip()]
        elif rtype == "regex_match":
            cfg_map["column"] = col
            cfg_map["pattern"] = st.text_input("Regex pattern", value="^.*$")
        elif rtype == "required_column":
            cfg_map["column"] = col
        elif rtype == "unique_key":
            cfg_map["columns"] = picked or [st.selectbox("Key column", cols, key="keycol")]
        elif rtype == "cross_column":
            cfg_map["left"] = st.selectbox("Left column", cols)
            cfg_map["operator"] = st.selectbox("Operator", ["==", "!=", ">", ">=", "<", "<="])
            cfg_map["right_column"] = st.selectbox("Right column", cols)
            cfg_map["numeric"] = True
        elif rtype == "conditional_required":
            cfg_map["column"] = st.selectbox("Required column", cols)
            cfg_map["when_column"] = st.selectbox("When column", cols)
            cfg_map["when_operator"] = st.selectbox("When operator", ["==", "!="])
            cfg_map["when_value"] = st.text_input("When value", value="senior")

        if st.button("Add rule to plan", type="primary"):
            try:
                base = yaml.safe_dump(cfg_map, sort_keys=False)
                rule = parse_config(_wrap_rule(base))
                merged = _merge_rule(current, rule)
                set_config(merged, "UI-built")
                st.success(f"Rule {rid!r} added to the plan.")
            except ConfigError as exc:
                st.error(f"Rule invalid: {exc}")
    return get_config()


def _wrap_rule(rule_yaml: str) -> str:
    """Wrap a single rule's YAML mapping into a full config document."""
    indented = rule_yaml.rstrip("\n").replace("\n", "\n    ")
    return 'version: "1.0"\nname: ui-draft\nrules:\n  - ' + indented + "\n"


def _merge_rule(current, rule):
    from data_cleaning_toolkit.config.schema import CleaningConfig

    rules = list(current.rules) if current is not None else []
    rules.extend(rule.rules)
    name = current.name if current is not None else "ui-draft"
    desc = current.description if current is not None else "Built in the Cleaning Studio"
    return CleaningConfig(name=name, description=desc, rules=rules)


# ---------------------------------------------------------------------------
# preview tab
# ---------------------------------------------------------------------------


def _preview_tab(ds) -> None:
    cfg = get_config()
    if cfg is None:
        empty_state("Configure a plan first (tab 1).", "Tip: start from the 'example:' profiles.")
        return
    if st.button("🔍 Run preview (dry run)", type="primary"):
        engine = CleaningEngine(cfg, source_metadata=ds.metadata.to_dict())
        with st.spinner("Analyzing..."):
            preview = engine.preview(ds.dataframe)
        st.session_state["dtk_preview"] = preview
    preview = st.session_state.get("dtk_preview")
    if preview is None:
        empty_state("No preview yet. Press **Run preview** to see exactly what "
                    "would change - nothing is written.")
        return
    s = preview.summary()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Rows", f"{s['rows_in']:,} → {s['rows_out']:,}")
    c2.metric("Cells changed", f"{s['cells_changed']:,}")
    c3.metric("Rows removed", f"{s['rows_removed']:,}")
    c4.metric("Flagged", f"{s['flags']:,}")
    c5.metric("Rules", s["rules_executed"])

    frame = preview.outcomes_frame()
    st.dataframe(frame, width="stretch", hide_index=True)

    for o in preview.outcomes:
        if o.examples:
            with st.expander(f"Before / after - {o.rule_id} ({len(o.examples)} example(s))"):
                st.dataframe(
                    pd.DataFrame(o.examples)[["row", "column", "before", "after", "reason"]],
                    width="stretch",
                    hide_index=True,
                )
    for o in preview.outcomes:
        for w in o.warnings:
            st.warning(f"{o.rule_id}: {w}")
    if preview.flags:
        with st.expander(f"Flagged values ({preview.flags}) - shown for review, "
                         "rules never modify these"):
            flags = pd.DataFrame(
                [
                    {"rule": f.rule_id, "row": f.row, "column": f.column,
                     "value": f.value, "message": f.message}
                    for f in preview.audit.flags[:500]
                ]
            )
            st.dataframe(flags, width="stretch", hide_index=True)
    if s.get("stopped_early"):
        st.error(f"A rule failed during preview: {s.get('error')}")


# ---------------------------------------------------------------------------
# apply tab
# ---------------------------------------------------------------------------


def _apply_tab(ds) -> None:
    cfg = get_config()
    if cfg is None:
        empty_state("Configure a plan first (tab 1).")
        return
    preview = st.session_state.get("dtk_preview")
    if preview is not None:
        s = preview.summary()
        st.markdown(
            f"<div class='dtk-note'>Preview estimate: <b>{s['cells_changed']:,}</b> cells "
            f"would change, <b>{s['rows_removed']:,}</b> rows removed, "
            f"<b>{s['flags']:,}</b> values flagged. Applying runs exactly this plan."
            "</div>",
            unsafe_allow_html=True,
        )
    confirm = st.checkbox(
        "I reviewed the preview and approve these transformations",
        help="Applying never touches your source file: the cleaned dataset and "
        "a full audit trail are written to the local workspace.",
    )
    fmt = st.selectbox("Output format", ["csv", "xlsx", "json"],
                       index=["csv", "xlsx", "json"].index(
                           st.session_state["dtk_settings"].get("export_fmt", "csv")))
    st.session_state["dtk_settings"]["export_fmt"] = fmt

    if not confirm:
        empty_state("Tick the approval box to enable Apply.")
        return
    if st.button("▶️ Apply cleaning", type="primary"):
        from data_cleaning_toolkit.config.schema import AuditConfig, CleaningConfig, ExportConfig

        export = ExportConfig(fmt=fmt, directory="cleaned")
        audit = AuditConfig(
            max_change_records=cfg.audit.max_change_records,
            key_columns=cfg.audit.key_columns,
            redact_columns=cfg.audit.redact_columns,
            write_excel_workbook=st.session_state["dtk_settings"].get("excel_audit_workbook", False),
        )
        run_cfg = CleaningConfig(
            version=cfg.version, name=cfg.name, description=cfg.description,
            import_options=cfg.import_options, source=cfg.source,
            rules=list(cfg.rules), export=export, limits=cfg.limits, audit=audit,
        )
        engine = CleaningEngine(run_cfg, source_metadata=ds.metadata.to_dict())
        with st.spinner("Applying approved rules..."):
            result = engine.apply(ds.dataframe)
        if result.stopped_early:
            st.error(f"Run stopped early: {result.error}")
            st.session_state["dtk_result"] = result
            return
        try:
            from data_cleaning_toolkit.exporters.exporters import export_dataframe

            export_result = export_dataframe(
                result.dataframe, runs_dir(), sanitize_filename(ds.name), run_cfg
            )
            run_dir = save_run(
                result,
                output_dir=runs_dir(),
                dataset_name=ds.name,
                exported_path=export_result.path if export_result else None,
                export_result=export_result,
                profile=st.session_state.get("dtk_profile"),
            )
        except Exception as exc:  # noqa: BLE001 - surface any export problem
            st.error(f"Run completed but saving artifacts failed: {exc}")
            run_dir = None
        st.session_state["dtk_result"] = result
        st.session_state["dtk_run_dir"] = run_dir
        st.rerun()

    result = st.session_state.get("dtk_result")
    if result is None:
        return
    s = result.summary()
    if s.get("stopped_early"):
        st.error(f"Last run stopped early: {s.get('error')}")
        return
    st.success(
        f"Applied: {s['rows_in']:,} → {s['rows_out']:,} rows, "
        f"{s['cells_changed']:,} cells changed, {s['flags']:,} flagged. "
        "Open **Before vs After** to compare, or **Reports & Audit** to download."
    )
    st.dataframe(result.outcomes_frame(), width="stretch", hide_index=True)
