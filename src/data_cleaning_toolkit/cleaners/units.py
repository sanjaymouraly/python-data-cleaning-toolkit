"""Unit normalization for explicitly configured measurement columns.

Only documented conversion tables are supported (mass, length, temperature).
Rows whose source unit is unknown, missing or non-numeric are flagged and
left untouched - a conversion is never guessed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..auditing.audit import AuditCollector
from ..config.schema import UNIT_CATEGORIES, UnitNormalizeRuleConfig
from .base import CleaningRule, register


def _to_celsius(value: float, unit: str) -> float:
    if unit == "c":
        return value
    if unit == "f":
        return (value - 32.0) * 5.0 / 9.0
    return value - 273.15  # k


def _from_celsius(value: float, unit: str) -> float:
    if unit == "c":
        return value
    if unit == "f":
        return value * 9.0 / 5.0 + 32.0
    return value + 273.15  # k


@register
class UnitNormalizeRule(CleaningRule):
    rule_type = "unit_normalize"
    description = (
        "Convert a value column between explicitly configured units (mass, "
        "length, temperature). Unknown/missing source units are flagged and "
        "never converted."
    )

    def apply(self, df: pd.DataFrame, audit: AuditCollector) -> pd.DataFrame:
        cfg: UnitNormalizeRuleConfig = self.cfg
        for col in (cfg.value_column, cfg.unit_column):
            if col and col not in df.columns:
                from ..core.errors import RuleError

                raise RuleError(
                    f"rule {self.rule_id!r}: column {col!r} not found "
                    f"(available: {[str(c) for c in df.columns]})"
                )

        table = UNIT_CATEGORIES[cfg.category]
        target = cfg.target_unit.lower()
        source_series = (
            df[cfg.unit_column].astype(str).str.strip().str.lower()
            if cfg.unit_column
            else pd.Series([cfg.source_unit.lower()] * len(df), index=df.index)
        )
        values = pd.to_numeric(df[cfg.value_column], errors="coerce").astype(float)
        non_numeric = df[cfg.value_column].notna() & values.isna()

        converted = pd.Series(False, index=df.index)
        new_values = values.copy()

        for pos in df.index:
            unit = source_series.loc[pos]
            if df[cfg.value_column].isna().loc[pos]:
                continue  # nothing to convert; missing-data rules own this case
            if non_numeric.loc[pos]:
                audit.add_flag(
                    rule_id=self.rule_id,
                    rule_type=self.rule_type,
                    row=int(pos),
                    column=cfg.value_column,
                    value=str(df[cfg.value_column].loc[pos]),
                    message="non-numeric value; unit conversion skipped",
                )
                continue
            if cfg.category == "temperature":
                if unit not in ("c", "f", "k"):
                    self._flag_unknown(audit, df, pos, unit)
                    continue
                new = _from_celsius(_to_celsius(float(values.loc[pos]), unit), target)
            else:
                if unit not in table:
                    self._flag_unknown(audit, df, pos, unit)
                    continue
                new = float(values.loc[pos]) * table[unit] / table[target]
            if cfg.rounding_digits is not None:
                new = round(new, int(cfg.rounding_digits))
            if not np.isclose(new, float(values.loc[pos]), rtol=1e-12, atol=0):
                audit.add_change(
                    rule_id=self.rule_id,
                    rule_type=self.rule_type,
                    row=int(pos),
                    column=cfg.value_column,
                    original=df[cfg.value_column].loc[pos],
                    modified=new,
                    reason=f"unit conversion {unit or '<missing>'} -> {target}",
                )
            if cfg.unit_column and str(df[cfg.unit_column].loc[pos]).strip().lower() != target:
                audit.add_change(
                    rule_id=self.rule_id,
                    rule_type=self.rule_type,
                    row=int(pos),
                    column=cfg.unit_column,
                    original=df[cfg.unit_column].loc[pos],
                    modified=target,
                    reason=f"unit label updated to {target!r} after conversion",
                )
            new_values.loc[pos] = new
            converted.loc[pos] = True

        df[cfg.value_column] = new_values.where(converted, df[cfg.value_column])
        if cfg.unit_column:
            label_changed = converted & source_series.ne(target)
            df.loc[label_changed, cfg.unit_column] = target
        return df

    def _flag_unknown(self, audit: AuditCollector, df: pd.DataFrame, pos, unit: str) -> None:
        audit.add_flag(
            rule_id=self.rule_id,
            rule_type=self.rule_type,
            row=int(pos),
            column=self.cfg.unit_column or self.cfg.value_column,
            value=unit,
            message=(
                f"unknown or missing source unit {unit!r}; value left unchanged "
                "(conversion prevented)"
            ),
        )
