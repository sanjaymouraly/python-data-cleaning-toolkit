"""Engine-level tests: safety guarantees, preview/apply consistency, audit."""

from __future__ import annotations

import pandas as pd

from data_cleaning_toolkit import CleaningEngine
from data_cleaning_toolkit.auditing.audit import AuditCollector


class TestSafetyGuarantees:
    def test_input_dataframe_never_mutated(self, simple_cfg, dirty_df):
        cfg = simple_cfg(
            [
                {"type": "string_standardize", "columns": ["name"], "trim_whitespace": True},
                {"type": "duplicates"},
                {"type": "missing_values", "columns": ["qty"], "strategy": "remove_rows"},
            ]
        )
        original = dirty_df.copy(deep=True)
        CleaningEngine(cfg).apply(dirty_df)
        pd.testing.assert_frame_equal(dirty_df, original)

    def test_source_file_never_modified_by_apply(self, simple_cfg, tmp_csv, dirty_df):
        path = tmp_csv(dirty_df)
        before = open(path, "rb").read()
        from data_cleaning_toolkit import clean_file

        clean_file(path, simple_cfg([{"type": "duplicates"}]), str(tmp := __import__("pathlib").Path(path).parent))
        assert open(path, "rb").read() == before

    def test_preview_equals_apply_dataframe(self, simple_cfg, dirty_df):
        cfg = simple_cfg(
            [
                {"type": "missing_values", "strategy": "retain"},
                {"type": "string_standardize", "columns": ["name"], "trim_whitespace": True},
                {"type": "type_conversion", "column": "qty", "target": "integer"},
                {"type": "duplicates"},
            ]
        )
        engine = CleaningEngine(cfg)
        prev = engine.preview(dirty_df)
        appl = engine.apply(dirty_df)
        pd.testing.assert_frame_equal(prev.dataframe, appl.dataframe)
        assert prev.summary()["cells_changed"] == appl.summary()["cells_changed"]

    def test_fail_fast_stops_remaining_rules(self, simple_cfg):
        df = pd.DataFrame({"a": ["x"], "b": ["y"]})
        cfg = simple_cfg(
            [
                {"type": "type_conversion", "column": "a", "target": "integer", "on_error": "fail"},
                {"type": "duplicates"},
            ]
        )
        res = CleaningEngine(cfg).apply(df)
        assert res.stopped_early
        assert [o.rule_type for o in res.outcomes] == ["type_conversion"]

    def test_rule_error_recorded_with_rule_id(self, simple_cfg):
        df = pd.DataFrame({"a": [1]})
        cfg = simple_cfg([{"type": "numeric_validate", "columns": ["missing_col"]}])
        res = CleaningEngine(cfg).apply(df)
        assert res.stopped_early
        assert res.outcomes[0].error and "missing_col" in res.outcomes[0].error


class TestAuditCollector:
    def test_redaction(self):
        audit = AuditCollector(redact_columns=["email"])
        audit.add_change(
            rule_id="r", rule_type="t", row=0, column="email",
            original="secret@x.io", modified="SECRETX@x.io", reason="test",
        )
        assert audit.changes[0].original == "[REDACTED]"
        assert audit.to_dict()["changes"][0]["original"] == "[REDACTED]"

    def test_change_cap_keeps_exact_totals(self):
        audit = AuditCollector(max_change_records=5)
        for i in range(20):
            audit.add_change(
                rule_id="r", rule_type="t", row=i, column="c",
                original=i, modified=i + 1, reason="test",
            )
        d = audit.to_dict()
        assert d["totals"]["cells_changed"] == 20
        assert len(d["changes"]) == 5
        assert d["totals"]["change_records_dropped"] == 15

    def test_removed_row_provenance_only_key_columns(self):
        audit = AuditCollector(key_columns=["id"])
        df = pd.DataFrame({"id": ["k1"], "secret": ["s"], "v": [1]})
        audit.add_removed_row(
            rule_id="r", rule_type="t", row=0, reason="test",
            row_series=dict(zip(df.columns, df.iloc[0], strict=True)),
        )
        rec = audit.removed_rows[0]
        assert rec.key_values == {"id": "k1"}

    def test_values_none_rendered_as_na(self):
        audit = AuditCollector()
        audit.add_change(
            rule_id="r", rule_type="t", row=0, column="c",
            original=None, modified=5, reason="test",
        )
        assert audit.changes[0].original == "<NA>"


class TestCleanResult:
    def test_summary_shape(self, simple_cfg, dirty_df):
        res = CleaningEngine(simple_cfg([{"type": "duplicates"}])).apply(dirty_df)
        s = res.summary()
        for key in ("rows_in", "rows_out", "rows_removed", "cells_changed", "flags"):
            assert key in s

    def test_config_snapshot_embedded(self, simple_cfg):
        res = CleaningEngine(simple_cfg([{"type": "duplicates"}])).apply(
            pd.DataFrame({"a": [1, 1]})
        )
        snap = res.config_snapshot
        assert snap["snapshot_version"] == "1.0"
        assert snap["config"]["rules"][0]["type"] == "duplicates"

    def test_outcomes_frame(self, simple_cfg, dirty_df):
        res = CleaningEngine(simple_cfg([{"type": "duplicates"}])).apply(dirty_df)
        assert not res.outcomes_frame().empty
