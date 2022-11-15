"""Type conversion tests: numerics, booleans, precision, leading zeros."""

from __future__ import annotations

import pandas as pd

from data_cleaning_toolkit import CleaningEngine


def run(simple_cfg, df, rules):
    return CleaningEngine(simple_cfg(rules)).apply(df)


class TestNumericConversion:
    def test_decimal_with_thousands(self, simple_cfg):
        df = pd.DataFrame({"v": ["1,234.50", "2"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "type_conversion",
                    "column": "v",
                    "target": "decimal",
                    "thousands_sep": ",",
                }
            ],
        )
        assert float(res.dataframe["v"].iloc[0]) == 1234.5

    def test_european_decimal_sep(self, simple_cfg):
        df = pd.DataFrame({"v": ["1.234,50", "2,5"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "type_conversion",
                    "column": "v",
                    "target": "decimal",
                    "thousands_sep": ".",
                    "decimal_sep": ",",
                }
            ],
        )
        assert float(res.dataframe["v"].iloc[0]) == 1234.5
        assert float(res.dataframe["v"].iloc[1]) == 2.5

    def test_invalid_flagged_not_silently_dropped(self, simple_cfg):
        df = pd.DataFrame({"v": ["1", "abc", "3"]})
        res = run(
            simple_cfg,
            df,
            [{"type": "type_conversion", "column": "v", "target": "decimal"}],
        )
        assert res.summary()["flags"] == 1
        assert str(res.dataframe["v"].iloc[1]) == "abc"  # untouched evidence
        assert float(res.dataframe["v"].iloc[0]) == 1.0

    def test_on_error_set_null(self, simple_cfg):
        df = pd.DataFrame({"v": ["1", "abc"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "type_conversion",
                    "column": "v",
                    "target": "decimal",
                    "on_error": "set_null",
                }
            ],
        )
        assert pd.isna(res.dataframe["v"].iloc[1])
        # both the "1"->1.0 conversion and the "abc"-><NA> set are recorded changes
        assert res.summary()["cells_changed"] == 2

    def test_on_error_remove_row(self, simple_cfg):
        df = pd.DataFrame({"id": [1, 2], "v": ["1", "abc"]})
        res = CleaningEngine(
            simple_cfg(
                [
                    {
                        "type": "type_conversion",
                        "column": "v",
                        "target": "decimal",
                        "on_error": "remove_row",
                    }
                ],
                audit={"key_columns": ["id"]},
            )
        ).apply(df)
        assert len(res.dataframe) == 1
        assert float(res.dataframe["v"].iloc[0]) == 1.0
        assert res.audit.removed_rows[0].key_values["id"] == "2"  # audit values are strings

    def test_on_error_fail_aborts(self, simple_cfg):
        df = pd.DataFrame({"v": ["abc"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "type_conversion",
                    "column": "v",
                    "target": "integer",
                    "on_error": "fail",
                }
            ],
        )
        assert res.stopped_early and "failed conversion" in res.error

    def test_integer_precision_loss_rejected(self, simple_cfg):
        df = pd.DataFrame({"v": ["5.5", "5.0"]})
        res = run(
            simple_cfg,
            df,
            [{"type": "type_conversion", "column": "v", "target": "integer"}],
        )
        assert res.summary()["flags"] == 1  # 5.5 would lose precision
        assert int(res.dataframe["v"].iloc[1]) == 5  # 5.0 is safe

    def test_overflow_rejected(self, simple_cfg):
        df = pd.DataFrame({"v": [str(2**70)]})
        res = run(
            simple_cfg,
            df,
            [{"type": "type_conversion", "column": "v", "target": "integer"}],
        )
        assert res.summary()["flags"] == 1

    def test_leading_zeros_protected(self, simple_cfg):
        df = pd.DataFrame({"zip": ["01234", "999"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "type_conversion",
                    "column": "zip",
                    "target": "integer",
                    "keep_leading_zeros": True,
                }
            ],
        )
        assert str(res.dataframe["zip"].iloc[0]) == "01234"
        assert any("leading zeros" in f.message for f in res.audit.flags)
        assert int(res.dataframe["zip"].iloc[1]) == 999

    def test_blank_becomes_na_not_zero(self, simple_cfg):
        df = pd.DataFrame({"v": ["", "  ", "3"]})
        res = run(
            simple_cfg,
            df,
            [{"type": "type_conversion", "column": "v", "target": "integer"}],
        )
        assert pd.isna(res.dataframe["v"].iloc[0])
        assert int(res.dataframe["v"].iloc[2]) == 3

    def test_missing_column_fails_clearly(self, simple_cfg):
        df = pd.DataFrame({"a": [1]})
        res = run(
            simple_cfg,
            df,
            [{"type": "type_conversion", "column": "nope", "target": "integer"}],
        )
        assert res.stopped_early and "not found" in res.error


class TestBooleanConversion:
    def test_boolean_variants(self, simple_cfg):
        df = pd.DataFrame({"paid": ["yes", "NO", "Y", "false", "1", "0"]})
        res = run(
            simple_cfg,
            df,
            [{"type": "type_conversion", "column": "paid", "target": "boolean"}],
        )
        got = res.dataframe["paid"].tolist()
        assert list(got) == [True, False, True, False, True, False]

    def test_invalid_boolean_flagged(self, simple_cfg):
        df = pd.DataFrame({"paid": ["maybe"]})
        res = run(
            simple_cfg,
            df,
            [{"type": "type_conversion", "column": "paid", "target": "boolean"}],
        )
        assert res.summary()["flags"] == 1

    def test_custom_true_false_values(self, simple_cfg):
        df = pd.DataFrame({"s": ["aktiv", "inaktiv"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "type_conversion",
                    "column": "s",
                    "target": "boolean",
                    "true_values": ["aktiv"],
                    "false_values": ["inaktiv"],
                }
            ],
        )
        assert list(res.dataframe["s"]) == [True, False]


class TestTextCategory:
    def test_leading_zeros_survive_text_conversion(self, simple_cfg):
        df = pd.DataFrame({"id": ["0012", 34]})
        res = run(
            simple_cfg,
            df,
            [{"type": "type_conversion", "column": "id", "target": "text"}],
        )
        assert list(res.dataframe["id"].astype(str)) == ["0012", "34"]

    def test_category_dtype(self, simple_cfg):
        df = pd.DataFrame({"c": ["a", "b", "a"]})
        res = run(
            simple_cfg,
            df,
            [{"type": "type_conversion", "column": "c", "target": "category"}],
        )
        assert str(res.dataframe["c"].dtype) == "category"

    def test_idempotent_on_clean_data(self, simple_cfg):
        df = pd.DataFrame({"v": ["1", "2", "3"]})
        rule = [{"type": "type_conversion", "column": "v", "target": "integer"}]
        once = run(simple_cfg, df, rule)
        twice = run(simple_cfg, once.dataframe, rule)
        assert once.dataframe.equals(twice.dataframe)
