"""Cleaning rule interface, outcome records and the rule registry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

import pandas as pd

from ..auditing.audit import AuditCollector
from ..core.errors import RuleError


@dataclass
class RuleOutcome:
    """What one rule did (or would do, in preview mode)."""

    rule_id: str
    rule_type: str
    status: str = "no_changes"  # applied | no_changes | flagged_only | error
    cells_changed: int = 0
    rows_removed: int = 0
    flags: int = 0
    rows_in: int = 0
    rows_out: int = 0
    details: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    examples: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_type": self.rule_type,
            "status": self.status,
            "cells_changed": self.cells_changed,
            "rows_removed": self.rows_removed,
            "flags": self.flags,
            "rows_in": self.rows_in,
            "rows_out": self.rows_out,
            "details": self.details,
            "warnings": self.warnings,
            "examples": self.examples,
            "error": self.error,
        }


class CleaningRule(ABC):
    """Base class for all cleaning rules.

    A rule *never* mutates the caller's dataframe: ``run`` receives a private
    copy. Every effect must be recorded through the audit collector, which is
    what makes preview and apply byte-for-byte consistent.
    """

    rule_type: ClassVar[str] = "base"
    description: ClassVar[str] = ""
    requires_full_dataset: ClassVar[bool] = False

    def __init__(self, cfg: Any, rule_id: str) -> None:
        self.cfg = cfg
        self.rule_id = rule_id
        self._warnings: list[str] = []

    # -- hooks -------------------------------------------------------------
    def run(self, df: pd.DataFrame, audit: AuditCollector) -> tuple[pd.DataFrame, RuleOutcome]:
        outcome = RuleOutcome(rule_id=self.rule_id, rule_type=self.rule_type)
        outcome.rows_in = len(df)
        self._warnings: list[str] = []
        c0, r0, f0 = audit.total_changes, len(audit.removed_rows), len(audit.flags)
        try:
            out_df = self.apply(df, audit)
        except RuleError:
            raise
        except Exception as exc:  # surface as a rule error, never crash the run
            raise RuleError(
                f"rule {self.rule_id!r} ({self.rule_type}) failed: {type(exc).__name__}: {exc}"
            ) from exc
        outcome.warnings = list(getattr(self, "_warnings", []))
        outcome.cells_changed = audit.total_changes - c0
        outcome.rows_removed = len(audit.removed_rows) - r0
        outcome.flags = len(audit.flags) - f0
        outcome.rows_out = len(out_df)
        if outcome.rows_removed or outcome.cells_changed:
            outcome.status = "applied"
        elif outcome.flags:
            outcome.status = "flagged_only"
        else:
            outcome.status = "no_changes"
        self._record_examples(outcome, audit)
        return out_df, outcome

    def _record_examples(self, outcome: RuleOutcome, audit: AuditCollector) -> None:
        """Attach representative before/after examples (for previews/reports)."""
        start = max(0, audit.total_changes - outcome.cells_changed)
        for rec in audit.changes[start : start + 8]:
            outcome.examples.append(
                {
                    "row": rec.row,
                    "column": rec.column,
                    "before": rec.original,
                    "after": rec.modified,
                    "reason": rec.reason,
                }
            )

    @abstractmethod
    def apply(self, df: pd.DataFrame, audit: AuditCollector) -> pd.DataFrame:
        """Execute the rule on ``df`` (a private copy) and record effects."""

    # -- shared helpers ----------------------------------------------------
    def _resolve_columns(self, df: pd.DataFrame, columns: list[str] | None) -> list[str]:
        if columns is None:
            return [str(c) for c in df.columns]
        missing = [c for c in columns if c not in df.columns]
        if missing:
            raise RuleError(
                f"rule {self.rule_id!r}: column(s) not found in dataset: {missing}. "
                f"Available columns: {[str(c) for c in df.columns]}"
            )
        return list(columns)

    def _warn(self, outcome_msgs: list[str], msg: str) -> None:
        if msg not in outcome_msgs:
            outcome_msgs.append(msg)


def iter_changes(
    df: pd.DataFrame,
    mask: pd.Series,
    column: str,
    new_values: pd.Series,
):
    """Yield (row_position, old, new) for changed cells, via fast numpy access."""
    import numpy as np

    pos = np.flatnonzero(mask.to_numpy())
    old = df[column].to_numpy(dtype=object)
    new = new_values.to_numpy(dtype=object)
    for p in pos:
        yield int(p), old[p], new[p]


_REGISTRY: dict[str, type[CleaningRule]] = {}


def register(cls: type[CleaningRule]) -> type[CleaningRule]:
    _REGISTRY[cls.rule_type] = cls
    return cls


def build_rules(config: Any) -> list[CleaningRule]:
    """Instantiate enabled rules from a validated config (fail-fast ids)."""
    counter = [0]
    rules: list[CleaningRule] = []
    seen: set[str] = set()
    for raw in config.rules:
        if not raw.enabled:
            continue
        counter[0] += 1
        rid = raw.resolve_id(f"{raw.type}-{counter[0]:02d}")
        if rid in seen:
            raise RuleError(f"duplicate rule id {rid!r}")
        seen.add(rid)
        cls = _REGISTRY.get(raw.type)
        if cls is None:
            raise RuleError(f"unknown rule type {raw.type!r}")
        rules.append(cls(raw, rid))
    return rules


def registry_types() -> list[str]:
    return sorted(_REGISTRY)
