"""File-level orchestration used by the CLI: load -> clean -> export -> audit."""

from __future__ import annotations

import os
from typing import Any

from ..auditing.run_io import save_run
from ..config.schema import CleaningConfig
from ..core.engine import CleaningEngine
from ..exporters.exporters import export_dataframe
from ..profiling.profiler import ProfileReport, profile_dataset
from ..readers.base import Dataset
from ..readers.excel_reader import load_any


def load_dataset(
    input_path: str,
    config: CleaningConfig,
    *,
    sheet: str | int | None = None,
) -> Dataset:
    """Load a file honoring the config's import options and limits."""
    options = config.import_options
    return load_any(input_path, sheet=sheet or None, options=options, limits=config.limits)


def profile_file(
    input_path: str,
    config: CleaningConfig,
    *,
    sheet: str | int | None = None,
) -> tuple[Dataset, ProfileReport]:
    ds = load_dataset(input_path, config, sheet=sheet)
    return ds, profile_dataset(ds.dataframe)


def process_file(
    input_path: str,
    config: CleaningConfig,
    output_dir: str,
    *,
    sheet: str | int | None = None,
    dry_run: bool = False,
    allow_overwrite: bool = False,
    runs_dir: str | None = None,
) -> dict[str, Any]:
    """Run the full pipeline for one file and return a summary dict.

    ``dry_run=True`` executes the engine in preview mode: source files are
    read but nothing is ever written, and the returned summary is identical
    in shape to an apply run (preview/apply consistency).
    """
    ds = load_dataset(input_path, config, sheet=sheet)
    profile = profile_dataset(ds.dataframe)
    engine = CleaningEngine(config, source_metadata=ds.metadata.to_dict())

    if dry_run:
        result = engine.preview(ds.dataframe)
        return {
            "ok": True,
            "dry_run": True,
            "input": input_path,
            "dataset": ds.name,
            "summary": result.summary(),
            "outcomes": [o.to_dict() for o in result.outcomes],
            "profile": profile.to_dict(),
        }

    result = engine.apply(ds.dataframe)
    if result.stopped_early:
        return {
            "ok": False,
            "input": input_path,
            "dataset": ds.name,
            "summary": result.summary(),
            "outcomes": [o.to_dict() for o in result.outcomes],
            "profile": profile.to_dict(),
            "error": result.error,
        }

    os.makedirs(output_dir, exist_ok=True)
    export = export_dataframe(
        result.dataframe,
        output_dir,
        ds.name,
        config,
        allow_overwrite=allow_overwrite,
    )
    run_dir = save_run(
        result,
        output_dir=runs_dir or output_dir,
        dataset_name=ds.name,
        exported_path=export.path if export else None,
        export_result=export,
        profile=profile,
    )
    return {
        "ok": True,
        "dry_run": False,
        "input": input_path,
        "dataset": ds.name,
        "run_dir": run_dir,
        "output": export.path if export else None,
        "export": export.__dict__ if export else None,
        "summary": result.summary(),
        "outcomes": [o.to_dict() for o in result.outcomes],
        "profile": profile.to_dict(),
    }


def validation_report(
    input_path: str,
    config: CleaningConfig,
    *,
    sheet: str | int | None = None,
) -> dict[str, Any]:
    """Profile + preview a file and summarize validation findings.

    This never writes anything: it answers "what problems would my rules
    find if I cleaned this file?"
    """
    ds, profile = profile_file(input_path, config, sheet=sheet)
    engine = CleaningEngine(config, source_metadata=ds.metadata.to_dict())
    result = engine.preview(ds.dataframe)
    violation_count = sum(o.flags for o in result.outcomes)
    return {
        "ok": not result.stopped_early,
        "input": input_path,
        "dataset": ds.name,
        "profile": profile.to_dict(),
        "summary": result.summary(),
        "validation_violations": violation_count,
        "outcomes": [o.to_dict() for o in result.outcomes],
        "error": result.error,
    }
