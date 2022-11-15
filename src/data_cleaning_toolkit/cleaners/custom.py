"""Configuration-driven custom validation rules.

All rules share the same violation actions: ``flag`` (default),
``remove_rows``, or ``set_null``. Nothing is deleted without an explicit
configuration choice, and every violation is reported.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from ..auditing.audit import AuditCollector
from ..config.schema import (
    AllowedValuesRuleConfig,
    ConditionalRequiredRuleConfig,
    CrossColumnRuleConfig,
    RegexMatchRuleConfig,
    RequiredColumnRuleConfig,
    UniqueKeyRuleConfig,
)
from ..core.errors import RuleError
from .base import CleaningRule, register


class _CustomRuleMixin:
    def _column(self, df: pd.DataFrame, name: str) -> pd.Series:
        if name not in df.columns:
            raise RuleError(
                f"rule {self.rule_id!r}: column {name!r} not found "
                f"(available: {[str(c) for c in df.columns]})"
            )
        return df[name]

    def _finalize(
        self,
        df: pd.DataFrame,
        audit: AuditCollector,
        violations: pd.Series,
        column: str | None,
        message_for: object,
    ) -> pd.DataFrame:
        if violations.empty or not violations.any():
            return df
        action = self.cfg.on_violation
        for pos in df.index[violations.to_numpy()]:
            message = message_for(pos) if callable(message_for) else message_for
            if action == "flag":
                audit.add_flag(
                    rule_id=self.rule_id,
                    rule_type=self.rule_type,
                    row=int(pos),
                    column=column,
                    value=str(df[column].loc[pos]) if column else "",
                    message=message,
                )
            elif action == "set_null" and column:
                audit.add_change(
                    rule_id=self.rule_id,
                    rule_type=self.rule_type,
                    row=int(pos),
                    column=column,
                    original=df[column].loc[pos],
                    modified="<NA>",
                    reason=message,
                )
                df.loc[pos, column] = np.nan
            elif action == "set_null":
                raise RuleError(
                    f"rule {self.rule_id!r}: on_violation=set_null requires a target column"
                )
        if action == "remove_rows":
            rows = df.index[violations.to_numpy()]
            for pos, row in zip(rows, df.loc[rows].itertuples(index=False, name=None), strict=True):
                audit.add_removed_row(
                    rule_id=self.rule_id,
                    rule_type=self.rule_type,
                    row=int(pos),
                    reason=str(message_for(rows[0]) if callable(message_for) else message_for),
                    row_series=dict(zip(df.columns, row, strict=True)),
                )
            df = df.loc[~violations.to_numpy()].reset_index(drop=True)
        return df


@register
class RequiredColumnRule(CleaningRule, _CustomRuleMixin):
    rule_type = "required_column"
    description = "Flag or remove rows where a required field is empty."

    def apply(self, df: pd.DataFrame, audit: AuditCollector) -> pd.DataFrame:
        cfg: RequiredColumnRuleConfig = self.cfg
        s = self._column(df, cfg.column)
        empty = s.isna() | (s.astype(str).str.strip() == "")
        return self._finalize(
            df, audit, empty, cfg.column,
            lambda p: f"required field {cfg.column!r} is empty",
        )


@register
class AllowedValuesRule(CleaningRule, _CustomRuleMixin):
    rule_type = "allowed_values"
    description = "Validate that a column only contains allowed category values."

    def apply(self, df: pd.DataFrame, audit: AuditCollector) -> pd.DataFrame:
        cfg: AllowedValuesRuleConfig = self.cfg
        s = self._column(df, cfg.column)
        notna = s.notna() & s.astype(str).str.strip().ne("")
        if cfg.ignore_case:
            allowed = {str(v).strip().lower() for v in cfg.values}
            ok = s.astype(str).str.strip().str.lower().isin(allowed)
        else:
            allowed = {str(v) for v in cfg.values}
            ok = s.astype(str).str.strip().isin(allowed)
        violations = notna & ~ok
        return self._finalize(
            df, audit, violations, cfg.column,
            lambda p: f"value {s.loc[p]!r} not in allowed values {sorted(allowed)}",
        )


@register
class RegexMatchRule(CleaningRule, _CustomRuleMixin):
    rule_type = "regex_match"
    description = "Validate text against a regular expression pattern."

    def apply(self, df: pd.DataFrame, audit: AuditCollector) -> pd.DataFrame:
        cfg: RegexMatchRuleConfig = self.cfg
        s = self._column(df, cfg.column)
        notna = s.notna() & s.astype(str).str.strip().ne("")
        try:
            matched = s.astype(str).str.match(cfg.pattern)
        except re.error as exc:
            raise RuleError(f"rule {self.rule_id!r}: invalid regex: {exc}") from exc
        violations = notna & (matched if cfg.inverse else ~matched)
        label = "does not match" if not cfg.inverse else "matches forbidden pattern"
        return self._finalize(
            df, audit, violations, cfg.column,
            lambda p: f"value {s.loc[p]!r} {label} pattern {cfg.pattern!r}",
        )


@register
class UniqueKeyRule(CleaningRule, _CustomRuleMixin):
    rule_type = "unique_key"
    description = "Enforce uniqueness of one or more key columns."
    requires_full_dataset = True

    def apply(self, df: pd.DataFrame, audit: AuditCollector) -> pd.DataFrame:
        cfg: UniqueKeyRuleConfig = self.cfg
        missing = [c for c in cfg.columns if c not in df.columns]
        if missing:
            raise RuleError(
                f"rule {self.rule_id!r}: key column(s) {missing} not found"
            )
        dup = df.duplicated(subset=cfg.columns, keep=False)
        return self._finalize(
            df, audit, dup, cfg.columns[0],
            lambda p: f"duplicate key {cfg.columns} across rows: "
            f"{[str(df[c].loc[p]) for c in cfg.columns]}",
        )


@register
class CrossColumnRule(CleaningRule, _CustomRuleMixin):
    rule_type = "cross_column"
    description = "Compare two columns, or a column against a constant."

    def apply(self, df: pd.DataFrame, audit: AuditCollector) -> pd.DataFrame:
        cfg: CrossColumnRuleConfig = self.cfg
        left = self._column(df, cfg.left)
        left_num = pd.to_numeric(left, errors="coerce") if cfg.numeric else left

        if cfg.right_column is not None:
            right = self._column(df, cfg.right_column)
            right_num = pd.to_numeric(right, errors="coerce") if cfg.numeric else right
            label = f"column {cfg.right_column!r}"
        else:
            right_num = cfg.right_value
            label = f"constant {cfg.right_value!r}"

        if cfg.factor_column is not None:
            factor = pd.to_numeric(self._column(df, cfg.factor_column), errors="coerce")
            right_num = right_num * factor
            label += f" * column {cfg.factor_column!r}"

        ops = {
            "==": lambda a, b: a == b,
            "!=": lambda a, b: a != b,
            ">": lambda a, b: a > b,
            ">=": lambda a, b: a >= b,
            "<": lambda a, b: a < b,
            "<=": lambda a, b: a <= b,
        }
        op = ops[cfg.operator]
        with np.errstate(invalid="ignore"):
            result = op(left_num, right_num)
        right_missing = right_num.isna() if hasattr(right_num, "isna") else pd.isna(right_num)
        if not hasattr(right_missing, "index"):
            right_missing = pd.Series(bool(right_missing), index=df.index)
        comparable = left.notna() & ~right_missing
        violations = comparable & ~result.fillna(True)
        return self._finalize(
            df, audit, violations, cfg.left,
            lambda p: f"{cfg.left}={left.loc[p]!r} {cfg.operator} {label} failed",
        )


@register
class ConditionalRequiredRule(CleaningRule, _CustomRuleMixin):
    rule_type = "conditional_required"
    description = "Require a field to be present when a condition holds."

    def apply(self, df: pd.DataFrame, audit: AuditCollector) -> pd.DataFrame:
        cfg: ConditionalRequiredRuleConfig = self.cfg
        s = self._column(df, cfg.column)
        when = self._column(df, cfg.when_column)
        if cfg.when_operator == "==":
            cond = when.astype(str).str.strip() == str(cfg.when_value)
        else:
            cond = when.astype(str).str.strip() != str(cfg.when_value)
        empty = s.isna() | (s.astype(str).str.strip() == "")
        violations = cond & empty
        return self._finalize(
            df, audit, violations, cfg.column,
            lambda p: f"field {cfg.column!r} is required when "
            f"{cfg.when_column} {cfg.when_operator} {cfg.when_value!r}",
        )
