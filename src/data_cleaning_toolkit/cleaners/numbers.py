"""Numeric validation: ranges, signs, precision, separators and outliers.

By default this rule *flags* problems (including statistical outliers) and
never deletes data unless an explicit removal policy is configured.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..auditing.audit import AuditCollector
from ..config.schema import NumericValidateRuleConfig
from .base import CleaningRule, register


def parse_numeric(s: pd.Series, thousands_sep: str | None, decimal_sep: str | None):
    text = s.astype("string")
    if thousands_sep:
        text = text.str.replace(thousands_sep, "", regex=False)
    if decimal_sep and decimal_sep != ".":
        text = text.str.replace(decimal_sep, ".", regex=False)
    return pd.to_numeric(text, errors="coerce")


@register
class NumericValidateRule(CleaningRule):
    rule_type = "numeric_validate"
    description = (
        "Validate numeric columns against explicit bounds, sign and precision "
        "rules; detect unparseable values and statistical outliers (IQR or "
        "Z-score). Outliers are flagged by default, never deleted silently."
    )
    requires_full_dataset = True  # IQR/Z-score need global statistics

    def apply(self, df: pd.DataFrame, audit: AuditCollector) -> pd.DataFrame:
        cfg: NumericValidateRuleConfig = self.cfg
        columns = self._resolve_columns(df, cfg.columns)
        warnings: list[str] = []
        for col in columns:
            if df[col].dtype != object and not pd.api.types.is_numeric_dtype(df[col]):
                self._warn(
                    warnings, f"column {col!r} is neither text nor numeric; skipped"
                )
                continue
            df = self._validate(df, col, audit, warnings)
        self._warnings = warnings
        return df

    def _validate(
        self,
        df: pd.DataFrame,
        col: str,
        audit: AuditCollector,
        warnings: list[str],
    ) -> pd.DataFrame:
        cfg = self.cfg
        s = df[col]
        isna = s.isna()
        num = s if pd.api.types.is_numeric_dtype(s) else parse_numeric(s, cfg.thousands_sep, cfg.decimal_sep)

        unparseable = (~isna) & num.isna() & s.astype(str).str.strip().ne("")
        below = pd.Series(False, index=df.index)
        above = pd.Series(False, index=df.index)
        if cfg.min is not None:
            below = num.notna() & (num < cfg.min)
        if cfg.max is not None:
            above = num.notna() & (num > cfg.max)
        negative = num.notna() & (num < 0) & (not cfg.allow_negative)
        fractional = pd.Series(False, index=df.index)
        if not cfg.allow_decimal:
            fractional = num.notna() & ~np.isclose(num % 1, 0, atol=1e-9)

        removal_needed = pd.Series(False, index=df.index)

        def handle(mask: pd.Series, message_fn) -> None:
            nonlocal removal_needed
            if mask.empty or not mask.any():
                return
            for pos in df.index[mask.to_numpy()]:
                audit.add_flag(
                    rule_id=self.rule_id,
                    rule_type=self.rule_type,
                    row=int(pos),
                    column=col,
                    value=str(s.loc[pos]),
                    message=message_fn(pos),
                )
            if cfg.on_invalid == "remove_rows":
                removal_needed |= mask

        handle(unparseable, lambda p: f"value {s.loc[p]!r} is not a valid number")
        handle(below, lambda p: f"value {num.loc[p]} is below configured minimum {cfg.min}")
        handle(above, lambda p: f"value {num.loc[p]} is above configured maximum {cfg.max}")
        handle(negative, lambda p: f"negative value {num.loc[p]} not allowed")
        handle(fractional, lambda p: f"unexpected decimal value {num.loc[p]}")

        # outliers, computed on non-violating values
        if cfg.outlier_method != "none":
            base = num.where(~(unparseable | below | above | negative | fractional))
            outlier_mask = pd.Series(False, index=df.index)
            valid = base.notna()
            if valid.sum() >= 4:
                if cfg.outlier_method == "iqr":
                    q1, q3 = base.quantile(0.25), base.quantile(0.75)
                    iqr = q3 - q1
                    if iqr > 0:
                        lo, hi = q1 - cfg.iqr_k * iqr, q3 + cfg.iqr_k * iqr
                        outlier_mask = valid & ((base < lo) | (base > hi))
                else:
                    mean, std = base.mean(), base.std()
                    if std and std > 0:
                        z = (base - mean).abs() / std
                        outlier_mask = valid & (z > cfg.zscore_threshold)
            if outlier_mask.any():
                for pos in df.index[outlier_mask.to_numpy()]:
                    audit.add_flag(
                        rule_id=self.rule_id,
                        rule_type=self.rule_type,
                        row=int(pos),
                        column=col,
                        value=str(s.loc[pos]),
                        message=(
                            f"statistical outlier ({cfg.outlier_method}) value "
                            f"{num.loc[pos]} - flagged for review, not modified"
                        ),
                    )
                if cfg.outlier_action == "remove_rows":
                    removal_needed |= outlier_mask

        if removal_needed.any():
            rows = df.index[removal_needed.to_numpy()]
            for pos, row in zip(rows, df.loc[rows].itertuples(index=False, name=None), strict=True):
                audit.add_removed_row(
                    rule_id=self.rule_id,
                    rule_type=self.rule_type,
                    row=int(pos),
                    reason=f"row removed: numeric validation failed in column {col!r}",
                    row_series=dict(zip(df.columns, row, strict=True)),
                )
            df = df.loc[~removal_needed.to_numpy()].reset_index(drop=True)
        return df
