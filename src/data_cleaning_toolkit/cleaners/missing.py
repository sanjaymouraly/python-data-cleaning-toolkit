"""Missing-data rule: marker normalization plus an explicit fill/remove strategy."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..auditing.audit import AuditCollector
from ..config.schema import MissingValuesRuleConfig
from .base import CleaningRule, iter_changes, register


@register
class MissingValuesRule(CleaningRule):
    rule_type = "missing_values"
    description = (
        "Normalize configured null markers to real <NA>, then apply one explicit "
        "strategy: retain, remove rows/columns, fill constant, mean/median/mode, "
        "or forward/backward fill. Zeros are never treated as missing."
    )
    requires_full_dataset = True  # remove_columns & statistical fills need the whole frame

    def apply(self, df: pd.DataFrame, audit: AuditCollector) -> pd.DataFrame:
        cfg: MissingValuesRuleConfig = self.cfg
        columns = self._resolve_columns(df, cfg.columns)
        markers = {m.lower() for m in cfg.null_markers}
        warnings = self._warnings

        # 1) normalize text null markers to real NaN (recorded, only for object columns)
        for col in columns:
            if col not in df.columns:
                continue
            s = df[col]
            if s.dtype != object and not pd.api.types.is_string_dtype(s):
                continue
            values = s.astype("string")
            stripped = values.str.strip()
            if cfg.case_insensitive_markers:
                marker_mask = stripped.str.lower().isin(markers) & values.notna()
            else:
                marker_mask = values.isin(set(cfg.null_markers)) & values.notna()
            marker_mask = marker_mask.fillna(False).astype(bool)
            if not marker_mask.any():
                continue
            new_values = s.where(~marker_mask, np.nan)
            for pos, old, _new in iter_changes(df, marker_mask, col, new_values):
                audit.add_change(
                    rule_id=self.rule_id,
                    rule_type=self.rule_type,
                    row=pos,
                    column=col,
                    original=old,
                    modified="<NA>",
                    reason=f"null marker {str(old)!r} normalized to <NA>",
                    kind="normalize_marker",
                )
            df[col] = new_values

        # 2) strategy on actual NaNs
        strategy = cfg.strategy
        if strategy == "retain":
            return df

        selected = [c for c in columns if c in df.columns]
        if strategy == "remove_rows":
            mask = (
                df[selected].isna().any(axis=1)
                if cfg.scope == "any"
                else df[selected].isna().all(axis=1)
            )
            self._remove_rows(df, mask, audit, reason_suffix=", ".join(selected))
            return df.loc[~mask.to_numpy()].reset_index(drop=True)

        if strategy == "remove_columns":
            dropped = []
            for col in selected:
                if df[col].isna().any():
                    n = int(df[col].isna().sum())
                    audit.add_change(
                        rule_id=self.rule_id,
                        rule_type=self.rule_type,
                        row=None,
                        column=col,
                        original=f"<column with {n} missing value(s)>",
                        modified="<column removed>",
                        reason="strategy remove_columns: column contains missing values",
                        kind="column_removed",
                    )
                    dropped.append(col)
            return df.drop(columns=dropped)

        if strategy == "fill_constant":
            value = cfg.fill_value
            for col in selected:
                mask = df[col].isna()
                if not mask.any():
                    continue
                # explicit object-dtype construction: fillna must not silently
                # downcast the column's dtype (pandas deprecation behavior)
                arr = df[col].to_numpy(dtype=object, copy=True)
                arr[mask.to_numpy()] = value
                new_values = pd.Series(arr, index=df.index, dtype=object)
                for pos, _old_na, _new in iter_changes(df, mask, col, new_values):
                    audit.add_change(
                        rule_id=self.rule_id,
                        rule_type=self.rule_type,
                        row=pos,
                        column=col,
                        original="<NA>",
                        modified=value,
                        reason=f"missing value filled with constant {value!r}",
                    )
                df[col] = new_values
            return df

        if strategy in {"mean", "median", "mode"}:
            return self._statistical_fill(df, selected, audit, warnings)

        if strategy in {"ffill", "bfill"}:
            method = "ffill" if strategy == "ffill" else "bfill"
            for col in selected:
                mask = df[col].isna()
                if not mask.any():
                    continue
                filled = df[col].ffill() if method == "ffill" else df[col].bfill()
                still = filled.isna() & mask
                if still.any():
                    self._warn(
                        warnings,
                        f"column {col!r}: {int(still.sum())} missing value(s) had "
                        f"no adjacent value to {method}-fill and remain <NA>",
                    )
                for pos, _old, new in iter_changes(df, mask & filled.notna(), col, filled):
                    audit.add_change(
                        rule_id=self.rule_id,
                        rule_type=self.rule_type,
                        row=pos,
                        column=col,
                        original="<NA>",
                        modified=new,
                        reason=f"missing value {method}-filled from adjacent row",
                    )
                df[col] = filled
            return df

        raise AssertionError(f"unhandled strategy {strategy}")  # pragma: no cover

    def _statistical_fill(
        self,
        df: pd.DataFrame,
        selected: list[str],
        audit: AuditCollector,
        warnings: list[str],
    ) -> pd.DataFrame:
        strategy = self.cfg.strategy
        for col in selected:
            mask = df[col].isna()
            if not mask.any():
                continue
            if strategy in {"mean", "median"}:
                numeric = pd.to_numeric(df[col], errors="coerce")
                usable = (
                    numeric.notna().sum() > 0
                    and (numeric.notna().sum() / max(1, len(numeric))) > 0.5
                )
                if not usable:
                    self._warn(
                        warnings,
                        f"column {col!r} is not numeric; {strategy} skipped "
                        "(invalid statistical imputation prevented)",
                    )
                    continue
                if strategy == "mean":
                    fill = float(numeric.mean())
                    label = f"mean ({fill:.6g})"
                else:
                    fill = float(numeric.median())
                    label = f"median ({fill:.6g})"
            else:  # mode works for any dtype
                modes = df[col].mode(dropna=True)
                if modes.empty:
                    self._warn(warnings, f"column {col!r} has no non-null values; skipped")
                    continue
                fill = modes.iloc[0]
                label = f"mode ({fill!r})"
            new_values = df[col].where(~mask, fill)
            for pos, _old, new in iter_changes(df, mask, col, new_values):
                audit.add_change(
                    rule_id=self.rule_id,
                    rule_type=self.rule_type,
                    row=pos,
                    column=col,
                    original="<NA>",
                    modified=new,
                    reason=f"missing value imputed with column {label}",
                )
            df[col] = new_values
        return df

    def _remove_rows(
        self, df: pd.DataFrame, mask: pd.Series, audit: AuditCollector, reason_suffix: str
    ) -> None:
        positions = df.index[mask.to_numpy()]
        for pos, row in zip(positions, df[mask.to_numpy()].itertuples(index=False, name=None), strict=True):
            audit.add_removed_row(
                rule_id=self.rule_id,
                rule_type=self.rule_type,
                row=int(pos),
                reason=f"row removed: missing value(s) in column(s) {reason_suffix}",
                row_series=dict(zip(df.columns, row, strict=True)),
            )
