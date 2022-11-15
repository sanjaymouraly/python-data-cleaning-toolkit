"""String standardization: trim, case, unicode normalization, label mappings.

Sensitive rule of thumb encoded here: only explicitly selected columns are
touched. Identifiers and free-text columns stay untouched unless the user
names them.
"""

from __future__ import annotations

import unicodedata

import pandas as pd

from ..auditing.audit import AuditCollector
from ..config.schema import StringStandardizeRuleConfig
from .base import CleaningRule, register


def _apply_case(value: str, mode: str) -> str:
    if mode == "lower":
        return value.lower()
    if mode == "upper":
        return value.upper()
    if mode == "title":
        return value.title()
    if mode == "sentence":
        return value[:1].upper() + value[1:].lower() if value else value
    return value


@register
class StringStandardizeRule(CleaningRule):
    rule_type = "string_standardize"
    description = (
        "Trim whitespace, normalize case/unicode and apply label mappings on "
        "explicitly selected text columns. Original values are preserved in "
        "the audit trail."
    )

    def apply(self, df: pd.DataFrame, audit: AuditCollector) -> pd.DataFrame:
        cfg: StringStandardizeRuleConfig = self.cfg
        if cfg.columns is not None:
            columns = self._resolve_columns(df, cfg.columns)
        else:
            columns = [str(c) for c in df.columns if df[c].dtype == object]
        exclude = set(cfg.exclude_columns)
        columns = [c for c in columns if c not in exclude]

        warnings: list[str] = []
        for col in columns:
            if df[col].dtype != object:
                self._warn(
                    warnings,
                    f"column {col!r} is not a text column; skipped (values preserved)",
                )
                continue
            self._standardize(df, col, audit)
        self._warnings = warnings
        return df

    def _standardize(self, df: pd.DataFrame, col: str, audit: AuditCollector) -> None:
        cfg = self.cfg
        s = df[col]
        notna = s.notna()
        work = s.where(notna, "").astype(str)

        if cfg.trim_whitespace:
            work = work.str.strip()
        if cfg.collapse_internal_whitespace:
            work = work.str.replace(r"\s+", " ", regex=True)
        if cfg.unicode_normalize != "none":
            mapper = {
                v: unicodedata.normalize(cfg.unicode_normalize, v) for v in work.unique()
            }
            work = work.map(mapper)
        if cfg.case != "none":
            mapper = {v: _apply_case(v, cfg.case) for v in work.unique()}
            work = work.map(mapper)
        if cfg.value_mappings:
            mappings = cfg.value_mappings

            def map_value(v: str) -> str:
                if cfg.mapping_ignore_case:
                    key = v.strip().lower()
                    for k, target in mappings.items():
                        if key == k.strip().lower():
                            return target
                    return v
                return mappings.get(v, v)

            mapper = {v: map_value(v) for v in work.unique()}
            work = work.map(mapper)

        changed = notna & (work != s.astype(str))
        if not changed.any():
            return
        reasons = []
        if cfg.trim_whitespace:
            reasons.append("trimmed")
        if cfg.collapse_internal_whitespace:
            reasons.append("whitespace collapsed")
        if cfg.case != "none":
            reasons.append(f"case={cfg.case}")
        if cfg.unicode_normalize != "none":
            reasons.append(f"unicode={cfg.unicode_normalize}")
        if cfg.value_mappings:
            reasons.append("label mapping applied")
        reason = "string standardization: " + ", ".join(reasons)
        for pos in df.index[changed.to_numpy()]:
            audit.add_change(
                rule_id=self.rule_id,
                rule_type=self.rule_type,
                row=int(pos),
                column=col,
                original=s.loc[pos],
                modified=work.loc[pos],
                reason=reason,
            )
        df[col] = work.where(notna, s)
