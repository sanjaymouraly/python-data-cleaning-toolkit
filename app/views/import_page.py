"""Upload & Import page: file upload, sheet/import options, data preview."""

from __future__ import annotations

import os

import streamlit as st

from data_cleaning_toolkit import DataImportError, LimitExceededError, UnsupportedFormatError, profile_dataset
from data_cleaning_toolkit.readers.base import Dataset
from data_cleaning_toolkit.readers.csv_reader import read_csv
from data_cleaning_toolkit.readers.excel_reader import list_sheets, read_excel
from state import init_state, set_dataset, uploads_dir
from ui import empty_state, hero, inject_css

ALLOWED_TYPES = ["csv", "txt", "tsv", "xlsx"]


def render() -> None:
    inject_css()
    hero(
        "Upload & Import",
        "Load a CSV or Excel file. Files are stored in a local workspace "
        "folder and never leave this machine.",
    )
    init_state()
    settings = st.session_state["dtk_settings"]

    left, right = st.columns([1, 2])
    with left:
        upload = st.file_uploader(
            "Drop a file here",
            type=ALLOWED_TYPES,
            help="CSV, TSV, TXT or XLSX. Large files are limited by the "
            "configured size cap (Settings).",
        )
        if upload is not None:
            size_mb = upload.size / 1048576
            st.caption(f"{upload.name} · {size_mb:.2f} MB")
            if st.button("Load dataset", type="primary", width="stretch"):
                _load(upload, settings)
    with right:
        st.markdown("**Import options**")
        enc_options = ["auto", "utf-8-sig", "utf-8", "cp1252", "latin-1"]
        settings["encoding"] = st.selectbox(
            "Encoding (CSV)", enc_options,
            help="'auto' tries UTF-8/BOM first, then cp1252/latin-1.",
        )
        delim_options = ["auto", ",", ";", "\t", "|"]
        settings["delimiter"] = st.selectbox("Delimiter (CSV)", delim_options)
        settings["header_row"] = st.number_input(
            "Header row (0-based)", min_value=0, max_value=50, value=0, step=1
        )
        st.caption("Options apply the next time you press **Load dataset**.")

    ds = st.session_state.get("dtk_dataset")
    if ds is None:
        empty_state(
            "No dataset loaded yet. Upload a file and press **Load dataset**, "
            "or try an example from examples/data/ "
            "(sales_transactions.csv, inventory.xlsx, customer_contacts.csv, "
            "workforce_report.csv, freelancer_income_expenses.xlsx)."
        )
        return

    # worksheet switcher for multi-sheet workbooks
    if ds.metadata.fmt == "xlsx" and os.path.exists(ds.metadata.path):
        sheets = list_sheets(ds.metadata.path)
        if len(sheets) > 1:
            idx = sheets.index(ds.metadata.sheet) if ds.metadata.sheet in sheets else 0
            chosen = st.selectbox("Worksheet", sheets, index=idx)
            if chosen != ds.metadata.sheet:
                options = _build_options(settings)
                try:
                    new_ds = read_excel(ds.metadata.path, sheet=chosen, options=options)
                    set_dataset(new_ds, profile_dataset(new_ds.dataframe))
                    st.rerun()
                except (DataImportError, LimitExceededError) as exc:
                    st.error(f"Switching sheets failed: {exc}")

    st.divider()
    meta = ds.metadata
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rows", f"{ds.shape[0]:,}")
    c2.metric("Columns", ds.shape[1])
    c3.metric("Source size", f"{meta.size_bytes / 1024:.1f} KB")
    enc = meta.encoding or "n/a"
    delim = f" · delim {meta.delimiter!r}" if meta.delimiter else ""
    c4.metric("Encoding", enc + delim if len(enc + delim) < 24 else enc)
    for w in [*meta.import_warnings, *meta.workbook_warnings]:
        st.warning(w)
    st.caption(f"sha256: `{meta.sha256}`")

    st.markdown("**Data preview (first 100 rows)**")
    st.dataframe(ds.head(100), width="stretch")
    with st.expander("Column names & pandas dtypes"):
        st.write({str(c): str(t) for c, t in ds.dataframe.dtypes.items()})


def _load(upload, settings) -> None:
    os.makedirs(uploads_dir(), exist_ok=True)
    from data_cleaning_toolkit.exporters.exporters import sanitize_filename

    name = sanitize_filename(upload.name)
    path = os.path.join(uploads_dir(), name)
    with open(path, "wb") as fh:
        fh.write(upload.getbuffer())

    ext = os.path.splitext(name)[1].lower()
    try:
        sheet = None
        if ext == ".xlsx":
            sheets = list_sheets(path)
            sheet = st.session_state.get("dtk_pending_sheet")
            if sheet is None and len(sheets) > 1:
                sheet = sheets[0]
        options = _build_options(settings)
        if ext == ".xlsx":
            ds: Dataset = read_excel(path, sheet=sheet or None, options=options)
        else:
            ds = read_csv(path, options=options)
    except (DataImportError, LimitExceededError, UnsupportedFormatError) as exc:
        st.error(f"Import failed: {exc}")
        return
    profile = profile_dataset(ds.dataframe)
    set_dataset(ds, profile)
    st.session_state["dtk_pending_sheet"] = None
    st.rerun()


def _build_options(settings):
    from data_cleaning_toolkit.config.schema import ImportOptionsConfig

    kwargs: dict = {"header_row": int(settings.get("header_row", 0))}
    if settings.get("encoding") not in (None, "auto"):
        kwargs["encoding"] = settings["encoding"]
    if settings.get("delimiter") not in (None, "auto"):
        kwargs["delimiter"] = settings["delimiter"]
    return ImportOptionsConfig(**kwargs)
