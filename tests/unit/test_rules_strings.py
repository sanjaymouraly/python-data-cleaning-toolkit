"""String standardization tests: trim, case, unicode, mappings."""

from __future__ import annotations

import pandas as pd
import pytest

from data_cleaning_toolkit import CleaningEngine


def run(simple_cfg, df, rules):
    return CleaningEngine(simple_cfg(rules)).apply(df)


class TestBasic:
    def test_trim(self, simple_cfg):
        df = pd.DataFrame({"n": ["  a  ", "b\t"]})
        res = run(
            simple_cfg,
            df,
            [{"type": "string_standardize", "columns": ["n"], "trim_whitespace": True}],
        )
        assert list(res.dataframe["n"]) == ["a", "b"]

    def test_collapse_internal(self, simple_cfg):
        df = pd.DataFrame({"n": ["a    b"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "string_standardize",
                    "columns": ["n"],
                    "collapse_internal_whitespace": True,
                }
            ],
        )
        assert res.dataframe["n"].iloc[0] == "a b"

    @pytest.mark.parametrize(
        "case,expected", [("lower", "abc"), ("upper", "ABC"), ("title", "Abc")]
    )
    def test_case_modes(self, simple_cfg, case, expected):
        df = pd.DataFrame({"n": ["aBc"]})
        res = run(
            simple_cfg,
            df,
            [{"type": "string_standardize", "columns": ["n"], "case": case}],
        )
        assert res.dataframe["n"].iloc[0] == expected

    def test_sentence_case(self, simple_cfg):
        df = pd.DataFrame({"n": ["HELLO WORLD"]})
        res = run(
            simple_cfg,
            df,
            [{"type": "string_standardize", "columns": ["n"], "case": "sentence"}],
        )
        assert res.dataframe["n"].iloc[0] == "Hello world"


class TestUnicode:
    def test_nfc_composes(self, simple_cfg):
        decomposed = "e\u0301cole"  # e + combining accent
        df = pd.DataFrame({"n": [decomposed]})
        res = run(
            simple_cfg,
            df,
            [{"type": "string_standardize", "columns": ["n"], "unicode_normalize": "NFC"}],
        )
        assert res.dataframe["n"].iloc[0] == "école"

    def test_nfkd_strips_compatibility_chars(self, simple_cfg):
        df = pd.DataFrame({"n": ["\uff21"]})  # fullwidth A
        res = run(
            simple_cfg,
            df,
            [{"type": "string_standardize", "columns": ["n"], "unicode_normalize": "NFKC"}],
        )
        assert res.dataframe["n"].iloc[0] == "A"


class TestMappings:
    def test_value_mappings(self, simple_cfg):
        df = pd.DataFrame({"s": ["compleated", "done"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "string_standardize",
                    "columns": ["s"],
                    "value_mappings": {"compleated": "completed"},
                }
            ],
        )
        assert list(res.dataframe["s"]) == ["completed", "done"]

    def test_mapping_ignore_case(self, simple_cfg):
        df = pd.DataFrame({"s": ["COMPLEATED"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "string_standardize",
                    "columns": ["s"],
                    "value_mappings": {"compleated": "completed"},
                    "mapping_ignore_case": True,
                }
            ],
        )
        assert res.dataframe["s"].iloc[0] == "completed"


class TestBoundaries:
    def test_unselected_columns_untouched(self, simple_cfg):
        df = pd.DataFrame({"keep": ["  X  "], "clean": ["  Y  "]})
        res = run(
            simple_cfg,
            df,
            [{"type": "string_standardize", "columns": ["clean"]}],
        )
        assert res.dataframe["keep"].iloc[0] == "  X  "
        assert res.dataframe["clean"].iloc[0] == "Y"

    def test_exclude_columns(self, simple_cfg):
        df = pd.DataFrame({"a": [" x "], "b": [" y "]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "string_standardize",
                    "columns": ["a", "b"],
                    "exclude_columns": ["b"],
                }
            ],
        )
        assert res.dataframe["b"].iloc[0] == " y "

    def test_apply_to_all_text(self, simple_cfg):
        df = pd.DataFrame({"a": [" x "], "b": [" y "]})
        res = run(
            simple_cfg,
            df,
            [{"type": "string_standardize", "apply_to_all_text": True}],
        )
        assert list(res.dataframe.iloc[0]) == ["x", "y"]

    def test_numeric_columns_skipped_with_warning(self, simple_cfg):
        df = pd.DataFrame({"v": [1, 2]})
        res = run(
            simple_cfg,
            df,
            [{"type": "string_standardize", "columns": ["v"]}],
        )
        assert list(res.dataframe["v"]) == [1, 2]
        assert any("not a text column" in w for o in res.outcomes for w in o.warnings)

    def test_missing_values_stay_missing(self, simple_cfg):
        df = pd.DataFrame({"n": [None, " a "]})
        res = run(
            simple_cfg,
            df,
            [{"type": "string_standardize", "columns": ["n"]}],
        )
        assert pd.isna(res.dataframe["n"].iloc[0])

    def test_idempotent(self, simple_cfg):
        df = pd.DataFrame({"n": ["  AbC  "]})
        rule = [
            {
                "type": "string_standardize",
                "columns": ["n"],
                "trim_whitespace": True,
                "case": "title",
            }
        ]
        once = run(simple_cfg, df, rule)
        twice = run(simple_cfg, once.dataframe, rule)
        assert once.dataframe.equals(twice.dataframe)
