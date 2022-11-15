"""Advanced CSV & Excel Data Cleaning Toolkit.

A safety-first data cleaning engine with three interfaces:

* Python library (this package) - see :func:`clean_file`, :class:`CleaningEngine`
* CLI - ``cleaner --help``
* Streamlit dashboard - ``streamlit run app/app.py``
"""

from __future__ import annotations

__version__ = "1.0.0"

from .config.schema import CleaningConfig, config_yaml, load_config_file, parse_config
from .core.engine import CleaningEngine, CleanResult
from .core.errors import (
    ConfigError,
    DataImportError,
    LimitExceededError,
    OutputError,
    RuleError,
    SafetyError,
    ToolkitError,
    UnsupportedFormatError,
)
from .core.pipeline import load_dataset, process_file, profile_file, validation_report
from .exporters.exporters import export_csv, export_json, export_xlsx
from .profiling.profiler import ProfileReport, profile_dataset
from .readers.base import SUPPORTED_EXTENSIONS, Dataset
from .readers.csv_reader import read_csv
from .readers.excel_reader import list_sheets, read_excel

__all__ = [
    "__version__",
    "CleaningConfig",
    "parse_config",
    "load_config_file",
    "config_yaml",
    "CleaningEngine",
    "CleanResult",
    "clean_file",
    "process_file",
    "profile_file",
    "profile_dataset",
    "ProfileReport",
    "load_dataset",
    "validation_report",
    "read_csv",
    "read_excel",
    "list_sheets",
    "Dataset",
    "SUPPORTED_EXTENSIONS",
    "export_csv",
    "export_xlsx",
    "export_json",
    "ToolkitError",
    "ConfigError",
    "DataImportError",
    "UnsupportedFormatError",
    "LimitExceededError",
    "RuleError",
    "OutputError",
    "SafetyError",
]


def clean_file(
    input_path: str,
    config: CleaningConfig | str | dict,
    output_dir: str = "cleaned",
    *,
    sheet: str | int | None = None,
    dry_run: bool = False,
    allow_overwrite: bool = False,
    runs_dir: str | None = None,
) -> dict:
    """One-call convenience: clean a CSV/XLSX file with a config.

    Parameters
    ----------
    input_path:
        Path to a ``.csv``/``.tsv``/``.txt`` or ``.xlsx`` file.
    config:
        A :class:`CleaningConfig`, or YAML/JSON text, or a mapping.
    output_dir:
        Directory that receives the cleaned file and audit artifacts.
    sheet:
        Worksheet name or index for Excel workbooks.
    dry_run:
        When True, analyze/preview only - nothing is written.

    Returns
    -------
    dict
        Run summary including ``summary``, ``outcomes`` and artifact paths.
    """
    if not isinstance(config, CleaningConfig):
        config = parse_config(config)
    return process_file(
        input_path,
        config,
        output_dir,
        sheet=sheet,
        dry_run=dry_run,
        allow_overwrite=allow_overwrite,
        runs_dir=runs_dir,
    )
