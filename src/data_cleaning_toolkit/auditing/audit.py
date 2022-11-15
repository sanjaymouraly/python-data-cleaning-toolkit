"""Audit trail: structured records of every modification the engine makes.

Three record kinds exist:

* :class:`ChangeRecord` - one cell that was modified (value before/after).
* :class:`RemovedRowRecord` - one row that was deleted, with provenance.
* :class:`FlagRecord` - a suspicious value that was flagged for review,
  never silently modified.

A single :class:`AuditCollector` accumulates records while rules execute.
Change records are capped (``max_change_records``) to bound memory on huge
datasets; totals are always exact, only per-row detail is capped.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def sha256_file(path: str, chunk_size: int = 1 << 20) -> str:
    """SHA-256 hex digest of a file, streamed in chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def _format_value(value: Any, redact: bool) -> str:
    if value is None:
        return "<NA>"
    try:
        if isinstance(value, float) and math.isnan(value):
            return "<NA>"
    except TypeError:  # pragma: no cover - defensive
        pass
    if isinstance(value, datetime):
        return value.isoformat()
    text = str(value)
    return "[REDACTED]" if redact and text != "" else text


@dataclass
class ChangeRecord:
    rule_id: str
    rule_type: str
    row: int | None  # 0-based dataframe index
    column: str | None
    original: str
    modified: str
    reason: str
    kind: str = "cell"  # cell | normalize_marker | unit | removed | flag

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_type": self.rule_type,
            "row": self.row,
            "column": self.column,
            "original": self.original,
            "modified": self.modified,
            "reason": self.reason,
            "kind": self.kind,
        }


@dataclass
class RemovedRowRecord:
    rule_id: str
    rule_type: str
    row: int  # 0-based dataframe index of the row at removal time
    reason: str
    key_values: dict[str, str]  # provenance: identifier column values of the row

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_type": self.rule_type,
            "row": self.row,
            "reason": self.reason,
            "key_values": self.key_values,
        }


@dataclass
class FlagRecord:
    rule_id: str
    rule_type: str
    row: int | None
    column: str | None
    value: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_type": self.rule_type,
            "row": self.row,
            "column": self.column,
            "value": self.value,
            "message": self.message,
        }


@dataclass
class RuleRunStats:
    rule_id: str
    rule_type: str
    cells_changed: int = 0
    rows_removed: int = 0
    flags: int = 0
    warnings: list[str] = field(default_factory=list)


class AuditCollector:
    """Accumulates audit records while rules run.

    Parameters
    ----------
    max_change_records:
        Maximum number of *individual* change records retained. Extra changes
        are still counted exactly; only their per-row detail is dropped.
    key_columns:
        Columns whose values are captured as provenance for removed rows.
    redact_columns:
        Column names whose values must never appear in audit records.
    """

    def __init__(
        self,
        *,
        max_change_records: int = 50_000,
        key_columns: Iterable[str] = (),
        redact_columns: Iterable[str] = (),
    ) -> None:
        self.max_change_records = max(0, int(max_change_records))
        self.key_columns = list(key_columns)
        self.redact_columns = set(redact_columns)
        self.changes: list[ChangeRecord] = []
        self.removed_rows: list[RemovedRowRecord] = []
        self.flags: list[FlagRecord] = []
        self.total_changes = 0
        self.dropped_change_records = 0

    # -- redaction ---------------------------------------------------------
    def _value(self, column: str | None, value: Any) -> str:
        redact = column is not None and column in self.redact_columns
        return _format_value(value, redact)

    # -- record APIs -------------------------------------------------------
    def add_change(
        self,
        *,
        rule_id: str,
        rule_type: str,
        row: int | None,
        column: str | None,
        original: Any,
        modified: Any,
        reason: str,
        kind: str = "cell",
    ) -> None:
        self.total_changes += 1
        if len(self.changes) >= self.max_change_records:
            self.dropped_change_records += 1
            return
        self.changes.append(
            ChangeRecord(
                rule_id=rule_id,
                rule_type=rule_type,
                row=row,
                column=column,
                original=self._value(column, original),
                modified=self._value(column, modified),
                reason=reason,
                kind=kind,
            )
        )

    def add_removed_row(
        self, *, rule_id: str, rule_type: str, row: int, reason: str, row_series: Any
    ) -> None:
        keys: dict[str, str] = {}
        if isinstance(row_series, dict):
            available = row_series.keys()
        else:
            available = getattr(row_series, "index", ())
        for col in self.key_columns:
            if col in available:
                keys[col] = self._value(col, row_series[col])
        self.removed_rows.append(
            RemovedRowRecord(
                rule_id=rule_id,
                rule_type=rule_type,
                row=row,
                reason=reason,
                key_values=keys,
            )
        )

    def add_flag(
        self,
        *,
        rule_id: str,
        rule_type: str,
        row: int | None,
        column: str | None,
        value: Any,
        message: str,
    ) -> None:
        self.flags.append(
            FlagRecord(
                rule_id=rule_id,
                rule_type=rule_type,
                row=row,
                column=column,
                value=self._value(column, value),
                message=message,
            )
        )

    # -- serialization -----------------------------------------------------
    def to_dict(self, *, include_records: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "totals": {
                "cells_changed": self.total_changes,
                "rows_removed": len(self.removed_rows),
                "flags": len(self.flags),
                "change_records_retained": len(self.changes),
                "change_records_dropped": self.dropped_change_records,
            }
        }
        if include_records:
            data["changes"] = [c.to_dict() for c in self.changes]
            data["removed_rows"] = [r.to_dict() for r in self.removed_rows]
            data["flags"] = [f.to_dict() for f in self.flags]
        return data


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
