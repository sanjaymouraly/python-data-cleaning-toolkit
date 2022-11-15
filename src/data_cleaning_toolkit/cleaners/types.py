"""Safe explicit type conversions with leading-zero protection and error policies."""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from ..auditing.audit import AuditCollector
from ..config.schema import TypeConversionRuleConfig
from ..core.errors import RuleError
from .base import CleaningRule, register

_LEADING_ZERO_RE = re.compile(r"^\s*0\d+\s*$")
_INT64_MAX = 2**63 - 1


def _prep_text(text: pd.Series, cfg: TypeConversionRuleConfig) -> pd.Series:
    """Apply configured thousands/decimal separators to a string series."""
    work = text.copy()
    if cfg.thousands_sep:
        work = work.str.replace(cfg.thousands_sep, "", regex=False)
    if cfg.decimal_sep and cfg.decimal_sep != ".":
        work = work.str.replace(cfg.decimal_sep, ".", regex=False)
    return work


@register
class TypeConversionRule(CleaningRule):
    rule_type = "type_conversion"
    description = (
        "Convert one column to an explicit type. Invalid/lossy values follow the "
        "configured on_error policy and are never silently coerced. Identifiers "
        "with leading zeros can be protected (keep_leading_zeros)."
    )

    def apply(self, df: pd.DataFrame, audit: AuditCollector) -> pd.DataFrame:
        cfg: TypeConversionRuleConfig = self.cfg
        if cfg.column not in df.columns:
            raise RuleError(
                f"rule {self.rule_id!r}: column {cfg.column!r} not found "
                f"(available: {[str(c) for c in df.columns]})"
            )
        if cfg.target == "text":
            return self._to_text(df, audit)
        if cfg.target == "category":
            n_before = df[cfg.column].nunique(dropna=True)
            df[cfg.column] = df[cfg.column].astype("category")
            audit.add_change(
                rule_id=self.rule_id,
                rule_type=self.rule_type,
                row=None,
                column=cfg.column,
                original=f"text column with {n_before} distinct value(s)",
                modified=f"category column with {n_before} categories",
                reason="storage optimized to categorical dtype",
            )
            return df
        if cfg.target == "boolean":
            return self._to_boolean(df, audit)
        return self._to_numeric(df, audit)

    # ------------------------------------------------------------------
    def _to_text(self, df: pd.DataFrame, audit: AuditCollector) -> pd.DataFrame:
        col = self.cfg.column
        s = df[col]
        notna = s.notna()
        as_text = s.where(~notna, s.astype(str))
        changed = notna & (as_text.astype(str) != s.astype(str))
        for pos, old, new in self._iter(col, df, changed, as_text):
            audit.add_change(
                rule_id=self.rule_id,
                rule_type=self.rule_type,
                row=pos,
                column=col,
                original=old,
                modified=new,
                reason="value converted to text",
            )
        df[col] = as_text
        return df

    def _to_boolean(self, df: pd.DataFrame, audit: AuditCollector) -> pd.DataFrame:
        cfg = self.cfg
        col = cfg.column
        s = df[col]
        notna = s.notna()
        text = s.astype(str).str.strip().str.lower()
        true_set = {v.lower() for v in cfg.true_values}
        false_set = {v.lower() for v in cfg.false_values}
        is_true = notna & text.isin(true_set)
        is_false = notna & text.isin(false_set)
        invalid = notna & ~is_true & ~is_false
        result = pd.Series(pd.NA, index=df.index, dtype="boolean")
        self._handle_errors(df, audit, invalid, "value cannot be parsed as boolean")
        result.loc[df.index[is_true.to_numpy()]] = True
        result.loc[df.index[is_false.to_numpy()]] = False
        result.loc[df.index[(~notna).to_numpy()]] = pd.NA
        df[col] = result
        changed = notna & result.astype("string").str.lower().ne(text)
        for pos in df.index[changed.fillna(False).to_numpy()]:
            audit.add_change(
                rule_id=self.rule_id,
                rule_type=self.rule_type,
                row=int(pos),
                column=col,
                original=s.loc[pos],
                modified=bool(result.loc[pos]),
                reason="value converted to boolean",
            )
        return df

    def _to_numeric(self, df: pd.DataFrame, audit: AuditCollector) -> pd.DataFrame:
        cfg = self.cfg
        col = cfg.column
        s = df[col]
        notna = s.notna()
        text = s.astype("string")
        # empty / whitespace-only text is treated as missing, not invalid
        blank = notna & text.str.strip().eq("").fillna(False)
        effective = notna & ~blank

        work = _prep_text(text, cfg)
        num = pd.to_numeric(work, errors="coerce")

        invalid = effective & num.isna()
        protected = pd.Series(False, index=df.index)
        if cfg.keep_leading_zeros:
            protected = effective & text.str.match(_LEADING_ZERO_RE).fillna(False)
            invalid = invalid & ~protected

        non_integer = pd.Series(False, index=df.index)
        overflow = pd.Series(False, index=df.index)
        if cfg.target == "integer":
            non_integer = effective & num.notna() & ~np.isclose(num % 1, 0, atol=1e-9)
            overflow = effective & num.notna() & (num.abs() > _INT64_MAX)

        errors = invalid | non_integer | overflow
        messages = {
            "invalid": "value cannot be parsed as a number",
            "precision": "value has a fractional part; integer conversion would lose precision",
            "overflow": "value exceeds 64-bit integer range",
        }
        if errors.any():
            self._handle_errors(df, audit, invalid, messages["invalid"])
            self._handle_errors(df, audit, non_integer, messages["precision"])
            self._handle_errors(df, audit, overflow, messages["overflow"])

        for pos in df.index[protected.to_numpy()]:
            audit.add_flag(
                rule_id=self.rule_id,
                rule_type=self.rule_type,
                row=int(pos),
                column=col,
                value=str(s.loc[pos]),
                message="value kept as text to preserve leading zeros (identifier?)",
            )

        on_error = cfg.on_error
        error_mask = errors
        if on_error == "remove_row" and error_mask.any():
            rows = df.index[error_mask.to_numpy()]
            for pos, row in zip(rows, df.loc[rows].itertuples(index=False, name=None), strict=True):
                audit.add_removed_row(
                    rule_id=self.rule_id,
                    rule_type=self.rule_type,
                    row=int(pos),
                    reason=f"row removed: column {col!r} failed {cfg.target} conversion",
                    row_series=dict(zip(df.columns, row, strict=True)),
                )
            kept = ~error_mask.to_numpy()
            df = df.loc[kept].reset_index(drop=True)
            s = df[col]
            notna = s.notna()
            text = s.astype("string")
            blank = notna & text.str.strip().eq("").fillna(False)
            effective = notna & ~blank
            num = pd.to_numeric(_prep_text(text, cfg), errors="coerce")
            protected = pd.Series(False, index=df.index)
            # error masks are moot now: every offending row was removed
            errors = pd.Series(False, index=df.index)
            error_mask = errors
            invalid = errors
            non_integer = errors
            overflow = errors
        elif on_error == "set_null":
            new_s = s.where(~error_mask, np.nan)
            for pos in df.index[error_mask.to_numpy()]:
                audit.add_change(
                    rule_id=self.rule_id,
                    rule_type=self.rule_type,
                    row=int(pos),
                    column=col,
                    original=s.loc[pos],
                    modified="<NA>",
                    reason=f"unparseable value set to <NA> ({cfg.target} conversion)",
                )
            s = new_s

        valid = effective & ~errors & ~protected
        # untouched: error cells under flag policy (kept for review) and
        # leading-zero-protected cells. Blank cells are NOT untouched: they
        # become real <NA> below (empty text in a numeric column is missing).
        untouched = (~valid) & (error_mask | protected)

        # blank cells become real <NA> (recorded - an empty string in a numeric
        # column is a missing value, not the number zero)
        blank_effective = blank & ~untouched
        for pos in df.index[blank_effective.to_numpy()]:
            audit.add_change(
                rule_id=self.rule_id,
                rule_type=self.rule_type,
                row=int(pos),
                column=col,
                original=s.loc[pos],
                modified="<NA>",
                reason="empty value treated as <NA> during numeric conversion",
            )

        # Build as object first: flagged cells intentionally keep their original
        # text (mixed column = visible evidence), valid cells get numbers.
        final = pd.Series(np.nan, index=df.index, dtype=object)
        final.loc[valid] = num[valid]
        final.loc[untouched] = s.loc[untouched]
        final.loc[blank_effective] = np.nan
        if cfg.target == "integer":
            final.loc[valid] = final.loc[valid].astype("int64")
        else:
            final.loc[valid] = final.loc[valid].astype(float)
        if not untouched.any() and final.isna().any():
            df[col] = final.astype("Int64")
        elif not untouched.any():
            df[col] = final.astype("float64") if cfg.target == "decimal" else final
        else:
            df[col] = final

        # audit every successful textual->numeric conversion
        converted = valid & final.astype(str).ne(s.astype(str))
        for pos in df.index[converted.to_numpy()]:
            audit.add_change(
                rule_id=self.rule_id,
                rule_type=self.rule_type,
                row=int(pos),
                column=col,
                original=s.loc[pos],
                modified=final.loc[pos],
                reason=f"value converted to {cfg.target}",
            )
        return df

    # ------------------------------------------------------------------
    def _handle_errors(
        self, df: pd.DataFrame, audit: AuditCollector, mask: pd.Series, message: str
    ) -> None:
        if mask.empty or not mask.any():
            return
        col = self.cfg.column
        for pos in df.index[mask.to_numpy()]:
            audit.add_flag(
                rule_id=self.rule_id,
                rule_type=self.rule_type,
                row=int(pos),
                column=col,
                value=str(df[col].loc[pos]),
                message=message,
            )
        if self.cfg.on_error == "fail":
            raise RuleError(
                f"rule {self.rule_id!r}: {int(mask.sum())} value(s) in column "
                f"{col!r} failed conversion ({message}); on_error=fail aborts the run"
            )

    def _iter(self, column: str, df: pd.DataFrame, mask: pd.Series, new: pd.Series):
        from .base import iter_changes

        return iter_changes(df, mask, column, new)
