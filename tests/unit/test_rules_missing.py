"""Missing-value rule tests: markers and every strategy."""

from __future__ import annotations

import pandas as pd

from data_cleaning_toolkit import CleaningEngine


def run(simple_cfg, df, rules):
    return CleaningEngine(simple_cfg(rules)).apply(df)


class TestMarkers:
    def test_markers_normalized_and_counted(self, simple_cfg):
        df = pd.DataFrame({"a": ["x", "N/A", "null", "5"]})
        res = run(simple_cfg, df, [{"type": "missing_values", "strategy": "retain"}])
        assert res.summary()["cells_changed"] == 2
        assert res.dataframe["a"].isna().sum() == 2

    def test_case_insensitive_default(self, simple_cfg):
        df = pd.DataFrame({"a": ["Unknown", "UNKNOWN", "ok"]})
        res = run(simple_cfg, df, [{"type": "missing_values", "strategy": "retain"}])
        assert res.summary()["cells_changed"] == 2

    def test_custom_markers(self, simple_cfg):
        df = pd.DataFrame({"a": ["x", "MISSING", "-999"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "missing_values",
                    "strategy": "retain",
                    "null_markers": ["MISSING", "-999"],
                    "case_insensitive_markers": False,
                }
            ],
        )
        assert res.summary()["cells_changed"] == 2

    def test_zero_is_never_missing(self, simple_cfg):
        df = pd.DataFrame({"a": [0, 1, 2]})
        res = run(simple_cfg, df, [{"type": "missing_values", "strategy": "retain"}])
        assert res.summary()["cells_changed"] == 0


class TestStrategies:
    def test_remove_rows_any(self, simple_cfg):
        df = pd.DataFrame({"a": ["1", None, "3"], "b": ["x", "y", None]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "missing_values",
                    "columns": ["a", "b"],
                    "strategy": "remove_rows",
                    "scope": "any",
                }
            ],
        )
        assert len(res.dataframe) == 1
        assert res.summary()["rows_removed"] == 2

    def test_remove_rows_all(self, simple_cfg):
        df = pd.DataFrame({"a": ["1", None, None], "b": ["x", None, None]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "missing_values",
                    "columns": ["a", "b"],
                    "strategy": "remove_rows",
                    "scope": "all",
                }
            ],
        )
        assert len(res.dataframe) == 1  # only rows where BOTH are missing go

    def test_removed_rows_have_provenance(self, simple_cfg):
        df = pd.DataFrame({"id": ["k1", "k2"], "a": ["1", None]})
        res = CleaningEngine(
            simple_cfg(
                [{"type": "missing_values", "columns": ["a"], "strategy": "remove_rows"}],
                audit={"key_columns": ["id"]},
            )
        ).apply(df)
        assert res.audit.removed_rows[0].key_values == {"id": "k2"}

    def test_remove_columns(self, simple_cfg):
        df = pd.DataFrame({"a": ["1", None], "b": ["x", "y"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "missing_values",
                    "columns": ["a"],
                    "strategy": "remove_columns",
                }
            ],
        )
        assert list(res.dataframe.columns) == ["b"]

    def test_fill_constant(self, simple_cfg):
        df = pd.DataFrame({"a": ["1", None, "3"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "missing_values",
                    "columns": ["a"],
                    "strategy": "fill_constant",
                    "fill_value": "missing",
                }
            ],
        )
        assert res.dataframe["a"].iloc[1] == "missing"

    def test_mean_fill(self, simple_cfg):
        df = pd.DataFrame({"a": ["1", None, "3"]})
        res = run(
            simple_cfg,
            df,
            [{"type": "missing_values", "columns": ["a"], "strategy": "mean"}],
        )
        assert float(res.dataframe["a"].iloc[1]) == 2.0

    def test_median_fill(self, simple_cfg):
        df = pd.DataFrame({"a": ["1", None, "100"]})
        res = run(
            simple_cfg,
            df,
            [{"type": "missing_values", "columns": ["a"], "strategy": "median"}],
        )
        assert float(res.dataframe["a"].iloc[1]) == 50.5  # median of [1, 100]

    def test_mode_fill(self, simple_cfg):
        df = pd.DataFrame({"a": ["x", "y", "x", None]})
        res = run(
            simple_cfg,
            df,
            [{"type": "missing_values", "columns": ["a"], "strategy": "mode"}],
        )
        assert res.dataframe["a"].iloc[3] == "x"

    def test_mean_fill_skips_text_columns_with_warning(self, simple_cfg):
        df = pd.DataFrame({"a": ["red", None, "blue"]})
        res = run(
            simple_cfg,
            df,
            [{"type": "missing_values", "columns": ["a"], "strategy": "mean"}],
        )
        assert res.dataframe["a"].iloc[1] is None or pd.isna(res.dataframe["a"].iloc[1])
        assert any("not numeric" in w for o in res.outcomes for w in o.warnings)

    def test_ffill(self, simple_cfg):
        df = pd.DataFrame({"a": ["1", None, None, "4"]})
        res = run(
            simple_cfg,
            df,
            [{"type": "missing_values", "columns": ["a"], "strategy": "ffill"}],
        )
        assert list(res.dataframe["a"]) == ["1", "1", "1", "4"]

    def test_bfill_leading_gap_flagged(self, simple_cfg):
        # bfill propagates from the NEXT valid value: the leading gap gets filled,
        # a trailing gap has nothing after it and must stay <NA> with a warning
        df = pd.DataFrame({"a": [None, "2", None]})
        res = run(
            simple_cfg,
            df,
            [{"type": "missing_values", "columns": ["a"], "strategy": "bfill"}],
        )
        assert res.dataframe["a"].iloc[0] == "2"
        assert pd.isna(res.dataframe["a"].iloc[2])
        assert any("remain" in w for o in res.outcomes for w in o.warnings)

    def test_retain_changes_nothing_but_markers(self, simple_cfg):
        df = pd.DataFrame({"a": ["1", None]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "missing_values",
                    "columns": ["a"],
                    "strategy": "retain",
                    "null_markers": ["-"],  # not present
                }
            ],
        )
        assert res.summary()["cells_changed"] == 0
        assert len(res.dataframe) == 2
