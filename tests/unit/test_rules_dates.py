"""Date normalization tests: ISO, formats, ambiguity, invalid dates, tz."""

from __future__ import annotations

import pandas as pd

from data_cleaning_toolkit import CleaningEngine


def run(simple_cfg, df, rules):
    return CleaningEngine(simple_cfg(rules)).apply(df)


class TestParsing:
    def test_iso_normalized(self, simple_cfg):
        df = pd.DataFrame({"d": ["2026-03-04", "2026-03-05"]})
        res = run(simple_cfg, df, [{"type": "date_normalize", "columns": ["d"]}])
        assert list(res.dataframe["d"]) == ["2026-03-04", "2026-03-05"]

    def test_iso_with_time(self, simple_cfg):
        df = pd.DataFrame({"d": ["2026-03-04T15:30:00"]})
        res = run(simple_cfg, df, [{"type": "date_normalize", "columns": ["d"]}])
        assert res.dataframe["d"].iloc[0] == "2026-03-04"

    def test_explicit_formats(self, simple_cfg):
        df = pd.DataFrame({"d": ["04.03.2026", "05.03.2026"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "date_normalize",
                    "columns": ["d"],
                    "input_formats": ["%d.%m.%Y"],
                }
            ],
        )
        assert list(res.dataframe["d"]) == ["2026-03-04", "2026-03-05"]

    def test_textual_month_names(self, simple_cfg):
        df = pd.DataFrame({"d": ["March 4, 2026", "12 December 2025"]})
        res = run(simple_cfg, df, [{"type": "date_normalize", "columns": ["d"]}])
        assert list(res.dataframe["d"]) == ["2026-03-04", "2025-12-12"]

    def test_custom_output_format(self, simple_cfg):
        df = pd.DataFrame({"d": ["2026-03-04"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "date_normalize",
                    "columns": ["d"],
                    "output_format": "%d/%m/%Y",
                }
            ],
        )
        assert res.dataframe["d"].iloc[0] == "04/03/2026"

    def test_datetime_output_type(self, simple_cfg):
        df = pd.DataFrame({"d": ["2026-03-04"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "date_normalize",
                    "columns": ["d"],
                    "output_type": "date",
                }
            ],
        )
        assert isinstance(res.dataframe["d"].iloc[0], pd.Timestamp)


class TestAmbiguity:
    def test_ambiguous_flagged_not_guessed(self, simple_cfg):
        df = pd.DataFrame({"d": ["03/04/2026"]})
        res = run(simple_cfg, df, [{"type": "date_normalize", "columns": ["d"]}])
        assert res.summary()["flags"] == 1
        assert str(res.dataframe["d"].iloc[0]) == "03/04/2026"  # untouched

    def test_dayfirst_resolves(self, simple_cfg):
        df = pd.DataFrame({"d": ["03/04/2026"]})
        res = run(
            simple_cfg,
            df,
            [{"type": "date_normalize", "columns": ["d"], "dayfirst": True}],
        )
        assert res.dataframe["d"].iloc[0] == "2026-04-03"

    def test_monthfirst_resolves(self, simple_cfg):
        df = pd.DataFrame({"d": ["03/04/2026"]})
        res = run(
            simple_cfg,
            df,
            [{"type": "date_normalize", "columns": ["d"], "dayfirst": False}],
        )
        assert res.dataframe["d"].iloc[0] == "2026-03-04"

    def test_unambiguous_still_resolved_without_dayfirst(self, simple_cfg):
        df = pd.DataFrame({"d": ["25/03/2026"]})  # 25 can only be a day
        res = run(simple_cfg, df, [{"type": "date_normalize", "columns": ["d"]}])
        assert res.dataframe["d"].iloc[0] == "2026-03-25"

    def test_two_digit_years(self, simple_cfg):
        df = pd.DataFrame({"d": ["25/03/26"]})
        res = run(simple_cfg, df, [{"type": "date_normalize", "columns": ["d"]}])
        assert res.dataframe["d"].iloc[0] == "2026-03-25"


class TestInvalidDates:
    def test_impossible_dates_flagged(self, simple_cfg):
        df = pd.DataFrame({"d": ["2026-02-30", "31/04/2026"]})
        res = run(simple_cfg, df, [{"type": "date_normalize", "columns": ["d"]}])
        assert res.summary()["flags"] == 2
        assert list(res.dataframe["d"]) == ["2026-02-30", "31/04/2026"]

    def test_garbage_flagged(self, simple_cfg):
        df = pd.DataFrame({"d": ["hello", "13/13/2026"]})
        res = run(simple_cfg, df, [{"type": "date_normalize", "columns": ["d"]}])
        assert res.summary()["flags"] == 2

    def test_on_error_set_null(self, simple_cfg):
        df = pd.DataFrame({"d": ["garbage", "2026-01-01"]})
        res = run(
            simple_cfg,
            df,
            [{"type": "date_normalize", "columns": ["d"], "on_error": "set_null"}],
        )
        assert pd.isna(res.dataframe["d"].iloc[0])
        assert res.dataframe["d"].iloc[1] == "2026-01-01"

    def test_on_error_remove_row(self, simple_cfg):
        df = pd.DataFrame({"id": [1, 2], "d": ["garbage", "2026-01-01"]})
        res = CleaningEngine(
            simple_cfg(
                [{"type": "date_normalize", "columns": ["d"], "on_error": "remove_row"}],
                audit={"key_columns": ["id"]},
            )
        ).apply(df)
        assert len(res.dataframe) == 1
        assert res.audit.removed_rows[0].key_values["id"] == "1"  # audit values are strings

    def test_missing_dates_stay_missing(self, simple_cfg):
        df = pd.DataFrame({"d": [None, "2026-01-01"]})
        res = run(simple_cfg, df, [{"type": "date_normalize", "columns": ["d"]}])
        assert pd.isna(res.dataframe["d"].iloc[0])
        assert res.summary()["flags"] == 0


class TestTimezone:
    def test_target_timezone(self, simple_cfg):
        df = pd.DataFrame({"d": ["2026-03-04T12:00:00Z"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "date_normalize",
                    "columns": ["d"],
                    "output_type": "date",
                    "target_tz": "Asia/Kolkata",
                }
            ],
        )
        assert res.dataframe["d"].iloc[0].isoformat() == "2026-03-04T17:30:00+05:30"

    def test_naive_localized_to_target_timezone(self, simple_cfg):
        df = pd.DataFrame({"d": ["2026-03-04"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "date_normalize",
                    "columns": ["d"],
                    "output_type": "date",
                    "target_tz": "Asia/Kolkata",
                }
            ],
        )
        # naive input is localized as wall time in the target zone
        assert res.dataframe["d"].iloc[0].isoformat() == "2026-03-04T00:00:00+05:30"

    def test_unknown_timezone_fails(self, simple_cfg):
        df = pd.DataFrame({"d": ["2026-03-04"]})
        res = run(
            simple_cfg,
            df,
            [
                {
                    "type": "date_normalize",
                    "columns": ["d"],
                    "target_tz": "Mars/Olympus",
                }
            ],
        )
        assert res.stopped_early and "timezone" in res.error


class TestIdempotence:
    def test_normalized_dates_unchanged_on_second_run(self, simple_cfg):
        df = pd.DataFrame({"d": ["25/03/2026", "March 4, 2026"]})
        rule = [{"type": "date_normalize", "columns": ["d"], "dayfirst": True}]
        once = run(simple_cfg, df, rule)
        twice = run(simple_cfg, once.dataframe, rule)
        assert once.dataframe.equals(twice.dataframe)
        assert twice.summary()["cells_changed"] == 0
