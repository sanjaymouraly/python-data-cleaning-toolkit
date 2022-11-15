"""CSV reader with encoding cascade, delimiter sniffing and bad-row accounting."""

from __future__ import annotations

import csv
import os
from typing import Any

import pandas as pd

from ..config.schema import ImportOptionsConfig
from ..core.errors import DataImportError
from .base import (
    Dataset,
    SourceMetadata,
    check_extension,
    enforce_file_limit,
    enforce_shape_limit,
    hash_source,
)

# Encoding cascade: BOM-aware utf-8 first, then common single-byte encodings.
ENCODING_CASCADE = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
_CANDIDATE_DELIMITERS = [",", ";", "\t", "|"]


def _detect_encoding(path: str, override: str | None) -> tuple[str, list[str]]:
    warnings: list[str] = []
    if override:
        try:
            "probe".encode(override)
        except LookupError as exc:
            raise DataImportError(f"unknown encoding {override!r}") from exc
        return override, warnings
    with open(path, "rb") as _fh:
        raw = _fh.read(65536)
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig", warnings
    for enc in ENCODING_CASCADE:
        try:
            raw.decode(enc)
            if enc != "utf-8-sig" and enc != "utf-8":
                warnings.append(
                    f"file decoded with fallback encoding {enc!r}; verify text fields"
                )
            return enc, warnings
        except UnicodeDecodeError:
            continue
    raise DataImportError(
        "could not decode file with any common encoding "
        f"({', '.join(ENCODING_CASCADE)})"
    )


def _sniff_delimiter(path: str, encoding: str, override: str | None) -> tuple[str, list[str]]:
    warnings: list[str] = []
    if override:
        if len(override) != 1:
            raise DataImportError("delimiter must be a single character")
        return override, warnings
    try:
        with open(path, encoding=encoding, newline="") as fh:
            sample = fh.read(65536)
    except OSError as exc:
        raise DataImportError(f"cannot read file: {exc}") from exc
    if not sample.strip():
        raise DataImportError("file is empty (no header row found)")
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="".join(_CANDIDATE_DELIMITERS))
        delim = dialect.delimiter
        if delim != ",":
            warnings.append(f"auto-detected delimiter {delim!r}")
        return delim, warnings
    except csv.Error:
        # Fall back to the delimiter producing the most consistent column count.
        best, best_score = ",", -1.0
        for cand in _CANDIDATE_DELIMITERS:
            counts = [line.count(cand) for line in sample.splitlines()[:20] if line.strip()]
            if not counts:
                continue
            mean = sum(counts) / len(counts)
            var = sum((c - mean) ** 2 for c in counts) / len(counts)
            if mean > 0 and (best_score < 0 or var < best_score):
                best, best_score = cand, var
        if best_score < 0:
            # no candidate delimiter anywhere -> treat as a single-column file
            warnings.append(
                "no delimiter detected; reading as a single-column file"
            )
            return ",", warnings
        warnings.append(f"delimiter auto-detected as {best!r} (sniffer fallback)")
        return best, warnings


def _count_bad_lines(path: str, encoding: str, sep: str, header: int) -> tuple[int, list[str]]:
    """Count rows whose field count differs from the header's."""
    warnings: list[str] = []
    try:
        with open(path, encoding=encoding, newline="") as fh:
            reader = csv.reader(fh, delimiter=sep)
            rows = list(reader)
    except (OSError, UnicodeDecodeError) as exc:
        raise DataImportError(f"cannot re-scan file for malformed rows: {exc}") from exc
    if not rows:
        raise DataImportError("file is empty")
    if header >= len(rows):
        raise DataImportError(
            f"header_row={header} is beyond the end of the file ({len(rows)} rows)"
        )
    expected = max(len(r) for r in rows[header:])
    bad = sum(1 for r in rows[header:] if len(r) != expected)
    if bad:
        warnings.append(
            f"{bad} malformed row(s) had {expected} expected fields; "
            "ragged rows are padded/skipped by the parser"
        )
    return bad, warnings


def read_csv(
    path: str,
    options: ImportOptionsConfig | None = None,
    limits: Any = None,
) -> Dataset:
    """Read a CSV file into a :class:`Dataset`.

    Malformed rows are skipped and counted (never silently accepted as data).
    """
    options = options or ImportOptionsConfig()
    ext = check_extension(path)
    if ext != ".csv":
        raise DataImportError(f"{os.path.basename(path)!r} is not a CSV file")
    if limits is not None:
        enforce_file_limit(path, limits.max_file_mb)
    if not os.path.exists(path):
        raise DataImportError(f"file not found: {path}")

    encoding, warn_enc = _detect_encoding(path, options.encoding)
    delimiter, warn_delim = _sniff_delimiter(path, encoding, options.delimiter)
    header = int(options.header_row)
    bad_count, warn_bad = _count_bad_lines(path, encoding, delimiter, header)

    try:
        df = pd.read_csv(
            path,
            sep=delimiter,
            encoding=encoding,
            header=header,
            dtype=object,  # preserve original text; typing is decided by rules
            keep_default_na=False,
            na_values=[],
            on_bad_lines="warn",
            engine="python" if bad_count else "c",
        )
    except pd.errors.EmptyDataError as exc:
        raise DataImportError("file contains no data rows") from exc
    except UnicodeDecodeError as exc:
        raise DataImportError(
            f"decoding failed with {encoding!r}: {exc}. "
            "Set import_options.encoding explicitly."
        ) from exc
    except Exception as exc:  # pragma: no cover - pandas parser variants
        raise DataImportError(f"failed to parse CSV: {exc}") from exc

    warnings = [*warn_enc, *warn_delim, *warn_bad]
    if df.empty and len(df.columns) == 0:
        raise DataImportError("file contains no parseable columns")
    if df.empty:
        raise DataImportError(
            f"file contains a header row but no data rows "
            f"(columns: {list(df.columns)})"
        )

    df = _apply_column_options(df, options)
    if limits is not None:
        enforce_shape_limit(df, limits)

    meta = SourceMetadata(
        path=os.path.abspath(path),
        filename=os.path.basename(path),
        fmt="csv",
        size_bytes=os.path.getsize(path),
        sha256=hash_source(path),
        encoding=encoding,
        delimiter=delimiter,
        import_warnings=warnings,
    )
    return Dataset(dataframe=df, metadata=meta)


def _apply_column_options(df: pd.DataFrame, options: ImportOptionsConfig) -> pd.DataFrame:
    # selection uses ORIGINAL column names; rename is applied afterwards
    if options.columns:
        missing = [c for c in options.columns if c not in df.columns]
        if missing:
            raise DataImportError(
                f"import_options.columns references unknown columns: {missing}"
            )
        df = df[options.columns]
    if options.rename:
        missing = [c for c in options.rename if c not in df.columns]
        if missing:
            raise DataImportError(
                f"import_options.rename references unknown columns: {missing}"
            )
        df = df.rename(columns=dict(options.rename))
    return df
