"""Dataset container and source metadata shared by all readers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..auditing.audit import sha256_file as _sha256_file
from ..core.errors import LimitExceededError, UnsupportedFormatError

SUPPORTED_EXTENSIONS = {".csv", ".txt", ".tsv", ".xlsx"}
UNSUPPORTED_FORMAT_HINTS = {
    ".xls": "legacy .xls is not supported; re-save the file as .xlsx",
    ".xlsm": "macro-enabled workbooks are not supported; re-save as .xlsx "
    "(macros are never preserved)",
    ".parquet": "parquet is not supported; convert to CSV or XLSX",
    ".zip": "archives are not processed for safety reasons",
    ".gz": "compressed files are not processed; decompress first",
    ".ods": "OpenDocument spreadsheets are not supported; save as .xlsx",
}


@dataclass
class SourceMetadata:
    path: str
    filename: str
    fmt: str  # "csv" | "xlsx"
    size_bytes: int
    sha256: str
    encoding: str | None = None
    delimiter: str | None = None
    sheet: str | None = None
    workbook_warnings: list[str] = field(default_factory=list)
    import_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "filename": self.filename,
            "format": self.fmt,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "encoding": self.encoding,
            "delimiter": self.delimiter,
            "sheet": self.sheet,
            "workbook_warnings": list(self.workbook_warnings),
            "import_warnings": list(self.import_warnings),
        }


@dataclass
class Dataset:
    """A loaded tabular dataset plus everything needed to audit it."""

    dataframe: pd.DataFrame
    metadata: SourceMetadata

    @property
    def name(self) -> str:
        base = self.metadata.filename.rsplit(".", 1)[0]
        if self.metadata.sheet:
            return f"{base}[{self.metadata.sheet}]"
        return base

    @property
    def shape(self) -> tuple[int, int]:
        return self.dataframe.shape

    def head(self, n: int = 5) -> pd.DataFrame:
        return self.dataframe.head(n)


def check_extension(path: str) -> str:
    """Return the normalized extension or raise UnsupportedFormatError."""
    import os

    ext = os.path.splitext(path)[1].lower()
    if ext in SUPPORTED_EXTENSIONS:
        return ".xlsx" if ext == ".xlsx" else ".csv"
    hint = UNSUPPORTED_FORMAT_HINTS.get(ext)
    msg = f"unsupported file format {ext!r} for {os.path.basename(path)!r}"
    if hint:
        msg += f": {hint}"
    raise UnsupportedFormatError(msg)


def enforce_file_limit(path: str, max_file_mb: float) -> None:
    import os

    size = os.path.getsize(path)
    limit = max_file_mb * 1024 * 1024
    if size > limit:
        raise LimitExceededError(
            f"file {os.path.basename(path)!r} is {size / 1048576:.1f} MB which "
            f"exceeds the configured limit of {max_file_mb:g} MB "
            "(limits.max_file_mb). Increase the limit explicitly if this file "
            "is expected to be this large."
        )


def enforce_shape_limit(df: pd.DataFrame, limits: Any) -> None:
    rows, cols = df.shape
    if rows > limits.max_rows:
        raise LimitExceededError(
            f"dataset has {rows:,} rows which exceeds limits.max_rows "
            f"({limits.max_rows:,}). Refusing to process partially."
        )
    if cols > limits.max_columns:
        raise LimitExceededError(
            f"dataset has {cols:,} columns which exceeds limits.max_columns "
            f"({limits.max_columns:,})."
        )


def hash_source(path: str) -> str:
    return _sha256_file(path)
