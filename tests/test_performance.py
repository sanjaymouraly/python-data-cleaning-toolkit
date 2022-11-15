"""Performance characterization tests (marked slow; run with -m slow).

These use a 200k-row generated CSV to measure real throughput on this
machine and to guard against accidental algorithmic regressions. The
numbers are informational and printed for documentation purposes.
"""

from __future__ import annotations

import time

import pandas as pd
import pytest

from data_cleaning_toolkit import CleaningEngine, parse_config, profile_dataset

pytestmark = pytest.mark.slow

N_ROWS = 200_000


@pytest.fixture(scope="module")
def big_df():
    import numpy as np

    rng = np.random.default_rng(7)
    return pd.DataFrame(
        {
            "transaction_id": [f"T{i}" for i in range(N_ROWS)],
            "amount": rng.uniform(-500, 5000, size=N_ROWS).round(2).astype(str),
            "quantity": rng.integers(1, 10, size=N_ROWS).astype(str),
            "region": rng.choice(["north", "south", "east", "west"], size=N_ROWS),
            "order_date": pd.date_range("2025-01-01", periods=N_ROWS, freq="min").strftime(
                "%Y-%m-%d"
            ),
        }
    )


CFG = parse_config(
    {
        "version": "1.0",
        "name": "perf",
        "rules": [
            {"type": "string_standardize", "columns": ["region"], "case": "lower"},
            {"type": "date_normalize", "columns": ["order_date"]},
            {"type": "type_conversion", "column": "amount", "target": "decimal"},
            {"type": "type_conversion", "column": "quantity", "target": "integer"},
            {"type": "numeric_validate", "columns": ["amount"], "min": 0},
            {"type": "duplicates"},
        ],
    }
)


def test_200k_rows_within_budget(big_df):
    t0 = time.perf_counter()
    profile = profile_dataset(big_df)
    t_profile = time.perf_counter() - t0

    engine = CleaningEngine(CFG)
    t0 = time.perf_counter()
    result = engine.apply(big_df)
    t_apply = time.perf_counter() - t0

    assert len(result.dataframe) == N_ROWS
    rate = N_ROWS / t_apply
    print(
        f"\n[perf] profile: {t_profile:.2f}s, apply: {t_apply:.2f}s "
        f"({rate:,.0f} rows/s) on {N_ROWS:,} rows"
    )
    # generous budget for CI machines: at least 10k rows/s end to end
    assert rate > 10_000


def test_preview_equals_apply_on_large_data(big_df):
    engine = CleaningEngine(CFG)
    prev = engine.preview(big_df)
    appl = engine.apply(big_df)
    assert prev.summary()["cells_changed"] == appl.summary()["cells_changed"]


def test_memory_stays_bounded(big_df):
    """The engine must not balloon memory unreasonably (heuristic check)."""
    import tracemalloc

    tracemalloc.start()
    result = CleaningEngine(CFG).apply(big_df)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f"\n[perf] peak traced memory: {peak / 1048576:.0f} MB")
    # peak under ~12x input frame size (input frame itself is ~60-80 MB deep)
    assert peak < 12 * big_df.memory_usage(deep=True).sum()
