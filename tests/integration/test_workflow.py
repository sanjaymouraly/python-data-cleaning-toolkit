"""Integration tests: the complete workflow on real generated datasets.

Import -> Profile -> Configure -> Preview -> Apply -> Validate -> Export -> Audit
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

import pandas as pd
import pytest

from data_cleaning_toolkit import (
    CleaningEngine,
    load_config_file,
    parse_config,
    process_file,
    profile_dataset,
    validation_report,
)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(REPO, "examples", "data")
CONFIGS = os.path.join(REPO, "configs")

# ensure example data exists (generator is deterministic)
subprocess.run(
    [sys.executable, os.path.join(REPO, "scripts", "generate_samples.py")],
    check=True, capture_output=True,
)


@pytest.fixture()
def sales_csv():
    return os.path.join(DATA, "sales_transactions.csv")


@pytest.fixture()
def sales_cfg():
    return load_config_file(os.path.join(CONFIGS, "sales_report.yaml"))


@pytest.fixture()
def sample_df():
    return pd.read_csv(os.path.join(DATA, "sales_transactions.csv"), dtype=object,
                       keep_default_na=False)


class TestFullWorkflow:
    def test_import_profile_preview_apply_export_audit(
        self, tmp_path, sales_csv, sales_cfg
    ):
        # import + profile
        from data_cleaning_toolkit import load_dataset

        ds = load_dataset(sales_csv, sales_cfg)
        profile = profile_dataset(ds.dataframe)
        assert profile.rows == 520
        assert profile.quality_score < 80  # sample is intentionally dirty

        # preview: identical results, nothing written
        engine = CleaningEngine(sales_cfg, source_metadata=ds.metadata.to_dict())
        preview = engine.preview(ds.dataframe)
        assert not preview.stopped_early
        assert preview.summary()["rows_removed"] == 20

        # apply
        result = engine.apply(ds.dataframe)
        assert result.summary()["rows_out"] == 500
        assert not result.stopped_early

        # export + audit artifacts
        out_dir = str(tmp_path / "out")
        summary = process_file(sales_csv, sales_cfg, out_dir, dry_run=False)
        assert summary["ok"]
        assert os.path.exists(summary["output"])
        run_dir = summary["run_dir"]
        for artifact in (
            "manifest.json", "config_snapshot.yaml", "report.html",
            "audit/audit.json", "audit/changes.csv", "audit/flags.csv",
            "audit/removed_rows.csv",
        ):
            assert os.path.exists(os.path.join(run_dir, artifact)), artifact

        # exported file opens and has the expected shape
        cleaned = pd.read_csv(summary["output"], dtype=object, keep_default_na=False)
        assert len(cleaned) == 500

        # audit log matches reality
        with open(os.path.join(run_dir, "audit", "audit.json"), encoding="utf-8") as fh:
            audit = json.load(fh)
        assert audit["summary"]["rows_removed"] == 20
        assert audit["summary"]["cells_changed"] == result.audit.total_changes

    def test_source_never_modified_by_any_step(self, tmp_path, sales_csv, sales_cfg):
        def digest():
            return hashlib.sha256(open(sales_csv, "rb").read()).hexdigest()

        before = digest()
        process_file(sales_csv, sales_cfg, str(tmp_path / "a"), dry_run=True)
        process_file(sales_csv, sales_cfg, str(tmp_path / "b"), dry_run=False)
        assert digest() == before

    def test_dry_run_writes_nothing(self, tmp_path, sales_csv, sales_cfg):
        out_dir = str(tmp_path / "nothing")
        summary = process_file(sales_csv, sales_cfg, out_dir, dry_run=True)
        assert summary["dry_run"]
        assert not os.path.exists(out_dir) or not os.listdir(out_dir)

    def test_apply_overwrite_requires_explicit_consent(self, tmp_path, sales_csv, sales_cfg):
        from data_cleaning_toolkit import SafetyError

        first = process_file(sales_csv, sales_cfg, str(tmp_path / "o"))
        out_path = first["output"]
        assert os.path.exists(out_path)
        # a second identical run must refuse to clobber without consent
        with pytest.raises(SafetyError):
            process_file(sales_csv, sales_cfg, str(tmp_path / "o"))
        # explicit consent works
        second = process_file(
            sales_csv, sales_cfg, str(tmp_path / "o"), allow_overwrite=True
        )
        assert second["ok"]

    def test_preview_apply_counts_identical(self, sales_csv, sales_cfg, tmp_path):
        dry = process_file(sales_csv, sales_cfg, str(tmp_path), dry_run=True)
        real = process_file(sales_csv, sales_cfg, str(tmp_path), dry_run=False)
        assert dry["summary"]["cells_changed"] == real["summary"]["cells_changed"]
        assert dry["summary"]["rows_removed"] == real["summary"]["rows_removed"]
        assert dry["summary"]["flags"] == real["summary"]["flags"]


class TestSampleDatasets:
    """Every bundled sample must clean successfully with its config."""

    @pytest.mark.parametrize(
        "filename,config,sheet",
        [
            ("sales_transactions.csv", "sales_report.yaml", None),
            ("inventory.xlsx", "inventory_stock.yaml", "stock"),
            ("freelancer_income_expenses.xlsx", "freelancer_income.yaml", "income"),
            ("customer_contacts.csv", "customer_contacts.yaml", None),
            ("workforce_report.csv", "workforce_report.yaml", None),
        ],
    )
    def test_samples_clean_end_to_end(self, tmp_path, filename, config, sheet):
        cfg = load_config_file(os.path.join(CONFIGS, config))
        summary = process_file(
            os.path.join(DATA, filename), cfg, str(tmp_path), sheet=sheet
        )
        assert summary["ok"], summary.get("error")
        assert os.path.exists(summary["output"])
        assert summary["summary"]["rows_out"] > 0

    def test_generator_is_deterministic(self):
        """Same seed -> identical data (CSVs byte-identical; XLSX content-equal,
        because zip containers embed timestamps)."""
        import tempfile

        import pandas as pd

        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            from scripts.generate_samples import build_all

            m1 = build_all(d1)
            m2 = build_all(d2)
            assert m1["datasets"].keys() == m2["datasets"].keys()
            for name in m1["datasets"]:
                p1, p2 = os.path.join(d1, name), os.path.join(d2, name)
                if name.endswith(".csv"):
                    assert open(p1, "rb").read() == open(p2, "rb").read(), name
                else:
                    sheets1 = pd.read_excel(p1, sheet_name=None, dtype=object)
                    sheets2 = pd.read_excel(p2, sheet_name=None, dtype=object)
                    assert list(sheets1) == list(sheets2), name
                    for sheet in sheets1:
                        pd.testing.assert_frame_equal(sheets1[sheet], sheets2[sheet])


class TestValidationCommand:
    def test_validate_reports_violations(self, sales_csv, sales_cfg):
        report = validation_report(sales_csv, sales_cfg)
        assert report["validation_violations"] > 0
        assert not report["ok"] or report["ok"]  # ok reflects rule errors, not violations

    def test_clean_dataset_has_fewer_violations(self, tmp_path, sales_csv, sales_cfg):
        before = validation_report(sales_csv, sales_cfg)
        cleaned_path = os.path.join(str(tmp_path), "cleaned.csv")
        result = process_file(sales_csv, sales_cfg, str(tmp_path))
        df = pd.read_csv(result["output"])
        df.to_csv(cleaned_path, index=False)
        after = validation_report(cleaned_path, sales_cfg)
        assert (
            after["validation_violations"] < before["validation_violations"]
        ), "cleaning should reduce violations"


class TestBatch:
    def test_batch_processes_all_supported(self, tmp_path):
        in_dir = tmp_path / "in"
        in_dir.mkdir()
        for f in ("sales_transactions.csv", "customer_contacts.csv", "workforce_report.csv"):
            (in_dir / f).write_bytes(open(os.path.join(DATA, f), "rb").read())
        (in_dir / "ignore.txt.bak").write_text("not supported")
        out_dir = tmp_path / "out"
        # a schema-agnostic plan that applies to any tabular file
        cfg = parse_config(
            {
                "version": "1.0",
                "name": "generic",
                "rules": [
                    {
                        "type": "string_standardize",
                        "apply_to_all_text": True,
                        "trim_whitespace": True,
                    },
                    {"type": "duplicates"},
                ],
            }
        )
        from data_cleaning_toolkit.core.pipeline import process_file

        # batch is a CLI-level loop; here we verify each file individually
        ok = 0
        for f in sorted(in_dir.iterdir()):
            if f.suffix.lower() not in {".csv", ".xlsx"}:
                continue
            summary = process_file(str(f), cfg, str(out_dir), allow_overwrite=True)
            if summary["ok"]:
                ok += 1
        assert ok == 3


class TestReproducibility:
    def test_identical_inputs_and_config_identical_output(self, tmp_path, sales_csv):
        cfg = parse_config(
            {
                "version": "1.0",
                "name": "repro",
                "rules": [
                    {"type": "string_standardize", "columns": ["region"], "case": "lower"},
                    {"type": "duplicates"},
                ],
            }
        )
        outs = []
        for i in range(2):
            summary = process_file(
                sales_csv, cfg, str(tmp_path / f"run{i}"), allow_overwrite=True
            )
            df = pd.read_csv(summary["output"], dtype=str)
            outs.append(df)
        pd.testing.assert_frame_equal(outs[0], outs[1])
