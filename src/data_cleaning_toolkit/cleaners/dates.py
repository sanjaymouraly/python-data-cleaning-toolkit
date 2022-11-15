"""Date normalization with explicit ambiguity policy.

Guarantees
----------
* ISO 8601 and explicitly configured strptime formats are always honored.
* Slash/dash/dot numeric dates (e.g. ``03/04/2026``) are only auto-resolved
  when the day/month order is *unambiguous* from the values themselves;
  genuinely ambiguous cells are flagged and left untouched unless the config
  sets ``dayfirst`` explicitly.
* Invalid dates (e.g. ``2026-02-30``) follow ``on_error`` and are never
  silently dropped or guessed.
* Unambiguous textual dates ("March 4, 2026") use a fixed, documented format
  list; anything else needs ``input_formats`` or ``allow_fallback_parsing``.
"""

from __future__ import annotations

import re
from datetime import datetime

import pandas as pd

from ..auditing.audit import AuditCollector
from ..config.schema import DateNormalizeRuleConfig
from ..core.errors import RuleError
from .base import CleaningRule, register

_NUMERIC_DATE_RE = re.compile(r"^\s*(\d{1,2})([./-])(\d{1,2})\2(\d{2,4})\s*$")
_UNAMBIGUOUS_TEXT_FORMATS = (
    "%B %d, %Y",
    "%b %d, %Y",
    "%d %B %Y",
    "%d %b %Y",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%d %B %Y %H:%M",
)
_NUMERIC_ORDERS = ("%d/%m/%Y", "%m/%d/%Y")


@register
class DateNormalizeRule(CleaningRule):
    rule_type = "date_normalize"
    description = (
        "Parse dates from configured/ISO/unambiguous formats, flag ambiguous "
        "numeric dates instead of guessing, normalize to the configured output "
        "format, and optionally convert timezones."
    )

    def apply(self, df: pd.DataFrame, audit: AuditCollector) -> pd.DataFrame:
        cfg: DateNormalizeRuleConfig = self.cfg
        columns = self._resolve_columns(df, cfg.columns)
        for col in columns:
            df = self._normalize_column(df, col, audit)
        return df

    # ------------------------------------------------------------------
    def _normalize_column(
        self, df: pd.DataFrame, col: str, audit: AuditCollector
    ) -> pd.DataFrame:
        cfg = self.cfg
        s = df[col]
        isna = s.isna()
        parsed = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
        pending = ~isna

        if cfg.input_formats:
            for fmt in cfg.input_formats:
                if not pending.any():
                    break
                attempt = pd.to_datetime(
                    s.loc[pending].astype(str), format=fmt, errors="coerce"
                )
                parsed.loc[pending] = attempt
                pending = parsed.isna() & ~isna
        else:
            # Strict ISO 8601 first (unambiguous by definition).
            iso = pd.to_datetime(s.loc[pending].astype(str), format="ISO8601", errors="coerce")
            if getattr(iso.dtype, "tz", None) is not None:
                # offset-aware inputs keep their timezone (converted later if requested)
                parsed = pd.Series(pd.NaT, index=df.index, dtype=iso.dtype)
            parsed.loc[pending] = iso
            pending = parsed.isna() & ~isna
            handled: set = set()
            if pending.any():
                parsed = self._parse_numeric_dates(df, col, s, parsed, pending, audit, handled)
                handled_mask = pd.Series(s.index.isin(handled), index=df.index)
                pending = (parsed.isna() & ~isna & ~handled_mask)
            else:
                handled_mask = pd.Series(False, index=df.index)
            if pending.any():
                parsed = self._parse_unambiguous_text(df, col, s, parsed, pending)
                pending = parsed.isna() & ~isna & ~handled_mask
            if pending.any() and cfg.allow_fallback_parsing:
                parsed.loc[pending] = pd.to_datetime(
                    s.loc[pending].astype(str),
                    errors="coerce",
                    dayfirst=bool(cfg.dayfirst),
                )
                pending = parsed.isna() & ~isna & ~handled_mask

        # already-datetime cells (Excel) - reuse as-is
        already = pending & s.map(lambda v: isinstance(v, pd.Timestamp))
        if already.any():
            parsed.loc[already] = pd.to_datetime(s.loc[already])
            pending = parsed.isna() & ~isna

        invalid = pending  # non-null but unparseable at this point
        invalid.index = df.index
        if invalid.any():
            self._flag_invalid(df, audit, col, invalid)
            on_error = cfg.on_error
            if on_error == "fail":
                raise RuleError(
                    f"rule {self.rule_id!r}: {int(invalid.sum())} unparseable date(s) in "
                    f"column {col!r}; on_error=fail aborts the run"
                )
            if on_error == "remove_row":
                kept = ~invalid
                rows = df.index[invalid.to_numpy()]
                for pos, row in zip(rows, df.loc[rows].itertuples(index=False, name=None), strict=True):
                    audit.add_removed_row(
                        rule_id=self.rule_id,
                        rule_type=self.rule_type,
                        row=int(pos),
                        reason=f"row removed: invalid date in column {col!r}",
                        row_series=dict(zip(df.columns, row, strict=True)),
                    )
                df = df.loc[kept.to_numpy()].reset_index(drop=True)
                parsed = parsed.loc[df.index]
                s = df[col]
                isna = s.isna()
            elif on_error == "set_null":
                s = s.where(~invalid, pd.NA)
                for pos in df.index[invalid.to_numpy()]:
                    audit.add_change(
                        rule_id=self.rule_id,
                        rule_type=self.rule_type,
                        row=int(pos),
                        column=col,
                        original=df[col].loc[pos],
                        modified="<NA>",
                        reason="invalid date set to <NA>",
                    )

        parsed = self._apply_timezone(parsed, cfg.target_tz)

        if cfg.output_type == "date":
            new_values = s.where(parsed.isna(), parsed)
        else:
            formatted = parsed.dt.strftime(cfg.output_format)
            new_values = s.where(parsed.isna(), formatted)

        changed = parsed.notna() & (new_values.astype(str) != s.astype(str))
        for pos in df.index[changed.to_numpy()]:
            audit.add_change(
                rule_id=self.rule_id,
                rule_type=self.rule_type,
                row=int(pos),
                column=col,
                original=s.loc[pos],
                modified=new_values.loc[pos],
                reason=(
                    f"date normalized to {cfg.output_format!r}"
                    if cfg.output_type == "text"
                    else "value converted to datetime"
                ),
            )
        df[col] = new_values
        return df

    # ------------------------------------------------------------------
    def _parse_numeric_dates(
        self,
        df: pd.DataFrame,
        col: str,
        s: pd.Series,
        parsed: pd.Series,
        pending: pd.Series,
        audit: AuditCollector,
        handled: set,
    ) -> pd.Series:
        dayfirst_cfg: bool | None = self.cfg.dayfirst
        for pos in df.index[pending.to_numpy()]:
            raw = str(s.loc[pos])
            m = _NUMERIC_DATE_RE.match(raw)
            if not m:
                continue
            a, b, year_raw = m.group(1), m.group(3), m.group(4)
            n1, n2 = int(a), int(b)
            year = int(year_raw)
            if year < 100:
                year += 2000  # documented convention: two-digit years are 2000-2099

            if n1 > 12 and n2 > 12:
                audit.add_flag(
                    rule_id=self.rule_id,
                    rule_type=self.rule_type,
                    row=int(pos),
                    column=col,
                    value=raw,
                    message=f"invalid date: both day components out of range in {raw!r}",
                )
                handled.add(pos)
                continue
            if n1 <= 12 and n2 <= 12 and dayfirst_cfg is None:
                audit.add_flag(
                    rule_id=self.rule_id,
                    rule_type=self.rule_type,
                    row=int(pos),
                    column=col,
                    value=raw,
                    message=(
                        f"ambiguous date {raw!r} left unchanged - both parts could be "
                        "day or month; set 'dayfirst' explicitly in the config to "
                        "resolve this format"
                    ),
                )
                handled.add(pos)
                continue
            day, month = (n1, n2) if (dayfirst_cfg or (n1 > 12)) else (n2, n1)
            try:
                parsed.loc[pos] = pd.Timestamp(datetime(year, month, day))
            except ValueError:
                audit.add_flag(
                    rule_id=self.rule_id,
                    rule_type=self.rule_type,
                    row=int(pos),
                    column=col,
                    value=raw,
                    message=f"invalid calendar date {raw!r} (day/month out of range)",
                )
                handled.add(pos)
        return parsed

    def _parse_unambiguous_text(
        self,
        df: pd.DataFrame,
        col: str,
        s: pd.Series,
        parsed: pd.Series,
        pending: pd.Series,
    ) -> pd.Series:
        for fmt in _UNAMBIGUOUS_TEXT_FORMATS:
            if not pending.any():
                break
            attempt = pd.to_datetime(
                s.loc[pending].astype(str), format=fmt, errors="coerce"
            )
            parsed.loc[pending] = attempt
            pending = parsed.isna() & ~s.isna()
        return parsed

    def _apply_timezone(self, parsed: pd.Series, target_tz: str | None) -> pd.Series:
        if not target_tz:
            return parsed
        try:
            import zoneinfo

            zoneinfo.ZoneInfo(target_tz)
        except Exception as exc:  # unknown tz name
            raise RuleError(f"rule {self.rule_id!r}: unknown timezone {target_tz!r}") from exc
        if parsed.dt.tz is None:
            return parsed.dt.tz_localize(target_tz)
        return parsed.dt.tz_convert(target_tz)

    def _flag_invalid(
        self, df: pd.DataFrame, audit: AuditCollector, col: str, invalid: pd.Series
    ) -> None:
        s = df[col]
        for pos in df.index[invalid.to_numpy()]:
            audit.add_flag(
                rule_id=self.rule_id,
                rule_type=self.rule_type,
                row=int(pos),
                column=col,
                value=str(s.loc[pos]),
                message=f"unparseable/invalid date {str(s.loc[pos])!r} left unchanged",
            )
