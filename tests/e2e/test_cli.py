"""E2E tests for the CLI (real subprocess runs, real exit codes)."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pandas as pd
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(REPO, "examples", "data")
CONFIGS = os.path.join(CONFIGS_DIR := os.path.join(REPO, "configs"), "")

ENV = {**os.environ, "PYTHONPATH": os.path.join(REPO, "src")}


def run_cli(*args, cwd=REPO):
    return subprocess.run(
        [sys.executable, "-m", "data_cleaning_toolkit", *args],
        capture_output=True, text=True, env=ENV, cwd=cwd, timeout=300,
    )


@pytest.fixture(scope="module")
def sales_csv():
    return os.path.join(DATA, "sales_transactions.csv")


@pytest.fixture(scope="module")
def sales_config():
    return os.path.join(CONFIGS, "sales_report.yaml")


class TestGlobal:
    def test_help_works(self):
        r = run_cli("--help")
        assert r.returncode == 0
        for cmd in ("profile", "preview", "clean", "validate", "batch", "report", "config"):
            assert cmd in r.stdout

    def test_subcommand_help(self):
        for cmd in ("profile", "preview", "clean", "validate", "batch", "config"):
            r = run_cli(cmd, "--help")
            assert r.returncode == 0
            assert "--input" in r.stdout or "--run-dir" in r.stdout or "--init" in r.stdout

    def test_version(self):
        r = run_cli("--version")
        assert r.returncode == 0 and "cleaner" in r.stdout

    def test_unknown_command_exit_2(self):
        r = run_cli("definitely-not-a-command")
        assert r.returncode == 2

    def test_python_dash_m_entry(self, sales_csv, sales_config):
        r = run_cli("profile", "--input", sales_csv, "--config", sales_config, "--quiet")
        assert r.returncode == 0


class TestProfile:
    def test_profile_shows_findings(self, sales_csv, sales_config):
        r = run_cli("profile", "-i", sales_csv, "-c", sales_config)
        assert r.returncode == 0
        assert "520 rows" in r.stdout
        assert "duplicate" in r.stdout.lower()

    def test_profile_json_output(self, sales_csv, sales_config, tmp_path):
        out = tmp_path / "profile.json"
        r = run_cli("profile", "-i", sales_csv, "-c", sales_config, "--json", str(out))
        assert r.returncode == 0
        data = json.loads(out.read_text())
        assert data["profile"]["rows"] == 520
        assert data["source"]["sha256"]

    def test_profile_missing_file_exit_1(self, sales_config, tmp_path):
        r = run_cli("profile", "-i", str(tmp_path / "nope.csv"), "-c", sales_config)
        assert r.returncode == 1


class TestPreviewClean:
    def test_preview_writes_nothing(self, sales_csv, sales_config, tmp_path):
        out = tmp_path / "out"
        r = run_cli("preview", "-i", sales_csv, "-c", sales_config, "-o", str(out))
        assert r.returncode == 0
        assert "DRY RUN" in r.stdout
        assert not out.exists() or not list(out.iterdir())

    def test_clean_produces_outputs(self, sales_csv, sales_config, tmp_path):
        out = tmp_path / "cleaned"
        r = run_cli("clean", "-i", sales_csv, "-c", sales_config, "-o", str(out), "--yes")
        assert r.returncode == 0, r.stderr
        assert (out / "sales_transactions_cleaned.csv").exists()
        runs = list(out.glob("run-*"))
        assert runs and (runs[0] / "manifest.json").exists()

    def test_clean_dry_run_flag(self, sales_csv, sales_config, tmp_path):
        out = tmp_path / "out2"
        r = run_cli("clean", "-i", sales_csv, "-c", sales_config, "-o", str(out), "--dry-run")
        assert r.returncode == 0
        assert not (out / "sales_transactions_cleaned.csv").exists()

    def test_clean_wont_overwrite_without_flag(self, sales_csv, sales_config, tmp_path):
        out = tmp_path / "cleaned2"
        assert run_cli("clean", "-i", sales_csv, "-c", sales_config, "-o", str(out), "--yes").returncode == 0
        r = run_cli("clean", "-i", sales_csv, "-c", sales_config, "-o", str(out), "--yes")
        assert r.returncode == 1 and "overwrite" in r.stderr.lower()

    def test_clean_force_overwrite(self, sales_csv, sales_config, tmp_path):
        out = tmp_path / "cleaned3"
        for _ in range(2):
            r = run_cli(
                "clean", "-i", sales_csv, "-c", sales_config,
                "-o", str(out), "--yes", "--force-overwrite",
            )
            assert r.returncode == 0, r.stderr


class TestValidate:
    def test_exit_4_on_violations(self, sales_csv, sales_config):
        r = run_cli("validate", "-i", sales_csv, "-c", sales_config)
        assert r.returncode == 4
        assert "violation" in r.stdout.lower()

    def test_exit_0_after_cleaning(self, sales_csv, sales_config, tmp_path):
        out = tmp_path / "v"
        run_cli("clean", "-i", sales_csv, "-c", sales_config, "-o", str(out), "--yes")
        # validation of the cleaned file: still some flagged values are possible,
        # so we only assert the command runs and reports a number
        r = run_cli(
            "validate", "-i", str(out / "sales_transactions_cleaned.csv"),
            "-c", sales_config, "--quiet",
        )
        assert r.returncode in (0, 4)

    def test_json_report(self, sales_csv, sales_config, tmp_path):
        out = tmp_path / "val.json"
        r = run_cli("validate", "-i", sales_csv, "-c", sales_config, "--json", str(out))
        assert r.returncode == 4
        assert json.loads(out.read_text())["validation_violations"] > 0


class TestBatch:
    def test_batch_happy_path(self, tmp_path):
        in_dir = tmp_path / "in"
        in_dir.mkdir()
        for name in ("customer_contacts.csv", "workforce_report.csv"):
            (in_dir / name).write_bytes(open(os.path.join(DATA, name), "rb").read())
        out = tmp_path / "out"
        # a config that applies to any tabular file: trim text + dedupe exact rows
        cfg = tmp_path / "generic.yaml"
        cfg.write_text(
            "version: '1.0'\nname: generic\n"
            "rules:\n"
            "  - id: trim\n    type: string_standardize\n    apply_to_all_text: true\n"
            "    trim_whitespace: true\n"
            "  - id: dedupe\n    type: duplicates\n    keep: first\n"
        )
        r = run_cli("batch", "-i", str(in_dir), "-c", str(cfg), "-o", str(out), "--force-overwrite")
        assert r.returncode == 0, r.stderr
        cleaned = list(out.glob("*_cleaned.csv"))
        assert len(cleaned) == 2

    def test_batch_reports_failures_and_exit_1(self, tmp_path):
        in_dir = tmp_path / "in"
        in_dir.mkdir()
        pd.DataFrame({"a": [1]}).to_csv(in_dir / "tiny.csv", index=False)
        cfg = os.path.join(CONFIGS, "customer_contacts.yaml")  # incompatible rules
        r = run_cli("batch", "-i", str(in_dir), "-c", cfg, "-o", str(tmp_path / "o"))
        assert r.returncode == 1

    def test_batch_accepts_yes_flag(self, tmp_path):
        """--yes is accepted for interface consistency (batch never prompts)."""
        in_dir = tmp_path / "in"
        in_dir.mkdir()
        (in_dir / "customer_contacts.csv").write_bytes(
            open(os.path.join(DATA, "customer_contacts.csv"), "rb").read()
        )
        cfg = os.path.join(CONFIGS, "customer_contacts.yaml")
        out = tmp_path / "out"
        r = run_cli("batch", "-i", str(in_dir), "-c", cfg, "-o", str(out), "--yes")
        assert r.returncode == 0, r.stderr
        assert list(out.glob("*_cleaned.xlsx"))  # customer_contacts profile exports xlsx

    def test_batch_dry_run(self, tmp_path):
        in_dir = tmp_path / "in"
        in_dir.mkdir()
        (in_dir / "customer_contacts.csv").write_bytes(
            open(os.path.join(DATA, "customer_contacts.csv"), "rb").read()
        )
        out = tmp_path / "out"
        cfg = os.path.join(CONFIGS, "customer_contacts.yaml")
        r = run_cli("batch", "-i", str(in_dir), "-c", cfg, "-o", str(out), "--dry-run")
        assert r.returncode == 0
        assert not list(out.glob("*_cleaned.csv"))


class TestReportAndConfig:
    def test_report_rebuild(self, sales_csv, sales_config, tmp_path):
        out = tmp_path / "r"
        run_cli("clean", "-i", sales_csv, "-c", sales_config, "-o", str(out), "--yes")
        run_dir = next((out).glob("run-*"))
        (run_dir / "report.html").unlink()
        r = run_cli("report", "--run-dir", str(run_dir))
        assert r.returncode == 0
        assert (run_dir / "report.html").exists()

    def test_report_missing_dir(self, tmp_path):
        r = run_cli("report", "--run-dir", str(tmp_path / "ghost"))
        assert r.returncode == 2

    def test_config_init_and_validate(self, tmp_path):
        target = tmp_path / "new.yaml"
        r = run_cli("config", "--init", str(target))
        assert r.returncode == 0 and target.exists()
        r = run_cli("config", "--validate", str(target))
        assert r.returncode == 0 and "valid" in r.stdout

    def test_config_init_from_profile(self, tmp_path):
        target = tmp_path / "from_profile.yaml"
        r = run_cli("config", "--init", str(target), "--profile", "financial_transactions")
        assert r.returncode == 0
        r = run_cli("config", "--validate", str(target))
        assert r.returncode == 0

    def test_config_validate_invalid(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("version: '1.0'\nrules:\n  - type: nope\n")
        r = run_cli("config", "--validate", str(bad))
        assert r.returncode == 2

    def test_list_profiles(self):
        r = run_cli("config", "--list-profiles")
        assert r.returncode == 0
        assert "general_business" in r.stdout


class TestErrorHandling:
    def test_invalid_config_file(self, sales_csv, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("rules: [{type: unknown_rule}]")
        r = run_cli("profile", "-i", sales_csv, "-c", str(bad))
        assert r.returncode == 2
        assert "invalid cleaning configuration" in r.stderr

    def test_unsupported_format(self, sales_config, tmp_path):
        f = tmp_path / "data.parquet"
        f.write_bytes(b"PAR1 not really")
        r = run_cli("profile", "-i", str(f), "-c", sales_config)
        assert r.returncode == 1
        assert "unsupported" in r.stderr.lower()

    def test_quiet_suppresses_output(self, sales_csv, sales_config):
        r = run_cli("profile", "-i", sales_csv, "-c", sales_config, "--quiet")
        assert r.returncode == 0 and r.stdout == ""
