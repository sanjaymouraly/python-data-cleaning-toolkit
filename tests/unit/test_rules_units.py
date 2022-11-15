"""Unit normalization tests: mass/length/temperature, safety on unknown units."""

from __future__ import annotations

import pandas as pd

from data_cleaning_toolkit import CleaningEngine


def run(simple_cfg, df, rules):
    return CleaningEngine(simple_cfg(rules)).apply(df)


class TestMass:
    def test_kg_to_g(self, simple_cfg):
        df = pd.DataFrame({"w": ["2.5"], "u": ["kg"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "unit_normalize",
                    "value_column": "w",
                    "unit_column": "u",
                    "category": "mass",
                    "target_unit": "g",
                    "rounding_digits": 2,
                }
            ],
        )
        assert float(res.dataframe["w"].iloc[0]) == 2500.0
        assert res.dataframe["u"].iloc[0] == "g"

    def test_g_to_lb(self, simple_cfg):
        df = pd.DataFrame({"w": [453.59237], "u": ["g"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "unit_normalize",
                    "value_column": "w",
                    "unit_column": "u",
                    "category": "mass",
                    "target_unit": "lb",
                    "rounding_digits": 3,
                }
            ],
        )
        assert float(res.dataframe["w"].iloc[0]) == 1.0

    def test_mixed_units_all_converted(self, simple_cfg):
        df = pd.DataFrame({"w": ["1", "1000"], "u": ["kg", "g"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "unit_normalize",
                    "value_column": "w",
                    "unit_column": "u",
                    "category": "mass",
                    "target_unit": "g",
                }
            ],
        )
        assert list(res.dataframe["w"]) == [1000.0, 1000.0]

    def test_unknown_unit_flagged_not_converted(self, simple_cfg):
        df = pd.DataFrame({"w": ["5"], "u": ["stones"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "unit_normalize",
                    "value_column": "w",
                    "unit_column": "u",
                    "category": "mass",
                    "target_unit": "g",
                }
            ],
        )
        assert res.summary()["flags"] == 1
        assert float(res.dataframe["w"].iloc[0]) == 5.0  # untouched

    def test_missing_unit_flagged(self, simple_cfg):
        df = pd.DataFrame({"w": ["5"], "u": [None]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "unit_normalize",
                    "value_column": "w",
                    "unit_column": "u",
                    "category": "mass",
                    "target_unit": "g",
                }
            ],
        )
        assert res.summary()["flags"] == 1

    def test_fixed_source_unit(self, simple_cfg):
        df = pd.DataFrame({"w": ["3"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "unit_normalize",
                    "value_column": "w",
                    "source_unit": "kg",
                    "category": "mass",
                    "target_unit": "g",
                }
            ],
        )
        assert float(res.dataframe["w"].iloc[0]) == 3000.0


class TestLengthTemperature:
    def test_m_to_cm(self, simple_cfg):
        df = pd.DataFrame({"d": [1.5], "u": ["m"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "unit_normalize",
                    "value_column": "d",
                    "unit_column": "u",
                    "category": "length",
                    "target_unit": "cm",
                }
            ],
        )
        assert float(res.dataframe["d"].iloc[0]) == 150.0

    def test_fahrenheit_to_celsius(self, simple_cfg):
        df = pd.DataFrame({"t": [32.0], "u": ["F"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "unit_normalize",
                    "value_column": "t",
                    "unit_column": "u",
                    "category": "temperature",
                    "target_unit": "c",
                }
            ],
        )
        assert float(res.dataframe["t"].iloc[0]) == 0.0

    def test_kelvin_to_celsius(self, simple_cfg):
        df = pd.DataFrame({"t": [273.15], "u": ["k"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "unit_normalize",
                    "value_column": "t",
                    "unit_column": "u",
                    "category": "temperature",
                    "target_unit": "c",
                }
            ],
        )
        assert float(res.dataframe["t"].iloc[0]) == 0.0

    def test_cross_category_conversion_is_validated_away(self, simple_cfg):
        # target unit from wrong category is rejected at config time
        try:
            run(
                simple_cfg,
                pd.DataFrame({"d": [1], "u": ["m"]}),
                [
                    {
                        "type": "unit_normalize",
                        "value_column": "d",
                        "unit_column": "u",
                        "category": "length",
                        "target_unit": "kg",
                    }
                ],
            )
            raised = False
        except Exception:
            raised = True
        assert raised  # config/schema validation rejects it


class TestSafety:
    def test_non_numeric_value_flagged(self, simple_cfg):
        df = pd.DataFrame({"w": ["heavy"], "u": ["kg"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "unit_normalize",
                    "value_column": "w",
                    "unit_column": "u",
                    "category": "mass",
                    "target_unit": "g",
                }
            ],
        )
        assert res.summary()["flags"] == 1
        assert str(res.dataframe["w"].iloc[0]) == "heavy"

    def test_rounding_consistent(self, simple_cfg):
        df = pd.DataFrame({"w": [1.23456], "u": ["kg"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "unit_normalize",
                    "value_column": "w",
                    "unit_column": "u",
                    "category": "mass",
                    "target_unit": "g",
                    "rounding_digits": 1,
                }
            ],
        )
        assert float(res.dataframe["w"].iloc[0]) == 1234.6

    def test_idempotent_after_label_update(self, simple_cfg):
        df = pd.DataFrame({"w": ["2"], "u": ["kg"]})
        rule = [
            {
                "type": "unit_normalize",
                "value_column": "w",
                "unit_column": "u",
                "category": "mass",
                "target_unit": "g",
                "rounding_digits": 2,
            }
        ]
        once = run(simple_cfg, df, rule)
        twice = run(simple_cfg, once.dataframe, rule)
        assert once.dataframe.equals(twice.dataframe)
        assert twice.summary()["cells_changed"] == 0
