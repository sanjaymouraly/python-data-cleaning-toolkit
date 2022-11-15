"""Shared fixtures for the test suite."""

from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO_ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from data_cleaning_toolkit import parse_config  # noqa: E402


@pytest.fixture()
def dirty_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": ["001", "002", "003", "004", "005", "006"],
            "name": ["  Alice  ", "BOB", None, "  Alice  ", "Dave", "Eve"],
            "amount": ["1,234.50", "100.00", "N/A", "1,234.50", "-5.00", "x"],
            "qty": ["3", "0", "", "3", "2", "7"],
            "signed_up": ["2026-01-15", "15/02/2026", "2026-03-30", "2026-01-15",
                          "not-a-date", ""],
            "category": [" A ", "b", "A", " a ", "C", "b"],
        }
    )


@pytest.fixture()
def tmp_csv(tmp_path):
    """Write a small dirty CSV and return its path."""

    def _write(df: pd.DataFrame, name: str = "data.csv", **kwargs) -> str:
        path = tmp_path / name
        df.to_csv(path, index=False, **kwargs)
        return str(path)

    return _write


@pytest.fixture()
def simple_cfg():
    def _cfg(rules: list[dict], **kwargs):
        payload = {"version": "1.0", "name": "test", "rules": rules}
        if "audit" in kwargs:
            payload["audit"] = kwargs.pop("audit")
        payload.update(kwargs)
        return parse_config(payload)

    return _cfg
