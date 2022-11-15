"""Duplicate rule tests: policies, keys, flag-only, idempotence."""

from __future__ import annotations

import pandas as pd

from data_cleaning_toolkit import CleaningEngine


def run(simple_cfg, df, rules):
    return CleaningEngine(simple_cfg(rules)).apply(df)


class TestPolicies:
    def test_keep_first(self, simple_cfg):
        df = pd.DataFrame({"a": [1, 1, 2], "b": ["x", "x", "y"]})
        res = run(simple_cfg, df, [{"type": "duplicates", "keep": "first"}])
        assert len(res.dataframe) == 2
        assert res.summary()["rows_removed"] == 1

    def test_keep_last_keeps_second(self, simple_cfg):
        # duplicates on key column "a"; note differs but is not part of the key
        df = pd.DataFrame({"a": [1, 1], "note": ["first", "second"]})
        res = run(
            simple_cfg,
            df,
            [{"type": "duplicates", "columns": ["a"], "keep": "last"}],
        )
        assert list(res.dataframe["note"]) == ["second"]

    def test_keep_last_full_row(self, simple_cfg):
        df = pd.DataFrame({"a": [1, 1]})
        res = run(simple_cfg, df, [{"type": "duplicates", "keep": "last"}])
        assert len(res.dataframe) == 1

    def test_keep_none_removes_all_copies(self, simple_cfg):
        df = pd.DataFrame({"a": [1, 1, 2]})
        res = run(simple_cfg, df, [{"type": "duplicates", "keep": "none"}])
        assert list(res.dataframe["a"]) == [2]

    def test_flag_only_modifies_nothing(self, simple_cfg):
        df = pd.DataFrame({"a": [1, 1, 2]})
        res = run(
            simple_cfg, df, [{"type": "duplicates", "keep": "first", "flag_only": True}]
        )
        assert len(res.dataframe) == 3
        assert res.summary()["flags"] == 1
        assert res.summary()["rows_removed"] == 0


class TestKeys:
    def test_key_columns(self, simple_cfg):
        df = pd.DataFrame(
            {"id": [1, 2, 3], "email": ["a@x", "a@x", "b@x"], "note": ["p", "q", "r"]}
        )
        res = run(
            simple_cfg, df, [{"type": "duplicates", "columns": ["email"], "keep": "first"}]
        )
        assert len(res.dataframe) == 2
        assert list(res.dataframe["note"]) == ["p", "r"]

    def test_ignore_case_and_strip(self, simple_cfg):
        df = pd.DataFrame({"e": [" A@x ", "a@x", "b@x"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "duplicates",
                    "columns": ["e"],
                    "keep": "first",
                    "ignore_case": True,
                    "strip_whitespace": True,
                }
            ],
        )
        assert len(res.dataframe) == 2

    def test_removed_group_reported(self, simple_cfg):
        df = pd.DataFrame({"id": ["k1", "k1"], "v": [1, 1]})
        res = CleaningEngine(
            simple_cfg([{"type": "duplicates"}], audit={"key_columns": ["id"]})
        ).apply(df)
        assert res.audit.removed_rows[0].key_values["id"] == "k1"


class TestProperties:
    def test_idempotent(self, simple_cfg):
        df = pd.DataFrame({"a": [1, 1, 2, 2, 3]})
        once = run(simple_cfg, df, [{"type": "duplicates"}])
        twice = run(simple_cfg, once.dataframe, [{"type": "duplicates"}])
        assert once.dataframe.equals(twice.dataframe)

    def test_no_duplicates_is_noop(self, simple_cfg):
        df = pd.DataFrame({"a": [1, 2, 3]})
        res = run(simple_cfg, df, [{"type": "duplicates"}])
        assert res.summary()["rows_removed"] == 0
        assert res.dataframe.equals(df)

    def test_preview_matches_apply(self, simple_cfg):
        df = pd.DataFrame({"a": [1, 1, 2], "b": [3, 3, 4]})
        cfg = simple_cfg([{"type": "duplicates"}])
        engine = CleaningEngine(cfg)
        prev, appl = engine.preview(df), engine.apply(df)
        assert prev.summary()["rows_removed"] == appl.summary()["rows_removed"]
        assert prev.dataframe.equals(appl.dataframe)
