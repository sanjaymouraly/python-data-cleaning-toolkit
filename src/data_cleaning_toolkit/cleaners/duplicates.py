"""Duplicate detection: exact or key-based, with explicit keep policies."""

from __future__ import annotations

import pandas as pd

from ..auditing.audit import AuditCollector
from ..config.schema import DuplicatesRuleConfig
from .base import CleaningRule, register


@register
class DuplicatesRule(CleaningRule):
    rule_type = "duplicates"
    description = (
        "Detect exact duplicates (or duplicates on key columns) and apply a "
        "policy: keep first/last, remove all copies, or flag only. "
        "Never fuzzy by default."
    )
    requires_full_dataset = True  # global comparison by definition

    def apply(self, df: pd.DataFrame, audit: AuditCollector) -> pd.DataFrame:
        cfg: DuplicatesRuleConfig = self.cfg
        subset = self._resolve_columns(df, cfg.columns)
        key = df[subset]
        if cfg.strip_whitespace or cfg.ignore_case:
            key = key.astype(str).apply(
                lambda col: col.str.strip().str.lower() if cfg.ignore_case else col.str.strip()
            )

        if cfg.flag_only:
            dup_mask = key.duplicated(keep="first")
            group_sizes = key.groupby(list(key.columns), dropna=False)[key.columns[0]].transform("size")
            for pos in df.index[dup_mask.to_numpy()]:
                audit.add_flag(
                    rule_id=self.rule_id,
                    rule_type=self.rule_type,
                    row=int(pos),
                    column=None,
                    value="",
                    message=(
                        f"duplicate row on key {subset} (group of "
                        f"{int(group_sizes.loc[pos])} row(s)); review suggested"
                    ),
                )
            return df

        keep = None if cfg.keep == "none" else cfg.keep
        dup_mask = key.duplicated(keep=keep if keep else False)
        if cfg.keep == "none":
            dup_mask = key.duplicated(keep=False)

        drop_pos = df.index[dup_mask.to_numpy()]
        reason = {
            "first": "duplicate row removed (kept first occurrence)",
            "last": "duplicate row removed (kept last occurrence)",
            "none": "duplicate row removed (policy keeps no copies)",
        }[cfg.keep]
        for pos, row in zip(drop_pos, df.loc[drop_pos].itertuples(index=False, name=None), strict=True):
            audit.add_removed_row(
                rule_id=self.rule_id,
                rule_type=self.rule_type,
                row=int(pos),
                reason=reason + f" on key {subset}" if subset != list(df.columns) else reason,
                row_series=dict(zip(df.columns, row, strict=True)),
            )
        return df.loc[~dup_mask.to_numpy()].reset_index(drop=True)
