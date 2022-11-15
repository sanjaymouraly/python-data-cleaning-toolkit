"""Excel (.xlsx) reader using openpyxl, with formula-safety and sheet handling.

Formulas are read as their *cached* values (what a spreadsheet application
last calculated). If a workbook was written by another program and never
recalculated, cached values may be missing (None) - this is surfaced as a
workbook warning rather than silently producing empty data.
"""

from __future__ import annotations

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
from .csv_reader import read_csv


def list_sheets(path: str) -> list[str]:
    """Return sheet names of a workbook without loading cell data."""
    check_extension(path)
    try:
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=False)
        names = list(wb.sheetnames)
        wb.close()
        return names
    except Exception as exc:
        if "password" in str(exc).lower() or "encrypt" in str(exc).lower():
            raise DataImportError(
                "workbook is encrypted/password-protected; not supported"
            ) from exc
        raise DataImportError(f"cannot open workbook: {exc}") from exc


def _scan_formulas(path: str, sheet: str, sample_rows: int = 500) -> int:
    """Count formula-looking cells in a sample (to warn about cached values)."""
    try:
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=False)
        ws = wb[sheet]
        count = 0
        for _i, row in enumerate(ws.iter_rows(max_row=sample_rows)):
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    count += 1
                    if count >= 1:
                        break
            if count:
                break
        wb.close()
        return count
    except Exception:  # pragma: no cover - defensive
        return 0


def read_excel(
    path: str,
    sheet: str | int | None = None,
    options: ImportOptionsConfig | None = None,
    limits: Any = None,
) -> Dataset:
    """Read one worksheet of an ``.xlsx`` workbook into a :class:`Dataset`."""
    options = options or ImportOptionsConfig()
    ext = check_extension(path)
    if ext != ".xlsx":
        raise DataImportError(f"{os.path.basename(path)!r} is not an .xlsx workbook")
    if not os.path.exists(path):
        raise DataImportError(f"file not found: {path}")
    if limits is not None:
        enforce_file_limit(path, limits.max_file_mb)

    try:
        names = list_sheets(path)
    except DataImportError:
        raise
    if not names:
        raise DataImportError("workbook contains no worksheets")

    if sheet is None:
        chosen = names[0]
        if len(names) > 1:
            sheet_note = (
                f"workbook has {len(names)} sheets; using first sheet {chosen!r} "
                "(pass --sheet or select in the dashboard to choose another)"
            )
        else:
            sheet_note = ""
    elif isinstance(sheet, int):
        if not (-len(names) <= sheet < len(names)):
            raise DataImportError(
                f"sheet index {sheet} out of range; workbook has sheets {names}"
            )
        chosen = names[sheet]
        sheet_note = ""
    else:
        if sheet not in names:
            raise DataImportError(
                f"sheet {sheet!r} not found; available sheets: {names}"
            )
        chosen = sheet
        sheet_note = ""

    formula_cells = _scan_formulas(path, chosen)
    workbook_warnings: list[str] = []
    if formula_cells:
        workbook_warnings.append(
            "worksheet contains formula cells; their last *cached* values are "
            "imported (formulas themselves are never re-evaluated or exported). "
            "If this file was generated programmatically, cached values may be "
            "missing and cells will import as empty."
        )

    try:
        df = pd.read_excel(
            path,
            sheet_name=chosen,
            engine="openpyxl",
            header=int(options.header_row),
            dtype=object,
        )
    except Exception as exc:
        raise DataImportError(f"failed to read worksheet {chosen!r}: {exc}") from exc

    if df.empty and len(df.columns) == 0:
        raise DataImportError(
            f"worksheet {chosen!r} is empty (no rows and no columns)"
        )
    df.columns = [str(c) if not isinstance(c, str) else c for c in df.columns]
    df = df.dropna(axis=1, how="all")
    if df.empty:
        raise DataImportError(
            f"worksheet {chosen!r} has no data rows (header row "
            f"{options.header_row} exists but nothing below it)"
        )
    df.columns = [str(c) for c in df.columns]

    df = _apply_column_options(df, options)
    if limits is not None:
        enforce_shape_limit(df, limits)

    warnings: list[str] = []
    if sheet_note:
        warnings.append(sheet_note)

    meta = SourceMetadata(
        path=os.path.abspath(path),
        filename=os.path.basename(path),
        fmt="xlsx",
        size_bytes=os.path.getsize(path),
        sha256=hash_source(path),
        encoding="utf-8",
        delimiter=None,
        sheet=chosen,
        workbook_warnings=workbook_warnings,
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


def load_any(
    path: str,
    sheet: str | int | None = None,
    options: ImportOptionsConfig | None = None,
    limits: Any = None,
) -> Dataset:
    """Dispatch to the right reader based on the file extension."""
    ext = check_extension(path)
    if ext == ".csv":
        return read_csv(path, options=options, limits=limits)
    return read_excel(path, sheet=sheet, options=options, limits=limits)
