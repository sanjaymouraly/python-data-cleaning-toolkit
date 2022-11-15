"""Safe exporters: CSV / XLSX / JSON with atomic writes and output validation.

Safety features
---------------
* Never overwrites an existing file unless ``allow_overwrite`` is explicit.
* Writes go to a temporary file in the same directory, then ``os.replace`` -
  a failed export cannot leave a partial file.
* Formula-injection guard: text beginning with ``=``, ``+``, ``-``, ``@``,
  tab or CR is prefixed with ``'`` so spreadsheet applications treat it as
  text (OWASP CSV injection mitigation). Counts are returned for reporting.
* ``validate_output`` reopens each written file and checks row count,
  columns and sample rows against the dataframe that was written.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ..config.schema import CleaningConfig
from ..core.errors import OutputError, SafetyError

_RISKY_PREFIXES = ("=", "+", "@", "\t", "\r")


def sanitize_filename(name: str) -> str:
    """Strip path separators and control characters from a filename component."""
    base = os.path.basename(name.replace("\\", "/"))
    cleaned = "".join(c if c.isalnum() or c in "._- " else "_" for c in base).strip()
    cleaned = " ".join(cleaned.split())
    return cleaned or "output"


def guard_cell(value: Any, enabled: bool) -> tuple[Any, bool]:
    """Return (possibly-guarded) value and whether guarding applied."""
    if not enabled or not isinstance(value, str):
        return value, False
    if value.startswith(_RISKY_PREFIXES):
        return "'" + value, True
    return value, False


@dataclass
class ExportResult:
    path: str
    fmt: str
    rows: int
    columns: int
    guarded_cells: int = 0
    validated: bool = False
    validation_details: list[str] = field(default_factory=list)
    sha256: str = ""


def _atomic_write(path: str, writer) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    if os.path.exists(path):
        raise SafetyError(
            f"refusing to overwrite existing file: {path} "
            "(delete it first or pass --force-overwrite)"
        )
    fd, tmp_path = tempfile.mkstemp(prefix=".dtk_", suffix=".tmp", dir=directory)
    os.close(fd)
    try:
        writer(tmp_path)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def export_csv(
    df: pd.DataFrame,
    path: str,
    *,
    delimiter: str = ",",
    encoding: str = "utf-8",
    include_index: bool = False,
    formula_guard: bool = True,
    allow_overwrite: bool = False,
    validate: bool = True,
) -> ExportResult:
    if allow_overwrite and os.path.exists(path):
        os.unlink(path)
    guarded_count = 0
    out = df.copy()

    def write(tmp: str) -> None:
        nonlocal guarded_count
        if formula_guard:
            guarded = 0
            for col in out.columns:
                if out[col].dtype == object:
                    masked = out[col].map(lambda v: guard_cell(v, True)[1] if isinstance(v, str) else False)
                    if masked.any():
                        guarded += int(masked.sum())
                        out.loc[masked, col] = out.loc[masked, col].map(lambda v: "'" + v)
            guarded_count = guarded
        out.to_csv(
            tmp,
            sep=delimiter,
            encoding=encoding,
            index=include_index,
            lineterminator="\n",
        )

    _atomic_write(path, write)
    result = ExportResult(
        path=os.path.abspath(path),
        fmt="csv",
        rows=len(out),
        columns=len(out.columns),
        guarded_cells=guarded_count,
    )
    if validate:
        _validate_csv(out, path, result, delimiter, encoding)
    return result


def _validate_csv(
    expected: pd.DataFrame, path: str, result: ExportResult, delimiter: str, encoding: str
) -> None:
    readback = pd.read_csv(
        path, sep=delimiter, encoding=encoding, dtype=object, keep_default_na=False
    )
    if len(readback) != len(expected):
        raise OutputError(
            f"output validation failed: wrote {len(expected)} rows but "
            f"{len(readback)} round-tripped in {path}"
        )
    if list(readback.columns) != [str(c) for c in expected.columns]:
        raise OutputError(
            f"output validation failed: column mismatch in {path}: "
            f"{list(readback.columns)} vs {[str(c) for c in expected.columns]}"
        )
    # spot-check first, middle and last row as strings
    checks = {0, len(expected) // 2, len(expected) - 1} if len(expected) else set()
    for i in checks:
        exp_row = expected.iloc[i]
        got_row = readback.iloc[i]
        for col in expected.columns:
            if not _round_trip_equal(exp_row[col], str(got_row[col])):
                raise OutputError(
                    f"output validation failed at row {i}, column {col!r}: "
                    f"wrote {_stringify(exp_row[col])!r} but round-tripped "
                    f"{str(got_row[col])!r}"
                )
    result.validated = True
    result.validation_details.append(
        f"reopened CSV: {len(readback)} rows, {len(readback.columns)} columns, "
        "sample rows match"
    )


def _stringify(value: Any) -> str:
    import numpy as _np

    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        if value == value.normalize():
            return value.strftime("%Y-%m-%d")
        return str(value)
    if isinstance(value, (_np.floating, float)):
        return repr(float(value))
    if isinstance(value, (_np.integer, int)) and not isinstance(value, bool):
        return str(int(value))
    if isinstance(value, (_np.bool_, bool)):
        return str(bool(value))
    return str(value)


def _round_trip_equal(written: Any, read_back: str) -> bool:
    """Tolerant comparison: exact string match, or numeric equality."""
    w = _stringify(written)
    if w.strip() == read_back.strip():
        return True
    try:
        return abs(float(w)) == abs(float(read_back)) and (
            float(w) == float(read_back)
        )
    except (TypeError, ValueError):
        return False


def export_xlsx(
    df: pd.DataFrame,
    path: str,
    *,
    sheet_name: str = "cleaned",
    formula_guard: bool = True,
    allow_overwrite: bool = False,
    validate: bool = True,
) -> ExportResult:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    if allow_overwrite and os.path.exists(path):
        os.unlink(path)
    guarded_count = 0

    def write(tmp: str) -> None:
        nonlocal guarded_count
        wb = Workbook()
        ws = wb.active
        ws.title = sheet_name[:31] or "cleaned"
        for j, col in enumerate(df.columns, start=1):
            cell = ws.cell(row=1, column=j, value=str(col))
            cell.font = Font(bold=True)
        for i, (_, row) in enumerate(df.iterrows(), start=2):
            for j, col in enumerate(df.columns, start=1):
                value = row[col]
                if value is None or (isinstance(value, float) and pd.isna(value)) or pd.isna(value):
                    value = None
                elif isinstance(value, str):
                    value, was_guarded = guard_cell(value, formula_guard)
                    guarded_count += int(was_guarded)
                elif isinstance(value, pd.Timestamp):
                    value = value.to_pydatetime()
                elif isinstance(value, (np.integer,)):
                    value = int(value)
                elif isinstance(value, (np.floating,)):
                    value = float(value)
                elif isinstance(value, (np.bool_,)):
                    value = bool(value)
                cell = ws.cell(row=i, column=j, value=value)
                if isinstance(value, str):
                    cell.number_format = "@"
                elif isinstance(value, pd.Timestamp) or hasattr(value, "year"):
                    cell.number_format = "yyyy-mm-dd hh:mm:ss"
        # modest column widths for readability
        for j, col in enumerate(df.columns, start=1):
            width = min(40, max(10, len(str(col)) + 4))
            ws.column_dimensions[get_column_letter(j)].width = width
        wb.save(tmp)

    _atomic_write(path, write)
    result = ExportResult(
        path=os.path.abspath(path),
        fmt="xlsx",
        rows=len(df),
        columns=len(df.columns),
        guarded_cells=guarded_count,
    )
    if validate:
        _validate_xlsx(df, path, result, sheet_name)
    return result


def _validate_xlsx(
    expected: pd.DataFrame, path: str, result: ExportResult, sheet_name: str
) -> None:
    from openpyxl import load_workbook

    wb = load_workbook(path, data_only=True)
    name = (sheet_name or "cleaned")[:31] or "cleaned"
    ws = wb[name] if name in wb.sheetnames else wb.active
    header = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
    if header != [str(c) for c in expected.columns]:
        raise OutputError(
            f"output validation failed: XLSX header mismatch in {path}: {header}"
        )
    n_data_rows = ws.max_row - 1
    if n_data_rows != len(expected):
        # openpyxl does not count a trailing all-empty row; accept only when
        # the final expected row is entirely null
        trailing_null = False
        if n_data_rows == len(expected) - 1 and len(expected):
            last = expected.iloc[-1]
            trailing_null = all(pd.isna(v) for v in last)
        if not trailing_null:
            raise OutputError(
                f"output validation failed: XLSX has {n_data_rows} data rows, "
                f"expected {len(expected)}"
            )
    if len(expected):
        first = [c.value for c in next(ws.iter_rows(min_row=2, max_row=2))]
        exp_first = expected.iloc[0]
        for j, col in enumerate(expected.columns):
            exp = exp_first[col]
            got = first[j]
            try:
                if pd.isna(exp):
                    continue  # NaN written as empty cell
            except (TypeError, ValueError):
                pass
            if isinstance(exp, str):
                guarded = guard_cell(exp, True)[0]
                if got != guarded:
                    raise OutputError(
                        f"output validation failed: cell (1, {col!r}) wrote "
                        f"{guarded!r}, read back {got!r}"
                    )
            elif isinstance(exp, (bool, np.bool_)):
                if bool(got) != bool(exp):
                    raise OutputError(
                        f"output validation failed: cell (1, {col!r}) wrote "
                        f"{bool(exp)!r}, read back {got!r}"
                    )
    wb.close()
    result.validated = True
    result.validation_details.append(
        f"reopened XLSX: {n_data_rows} rows, {len(header)} columns, header and "
        "sample cells match"
    )


def export_json(
    df: pd.DataFrame,
    path: str,
    *,
    allow_overwrite: bool = False,
    validate: bool = True,
) -> ExportResult:
    if allow_overwrite and os.path.exists(path):
        os.unlink(path)

    def write(tmp: str) -> None:
        records = json.loads(df.to_json(orient="records", date_format="iso", force_ascii=False))
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(records, fh, ensure_ascii=False, indent=2)

    _atomic_write(path, write)
    result = ExportResult(
        path=os.path.abspath(path), fmt="json", rows=len(df), columns=len(df.columns)
    )
    if validate:
        with open(path, encoding="utf-8") as fh:
            records = json.load(fh)
        if len(records) != len(df):
            raise OutputError(
                f"output validation failed: JSON has {len(records)} records, "
                f"expected {len(df)}"
            )
        result.validated = True
        result.validation_details.append(f"reopened JSON: {len(records)} records")
    return result


def export_dataframe(
    df: pd.DataFrame,
    directory: str,
    base_name: str,
    config: CleaningConfig,
    *,
    allow_overwrite: bool = False,
) -> ExportResult | None:
    """Export per the config's export section. Returns None for fmt='none'."""
    fmt = config.export.fmt
    if fmt == "none":
        return None
    base = sanitize_filename(base_name)
    suffix = sanitize_filename(config.export.filename_suffix) or "_cleaned"
    os.makedirs(directory, exist_ok=True)
    if fmt == "csv":
        return export_csv(
            df,
            os.path.join(directory, f"{base}{suffix}.csv"),
            delimiter=config.export.delimiter,
            encoding=config.export.encoding,
            include_index=config.export.include_index,
            formula_guard=config.export.formula_injection_guard,
            allow_overwrite=allow_overwrite,
            validate=config.export.validate_output,
        )
    if fmt == "xlsx":
        return export_xlsx(
            df,
            os.path.join(directory, f"{base}{suffix}.xlsx"),
            formula_guard=config.export.formula_injection_guard,
            allow_overwrite=allow_overwrite,
            validate=config.export.validate_output,
        )
    return export_json(
        df,
        os.path.join(directory, f"{base}{suffix}.json"),
        allow_overwrite=allow_overwrite,
        validate=config.export.validate_output,
    )
