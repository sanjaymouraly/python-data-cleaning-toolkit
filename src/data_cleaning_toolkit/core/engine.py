"""The cleaning engine: runs rules in order, preview and apply share one path.

Preview is *literally* the same execution as apply - it just runs on a
discarded copy and reports what happened. This makes preview/apply
consistency structural rather than aspirational.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..auditing.audit import AuditCollector, utc_now_iso
from ..cleaners.base import CleaningRule, RuleOutcome, build_rules
from ..config.schema import CleaningConfig
from ..core.errors import RuleError


@dataclass
class CleanResult:
    dataframe: pd.DataFrame
    outcomes: list[RuleOutcome]
    audit: AuditCollector
    is_preview: bool
    rows_in: int
    rows_out: int
    columns_in: int
    columns_out: int
    stopped_early: bool = False
    error: str | None = None
    engine_version: str = "1.0.0"
    finished_at: str = ""
    config_snapshot: dict[str, Any] = field(default_factory=dict)
    source_metadata: dict[str, Any] | None = None

    @property
    def cells_changed(self) -> int:
        return self.audit.total_changes

    @property
    def rows_removed(self) -> int:
        return len(self.audit.removed_rows)

    @property
    def flags(self) -> int:
        return len(self.audit.flags)

    def summary(self) -> dict[str, Any]:
        return {
            "is_preview": self.is_preview,
            "rows_in": self.rows_in,
            "rows_out": self.rows_out,
            "rows_removed": self.rows_removed,
            "columns_in": self.columns_in,
            "columns_out": self.columns_out,
            "cells_changed": self.cells_changed,
            "flags": self.flags,
            "rules_executed": len(self.outcomes),
            "rules_failed": sum(1 for o in self.outcomes if o.status == "error"),
            "stopped_early": self.stopped_early,
            "error": self.error,
        }

    def outcomes_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "rule": o.rule_id,
                    "type": o.rule_type,
                    "status": o.status,
                    "cells changed": o.cells_changed,
                    "rows removed": o.rows_removed,
                    "flags": o.flags,
                    "warnings": "; ".join(o.warnings) or "",
                }
                for o in self.outcomes
            ]
        )

    def to_dict(self, *, include_audit_records: bool = True) -> dict[str, Any]:
        data = {
            "summary": self.summary(),
            "engine_version": self.engine_version,
            "finished_at": self.finished_at,
            "outcomes": [o.to_dict() for o in self.outcomes],
            "source": self.source_metadata,
            "config_snapshot": self.config_snapshot,
        }
        if include_audit_records:
            data["audit"] = self.audit.to_dict(include_records=True)
        else:
            data["audit_totals"] = self.audit.to_dict(include_records=False)
        return data


class CleaningEngine:
    """Execute a validated :class:`CleaningConfig` against a dataframe."""

    def __init__(self, config: CleaningConfig, *, source_metadata: dict[str, Any] | None = None) -> None:
        self.config = config
        self.source_metadata = source_metadata
        self.rules: list[CleaningRule] = build_rules(config)

    @property
    def requires_full_dataset(self) -> bool:
        return any(r.requires_full_dataset for r in self.rules)

    def preview(self, df: pd.DataFrame) -> CleanResult:
        """Analyze without touching the caller's data; identical code path to apply."""
        return self._run(df, is_preview=True)

    def apply(self, df: pd.DataFrame) -> CleanResult:
        """Execute the plan; the input dataframe is never mutated."""
        return self._run(df, is_preview=False)

    # ------------------------------------------------------------------
    def _run(self, df: pd.DataFrame, *, is_preview: bool) -> CleanResult:
        audit = AuditCollector(
            max_change_records=self.config.audit.max_change_records,
            key_columns=self.config.audit.key_columns,
            redact_columns=self.config.audit.redact_columns,
        )
        work = df.copy().reset_index(drop=True)
        rows_in, cols_in = work.shape
        outcomes: list[RuleOutcome] = []
        stopped_early = False
        error: str | None = None

        for rule in self.rules:
            try:
                work, outcome = rule.run(work, audit)
                outcomes.append(outcome)
            except RuleError as exc:
                outcomes.append(
                    RuleOutcome(
                        rule_id=rule.rule_id,
                        rule_type=rule.rule_type,
                        status="error",
                        rows_in=len(work),
                        rows_out=len(work),
                        error=str(exc),
                    )
                )
                stopped_early = True
                error = str(exc)
                break  # fail-safe: never continue with half-applied semantics

        return CleanResult(
            dataframe=work,
            outcomes=outcomes,
            audit=audit,
            is_preview=is_preview,
            rows_in=rows_in,
            rows_out=len(work),
            columns_in=cols_in,
            columns_out=work.shape[1],
            stopped_early=stopped_early,
            error=error,
            finished_at=utc_now_iso(),
            config_snapshot=self.config.to_snapshot(),
            source_metadata=self.source_metadata,
        )
