"""Session state helpers for the Streamlit dashboard.

All heavy objects (datasets, profiles, cleaning results) live in
``st.session_state`` under keys prefixed ``dtk_`` so they survive Streamlit
reruns. The dashboard never keeps its own copy of the cleaning logic - it
always calls the library.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import streamlit as st

APP_DIR = os.path.dirname(os.path.abspath(__file__))


def workspace_dir() -> str:
    """Local scratch workspace for uploads, runs and saved profiles."""
    root = os.environ.get("DTK_WORKSPACE", os.path.join(os.getcwd(), "dtk_workspace"))
    os.makedirs(root, exist_ok=True)
    for sub in ("uploads", "runs", "profiles"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    return root


def uploads_dir() -> str:
    return os.path.join(workspace_dir(), "uploads")


def runs_dir() -> str:
    return os.path.join(workspace_dir(), "runs")


def saved_profiles_dir() -> str:
    return os.path.join(workspace_dir(), "profiles")


def ensure_app_importable() -> None:
    if APP_DIR not in sys.path:
        sys.path.insert(0, APP_DIR)


def init_state() -> None:
    defaults = {
        "dtk_dataset": None,  # data_cleaning_toolkit.readers.base.Dataset
        "dtk_profile": None,  # ProfileReport
        "dtk_config": None,  # CleaningConfig
        "dtk_config_name": None,
        "dtk_preview": None,  # CleanResult (preview)
        "dtk_result": None,  # CleanResult (applied)
        "dtk_settings": {
            "encoding": "auto",
            "delimiter": "auto",
            "header_row": 0,
            "export_fmt": "csv",
            "redact": False,
            "excel_audit_workbook": False,
        },
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def get_dataset():
    return st.session_state.get("dtk_dataset")


def get_config():
    return st.session_state.get("dtk_config")


def set_dataset(dataset: Any, profile: Any) -> None:
    st.session_state["dtk_dataset"] = dataset
    st.session_state["dtk_profile"] = profile
    # a new dataset invalidates previews/results
    st.session_state["dtk_preview"] = None
    st.session_state["dtk_result"] = None


def set_config(config: Any, name: str | None = None) -> None:
    st.session_state["dtk_config"] = config
    st.session_state["dtk_config_name"] = name
    st.session_state["dtk_preview"] = None


def clear_all() -> None:
    for key in ("dtk_dataset", "dtk_profile", "dtk_config", "dtk_config_name",
                "dtk_preview", "dtk_result"):
        st.session_state[key] = None


def list_local_runs(limit: int = 50) -> list[dict[str, Any]]:
    """Scan the workspace runs directory for manifests (newest first)."""
    import json

    runs: list[dict[str, Any]] = []
    base = runs_dir()
    if not os.path.isdir(base):
        return runs
    for name in os.listdir(base):
        manifest_path = os.path.join(base, name, "manifest.json")
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, encoding="utf-8") as fh:
                    m = json.load(fh)
                m["_dir"] = os.path.join(base, name)
                runs.append(m)
            except (json.JSONDecodeError, OSError):
                continue
    runs.sort(key=lambda m: m.get("finished_at", m.get("run_id", "")), reverse=True)
    return runs[:limit]
