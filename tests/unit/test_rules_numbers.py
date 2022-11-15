"""Numeric validation tests: bounds, signs, precision, outliers."""

from __future__ import annotations

import pandas as pd

from data_cleaning_toolkit import CleaningEngine


def run(simple_cfg, df, rules):
    return CleaningEngine(simple_cfg(rules)).apply(df)


class TestBounds:
    def test_min_violation_flagged(self, simple_cfg):
        df = pd.DataFrame({"v": ["5", "-1"]})
        res = run(
            simple_cfg,
            df,
            [{"type": "numeric_validate", "columns": ["v"], "min": 0}],
        )
        assert res.summary()["flags"] == 1
        assert list(res.dataframe["v"]) == ["5", "-1"]  # values untouched

    def test_max_violation_flagged(self, simple_cfg):
        df = pd.DataFrame({"v": ["50", "5000"]})
        res = run(
            simple_cfg,
            df,
            [{"type": "numeric_validate", "columns": ["v"], "max": 100}],
        )
        assert res.summary()["flags"] == 1

    def test_negative_disallowed(self, simple_cfg):
        df = pd.DataFrame({"v": ["-3", "3"]})
        res = run(
            simple_cfg,
            df,
            [{"type": "numeric_validate", "columns": ["v"], "allow_negative": False}],
        )
        assert res.summary()["flags"] == 1

    def test_decimal_disallowed(self, simple_cfg):
        df = pd.DataFrame({"qty": ["2.5", "2"]})
        res = run(
            simple_cfg,
            df,
            [{"type": "numeric_validate", "columns": ["qty"], "allow_decimal": False}],
        )
        assert res.summary()["flags"] == 1

    def test_on_invalid_remove_rows(self, simple_cfg):
        df = pd.DataFrame({"id": [1, 2], "v": ["-5", "10"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "numeric_validate",
                    "columns": ["v"],
                    "allow_negative": False,
                    "on_invalid": "remove_rows",
                }
            ],
        )
        assert len(res.dataframe) == 1

    def test_unparseable_flagged(self, simple_cfg):
        df = pd.DataFrame({"v": ["abc", "5"]})
        res = run(
            simple_cfg,
            df,
            [{"type": "numeric_validate", "columns": ["v"]}],
        )
        assert res.summary()["flags"] == 1

    def test_separators_parsed(self, simple_cfg):
        df = pd.DataFrame({"v": ["1.234,50"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "numeric_validate",
                    "columns": ["v"],
                    "min": 1000,
                    "thousands_sep": ".",
                    "decimal_sep": ",",
                }
            ],
        )
        assert res.summary()["flags"] == 0


class TestOutliers:
    def test_iqr_outliers_flagged(self, simple_cfg):
        df = pd.DataFrame({"v": [10, 11, 12, 13, 12, 11, 500]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "numeric_validate",
                    "columns": ["v"],
                    "outlier_method": "iqr",
                }
            ],
        )
        assert res.summary()["flags"] == 1
        assert list(res.dataframe["v"]) == [10, 11, 12, 13, 12, 11, 500]  # kept

    def test_zscore_outliers_flagged(self, simple_cfg):
        df = pd.DataFrame({"v": [10.0] * 30 + [1000.0]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "numeric_validate",
                    "columns": ["v"],
                    "outlier_method": "zscore",
                }
            ],
        )
        assert res.summary()["flags"] == 1

    def test_outlier_removal_is_explicit(self, simple_cfg):
        df = pd.DataFrame({"v": [10, 11, 12, 13, 12, 11, 500]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "numeric_validate",
                    "columns": ["v"],
                    "outlier_method": "iqr",
                    "outlier_action": "remove_rows",
                }
            ],
        )
        assert 500 not in list(res.dataframe["v"])

    def test_no_outliers_in_clean_data(self, simple_cfg):
        df = pd.DataFrame({"v": [10, 11, 12, 13]})
        res = run(
            simple_cfg,
            df,
            [{"type": "numeric_validate", "columns": ["v"], "outlier_method": "iqr"}],
        )
        assert res.summary()["flags"] == 0


class TestEdgeCases:
    def test_missing_values_ignored(self, simple_cfg):
        df = pd.DataFrame({"v": [None, "5"]})
        res = run(
            simple_cfg,
            df,
            [{"type": "numeric_validate", "columns": ["v"], "min": 0}],
        )
        assert res.summary()["flags"] == 0

    def test_non_numeric_column_skipped_with_warning(self, simple_cfg):
        # datetime columns are neither text nor numeric for this rule: skipped
        df = pd.DataFrame(
            {"t": pd.to_datetime(["2026-01-01"]), "v": ["5"]}
        )
        res = run(
            simple_cfg,
            df,
            [{"type": "numeric_validate", "columns": ["t", "v"]}],
        )
        assert any("skipped" in w for o in res.outcomes for w in o.warnings)

    def test_text_junk_flagged_not_skipped(self, simple_cfg):
        df = pd.DataFrame({"t": ["abc"], "v": ["5"]})
        res = run(
            simple_cfg,
            df,
            [{"type": "numeric_validate", "columns": ["t", "v"]}],
        )
        assert res.summary()["flags"] == 1

    def test_missing_column_fails(self, simple_cfg):
        df = pd.DataFrame({"a": [1]})
        res = run(
            simple_cfg,
            df,
            [{"type": "numeric_validate", "columns": ["ghost"]}],
        )
        assert res.stopped_early and "not found" in res.error
