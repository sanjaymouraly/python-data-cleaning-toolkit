"""Advanced CSV & Excel Data Cleaner - Streamlit dashboard entry point.

Run with:
    streamlit run app/app.py

Every page calls the real toolkit engine (no mocked results).
"""

from __future__ import annotations

import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from state import ensure_app_importable, init_state  # noqa: E402

ensure_app_importable()

import data_cleaning_toolkit  # noqa: E402
from state import get_dataset  # noqa: E402
from ui import inject_css  # noqa: E402

st.set_page_config(
    page_title="Data Cleaning Toolkit",
    page_icon="🧼",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_state()
inject_css()

PAGES = [
    ("Dashboard", "views.dashboard"),
    ("Upload & Import", "views.import_page"),
    ("Data Profiling", "views.profiling"),
    ("Cleaning Studio", "views.studio"),
    ("Before vs After", "views.compare"),
    ("Reports & Audit", "views.reports"),
    ("Settings", "views.settings"),
]

# ---------------------------------------------------------------- sidebar ---
with st.sidebar:
    st.markdown(
        f"### 🧼 Data Cleaner\n"
        f"<span style='opacity:.6;font-size:.8rem'>v{data_cleaning_toolkit.__version__}"
        " · local & offline</span>",
        unsafe_allow_html=True,
    )
    ds = get_dataset()
    if ds is not None:
        shape = ds.shape
        st.markdown(
            f"<div class='dtk-note' style='margin-top:8px'>"
            f"<b>{ds.name}</b><br>{shape[0]:,} rows × {shape[1]:,} cols</div>",
            unsafe_allow_html=True,
        )
    page = st.radio("Navigation", [label for label, _ in PAGES], label_visibility="collapsed")
    st.divider()
    st.caption(
        "🔒 Files never leave this machine. Cleaning only applies rules you "
        "approve; previews never modify data."
    )

module_name = dict(PAGES)[page]
import importlib  # noqa: E402

module = importlib.import_module(module_name)
module.render()
