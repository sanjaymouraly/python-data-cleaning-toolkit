"""Profiler tests: counts, markers, mixed types, quality score."""

from __future__ import annotations

import pandas as pd

from data_cleaning_toolkit import profile_dataset


class TestCounts:
    def test_missing_and_markers(self):
        df = pd.DataFrame(
            {"a": ["1", "N/A", "3"], "b": ["x", None, "unknown"], "c": [0, 1, 2]}
        )
        p = profile_dataset(df).to_dict()
        by_name = {c["name"]: c for c in p["columns"]}
        assert by_name["a"]["missing"] == 1  # 'N/A' counts as missing
        assert by_name["b"]["missing"] == 2  # None + 'unknown'
        assert by_name["c"]["missing"] == 0  # zero is NOT missing

    def test_duplicates_counted(self):
        df = pd.DataFrame({"a": [1, 1, 2], "b": ["x", "x", "y"]})
        p = profile_dataset(df)
        assert p.duplicate_rows == 2

    def test_mixed_types_detected(self):
        df = pd.DataFrame({"a": ["1", "2", "three"]})
        col = profile_dataset(df).column("a")
        assert set(col.mixed_types) == {"integer", "text"}

    def test_case_variants(self):
        df = pd.DataFrame({"cat": ["north", "NORTH", "North", "south"]})
        col = profile_dataset(df).column("cat")
        assert col.case_variants >= 1

    def test_whitespace_padded(self):
        df = pd.DataFrame({"n": [" a ", "b", " c"]})
        col = profile_dataset(df).column("n")
        assert col.whitespace_padded == 2

    def test_mixed_units_detected(self):
        df = pd.DataFrame({"w": ["2 kg", "300 g", "1 kg"]})
        col = profile_dataset(df).column("w")
        assert set(col.distinct_units) == {"kg", "g"}

    def test_numeric_stats_and_outliers(self):
        df = pd.DataFrame({"v": [10, 11, 12, 13, 12, 11, 500]})
        prof = profile_dataset(df)
        col = prof.column("v")
        assert col.numeric_stats["max"] == 500
        assert col.outlier_candidates >= 1

    def test_date_like_text(self):
        df = pd.DataFrame({"d": ["2026-01-01", "03/04/2026", "hello"]})
        col = profile_dataset(df).column("d")
        assert col.parseable_dates == 2


class TestQualityScore:
    def test_score_components_bounded(self, dirty_df):
        p = profile_dataset(dirty_df)
        for v in p.score_components.values():
            assert 0 <= v <= 100
        assert 0 <= p.quality_score <= 100

    def test_clean_data_scores_high(self):
        df = pd.DataFrame(
            {"a": range(100), "b": [f"item{i}" for i in range(100)]}
        )
        assert profile_dataset(df).quality_score > 85

    def test_findings_reported(self):
        df = pd.DataFrame({"a": [1, 1, 2], "b": [4, 4, 5]})
        p = profile_dataset(df).to_dict()
        areas = {f["area"] for f in p["findings"]}
        assert "duplicates" in areas

    def test_empty_dataframe_does_not_crash(self):
        p = profile_dataset(pd.DataFrame())
        assert p.rows == 0 and p.columns == 0

    def test_profile_frame_is_dataframe(self, dirty_df):
        assert isinstance(profile_dataset(dirty_df).profile_frame(), pd.DataFrame)

    def test_deterministic(self, dirty_df):
        a = profile_dataset(dirty_df).to_dict()
        b = profile_dataset(dirty_df).to_dict()
        assert a == b
