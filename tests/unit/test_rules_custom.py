"""Custom rule tests: required, allowed, regex, unique, cross-column, conditional."""

from __future__ import annotations

import pandas as pd

from data_cleaning_toolkit import CleaningEngine


def run(simple_cfg, df, rules):
    return CleaningEngine(simple_cfg(rules)).apply(df)


class TestRequiredColumn:
    def test_empty_flagged(self, simple_cfg):
        df = pd.DataFrame({"a": ["x", "", None]})
        res = run(simple_cfg, df, [{"type": "required_column", "column": "a"}])
        assert res.summary()["flags"] == 2

    def test_remove_rows_action(self, simple_cfg):
        df = pd.DataFrame({"a": ["x", ""]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "required_column",
                    "column": "a",
                    "on_violation": "remove_rows",
                }
            ],
        )
        assert len(res.dataframe) == 1

    def test_set_null_action(self, simple_cfg):
        # empty strings are missing, not value violations; "z" is a real violation
        df = pd.DataFrame({"a": ["x", "", "z"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "allowed_values",
                    "column": "a",
                    "values": ["x", "y"],
                    "on_violation": "set_null",
                }
            ],
        )
        assert str(res.dataframe["a"].iloc[0]) == "x"
        assert res.dataframe["a"].iloc[1] == "" or pd.isna(res.dataframe["a"].iloc[1])
        assert pd.isna(res.dataframe["a"].iloc[2])


class TestAllowedValues:
    def test_disallowed_flagged(self, simple_cfg):
        df = pd.DataFrame({"status": ["ok", "weird"]})
        res = run(
            simple_cfg,
            df,
            [{"type": "allowed_values", "column": "status", "values": ["ok"]}],
        )
        assert res.summary()["flags"] == 1

    def test_ignore_case(self, simple_cfg):
        df = pd.DataFrame({"status": ["OK"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "allowed_values",
                    "column": "status",
                    "values": ["ok"],
                    "ignore_case": True,
                }
            ],
        )
        assert res.summary()["flags"] == 0

    def test_missing_not_violation(self, simple_cfg):
        df = pd.DataFrame({"status": [None]})
        res = run(
            simple_cfg,
            df,
            [{"type": "allowed_values", "column": "status", "values": ["ok"]}],
        )
        assert res.summary()["flags"] == 0


class TestRegex:
    def test_pattern_violation(self, simple_cfg):
        df = pd.DataFrame({"zip": ["1234", "abc"]})
        res = run(
            simple_cfg,
            df,
            [{"type": "regex_match", "column": "zip", "pattern": "^[0-9]{4}$"}],
        )
        assert res.summary()["flags"] == 1

    def test_inverse_mode(self, simple_cfg):
        df = pd.DataFrame({"note": ["ok", "SPAM"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "regex_match",
                    "column": "note",
                    "pattern": "SPAM",
                    "inverse": True,
                }
            ],
        )
        assert res.summary()["flags"] == 1

    def test_empty_not_violation(self, simple_cfg):
        df = pd.DataFrame({"zip": [None, ""]})
        res = run(
            simple_cfg,
            df,
            [{"type": "regex_match", "column": "zip", "pattern": "^[0-9]{4}$"}],
        )
        assert res.summary()["flags"] == 0


class TestUniqueKey:
    def test_duplicate_keys_flagged(self, simple_cfg):
        df = pd.DataFrame({"k": ["a", "a", "b"]})
        res = run(simple_cfg, df, [{"type": "unique_key", "columns": ["k"]}])
        assert res.summary()["flags"] == 2  # both members of the dup group

    def test_composite_key(self, simple_cfg):
        # (a=1, b=1) appears twice -> both members of the duplicate group flagged
        df = pd.DataFrame({"a": [1, 1, 1], "b": [1, 2, 1]})
        res = run(
            simple_cfg, df, [{"type": "unique_key", "columns": ["a", "b"]}]
        )
        assert res.summary()["flags"] == 2

    def test_composite_key_all_unique(self, simple_cfg):
        df = pd.DataFrame({"a": [1, 1, 1], "b": [1, 2, 3]})
        res = run(
            simple_cfg, df, [{"type": "unique_key", "columns": ["a", "b"]}]
        )
        assert res.summary()["flags"] == 0

    def test_remove_action(self, simple_cfg):
        df = pd.DataFrame({"k": ["a", "a", "b"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "unique_key",
                    "columns": ["k"],
                    "on_violation": "remove_rows",
                }
            ],
        )
        assert list(res.dataframe["k"]) == ["b"]


class TestCrossColumn:
    def test_column_compare(self, simple_cfg):
        df = pd.DataFrame({"start": [1, 5], "end": [2, 3]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "cross_column",
                    "left": "start",
                    "operator": "<=",
                    "right_column": "end",
                }
            ],
        )
        assert res.summary()["flags"] == 1

    def test_factor_column_total_check(self, simple_cfg):
        df = pd.DataFrame({"total": [10.0, 99.0], "price": [2.0, 3.0], "qty": [5, 5]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "cross_column",
                    "left": "total",
                    "operator": "==",
                    "right_column": "price",
                    "factor_column": "qty",
                }
            ],
        )
        assert res.summary()["flags"] == 1

    def test_constant_compare(self, simple_cfg):
        df = pd.DataFrame({"amount": [0, 5]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "cross_column",
                    "left": "amount",
                    "operator": "!=",
                    "right_value": 0,
                }
            ],
        )
        assert res.summary()["flags"] == 1

    def test_missing_values_not_violations(self, simple_cfg):
        df = pd.DataFrame({"a": [None, 1], "b": [None, 2]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "cross_column",
                    "left": "a",
                    "operator": "<=",
                    "right_column": "b",
                }
            ],
        )
        assert res.summary()["flags"] == 0


class TestConditionalRequired:
    def test_violation_detected(self, simple_cfg):
        df = pd.DataFrame(
            {"manager": [None, "M1"], "seniority": ["senior", "junior"]}
        )
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "conditional_required",
                    "column": "manager",
                    "when_column": "seniority",
                    "when_operator": "==",
                    "when_value": "senior",
                }
            ],
        )
        assert res.summary()["flags"] == 1

    def test_not_operator(self, simple_cfg):
        df = pd.DataFrame(
            {"manager": [None, None], "seniority": ["junior", "senior"]}
        )
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "conditional_required",
                    "column": "manager",
                    "when_column": "seniority",
                    "when_operator": "!=",
                    "when_value": "senior",
                }
            ],
        )
        assert res.summary()["flags"] == 1  # only the junior row requires it

    def test_satisfied_no_flags(self, simple_cfg):
        df = pd.DataFrame({"manager": ["M"], "seniority": ["senior"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "conditional_required",
                    "column": "manager",
                    "when_column": "seniority",
                    "when_operator": "==",
                    "when_value": "senior",
                }
            ],
        )
        assert res.summary()["flags"] == 0
