"""Property-based tests for core cleaning invariants (Hypothesis)."""

from __future__ import annotations

import string

import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from data_cleaning_toolkit import CleaningEngine
from data_cleaning_toolkit.auditing.audit import AuditCollector
from data_cleaning_toolkit.cleaners.duplicates import DuplicatesRule
from data_cleaning_toolkit.cleaners.missing import MissingValuesRule
from data_cleaning_toolkit.cleaners.strings import StringStandardizeRule
from data_cleaning_toolkit.config.schema import (
    DuplicatesRuleConfig,
    MissingValuesRuleConfig,
    StringStandardizeRuleConfig,
)

text_values = st.text(alphabet=string.printable, max_size=20)


class TestStringInvariants:
    @given(values=st.lists(text_values, min_size=1, max_size=20))
    @settings(max_examples=40, deadline=None)
    def test_trim_is_idempotent(self, values):
        df = pd.DataFrame({"v": values})
        cfg = StringStandardizeRuleConfig(
            type="string_standardize", columns=["v"], trim_whitespace=True
        )
        rule = StringStandardizeRule(cfg, "s1")
        once = rule.apply(df.copy(), AuditCollector())
        twice = rule.apply(once.copy(), AuditCollector())
        pd.testing.assert_frame_equal(once, twice)

    @given(values=st.lists(text_values, min_size=1, max_size=20))
    @settings(max_examples=40, deadline=None)
    def test_trim_never_lengthens(self, values):
        df = pd.DataFrame({"v": values})
        cfg = StringStandardizeRuleConfig(
            type="string_standardize", columns=["v"], trim_whitespace=True
        )
        out = StringStandardizeRule(cfg, "s1").apply(df.copy(), AuditCollector())
        assert (out["v"].str.len() <= df["v"].str.len()).all()


class TestDuplicateInvariants:
    @given(data=st.data())
    @settings(max_examples=25, deadline=None)
    def test_keep_first_never_loses_unique_rows(self, data):
        n = data.draw(st.integers(min_value=1, max_value=30))
        values = data.draw(st.lists(st.integers(0, 5), min_size=n, max_size=n))
        df = pd.DataFrame({"a": values})
        cfg = DuplicatesRuleConfig(type="duplicates", keep="first")
        out = DuplicatesRule(cfg, "d1").apply(df.copy(), AuditCollector())
        assert set(out["a"]) == set(values)  # every distinct value survives
        assert not out.duplicated().any()

    @given(data=st.data())
    @settings(max_examples=25, deadline=None)
    def test_dedup_idempotent(self, data):
        n = data.draw(st.integers(min_value=1, max_value=30))
        values = data.draw(st.lists(st.integers(0, 9), min_size=n, max_size=n))
        df = pd.DataFrame({"a": values})
        cfg = DuplicatesRuleConfig(type="duplicates", keep="first")
        rule = DuplicatesRule(cfg, "d1")
        once = rule.apply(df.copy(), AuditCollector())
        twice = rule.apply(once.copy(), AuditCollector())
        pd.testing.assert_frame_equal(once, twice)


class TestMarkerInvariants:
    @given(values=st.lists(st.one_of(st.none(), text_values), min_size=1, max_size=20))
    @settings(max_examples=25, deadline=None)
    def test_retain_never_drops_rows(self, values):
        df = pd.DataFrame({"v": pd.Series(values, dtype=object)})
        cfg = MissingValuesRuleConfig(type="missing_values", strategy="retain")
        out = MissingValuesRule(cfg, "m1").apply(df.copy(), AuditCollector())
        assert len(out) == len(df)

    def test_zero_preserved_under_any_strategy(self):
        df = pd.DataFrame({"v": [0, "0", 1]})
        for strategy in ("retain", "fill_constant", "mean", "median", "mode"):
            cfg = MissingValuesRuleConfig(
                type="missing_values",
                strategy=strategy,
                columns=["v"],
                **({"fill_value": 99} if strategy == "fill_constant" else {}),
            )
            out = MissingValuesRule(cfg, "m").apply(df.copy(), AuditCollector())
            got = pd.to_numeric(out["v"], errors="coerce").dropna().tolist()
            assert 0.0 in got, f"zero lost under {strategy}"


class TestEngineInvariants:
    @given(data=st.data())
    @settings(max_examples=20, deadline=None)
    def test_preview_equals_apply(self, data):
        n = data.draw(st.integers(min_value=1, max_value=25))
        letters = data.draw(st.lists(st.sampled_from("abcxyz"), min_size=n, max_size=n))
        numbers = data.draw(st.lists(st.integers(-5, 5), min_size=n, max_size=n))
        df = pd.DataFrame({"t": letters, "n": numbers})
        cfg = CleaningEngine.__init__  # placeholder to keep lints calm
        from data_cleaning_toolkit import parse_config

        engine = CleaningEngine(
            parse_config(
                {
                    "version": "1.0",
                    "rules": [
                        {"type": "string_standardize", "columns": ["t"], "case": "upper"},
                        {"type": "duplicates"},
                    ],
                }
            )
        )
        prev = engine.preview(df)
        appl = engine.apply(df)
        pd.testing.assert_frame_equal(prev.dataframe, appl.dataframe)
