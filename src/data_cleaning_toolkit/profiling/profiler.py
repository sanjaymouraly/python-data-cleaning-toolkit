"""Dataset profiling: structure, missingness, duplicates, types and anomalies.

The profiler is read-only and deterministic. It produces a
:class:`ProfileReport` that both the dashboard and the HTML report render.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..core.errors import LimitExceededError

_PLACEHOLDERS = {-1, 999, 9999, 99999, 1900, 1970}
_UNIT_SUFFIX_RE = re.compile(r"^\s*(-?\d+(?:[.,]\d+)?)\s*([A-Za-zµ°%$€£]{1,4})\s*$")
_DATEISH_RE = re.compile(
    r"^\s*\d{4}[-/]\d{1,2}[-/]\d{1,2}([ T]\d{2}:\d{2}(:\d{2})?)?\s*$"
    r"|^\s*\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\s*$"
    r"|^\s*[A-Za-z]{3,9} \d{1,2},? \d{4}\s*$"
)
_NULL_MARKERS = {"", "n/a", "na", "null", "none", "nan", "unknown", "-", "?", "nil"}


@dataclass
class ColumnProfile:
    name: str
    pandas_dtype: str
    inferred_kind: str  # text | numeric | date-like | boolean | identifier
    missing: int
    missing_pct: float
    unique: int
    top_values: list[tuple[str, int]] = field(default_factory=list)
    numeric_stats: dict[str, float] | None = None
    outlier_candidates: int = 0
    mixed_types: list[str] = field(default_factory=list)
    whitespace_padded: int = 0
    null_marker_count: int = 0
    parseable_dates: int = 0
    distinct_units: list[str] = field(default_factory=list)
    case_variants: int = 0
    suspicious_values: int = 0

    def to_dict(self) -> dict[str, Any]:
        d = {
            "name": self.name,
            "pandas_dtype": self.pandas_dtype,
            "inferred_kind": self.inferred_kind,
            "missing": self.missing,
            "missing_pct": round(self.missing_pct, 2),
            "unique": self.unique,
            "top_values": [[v, c] for v, c in self.top_values],
            "mixed_types": self.mixed_types,
            "whitespace_padded": self.whitespace_padded,
            "null_marker_count": self.null_marker_count,
            "parseable_dates": self.parseable_dates,
            "distinct_units": self.distinct_units,
            "case_variants": self.case_variants,
            "suspicious_values": self.suspicious_values,
            "outlier_candidates": self.outlier_candidates,
        }
        if self.numeric_stats:
            d["numeric_stats"] = {k: _round_or_none(v) for k, v in self.numeric_stats.items()}
        return d


def _round_or_none(v: float) -> float | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return round(float(v), 6)


def _is_missing(value: Any) -> bool:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    return isinstance(value, str) and value.strip().lower() in _NULL_MARKERS


@dataclass
class ProfileReport:
    rows: int
    columns: int
    memory_mb: float
    duplicate_rows: int
    duplicate_pct: float
    total_missing: int
    missing_pct: float
    quality_score: float
    score_components: dict[str, float]
    column_profiles: list[ColumnProfile]
    findings: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows": self.rows,
            "column_count": self.columns,
            "memory_mb": round(self.memory_mb, 2),
            "duplicate_rows": self.duplicate_rows,
            "duplicate_pct": round(self.duplicate_pct, 2),
            "total_missing": self.total_missing,
            "missing_pct": round(self.missing_pct, 2),
            "quality_score": round(self.quality_score, 1),
            "score_components": {k: round(v, 1) for k, v in self.score_components.items()},
            "columns": [c.to_dict() for c in self.column_profiles],
            "findings": self.findings,
        }

    def column(self, name: str) -> ColumnProfile | None:
        for c in self.column_profiles:
            if c.name == name:
                return c
        return None

    def profile_frame(self) -> pd.DataFrame:
        """Per-column summary as a dataframe (for dashboard tables)."""
        records = [
            {
                "column": c.name,
                "kind": c.inferred_kind,
                "missing": c.missing,
                "missing %": round(c.missing_pct, 1),
                "unique": c.unique,
                "notes": "; ".join(_column_notes(c)),
            }
            for c in self.column_profiles
        ]
        return pd.DataFrame(records)


def _column_notes(c: ColumnProfile) -> list[str]:
    notes: list[str] = []
    if c.mixed_types:
        notes.append("mixed types: " + "/".join(c.mixed_types))
    if c.whitespace_padded:
        notes.append(f"{c.whitespace_padded} whitespace-padded")
    if c.null_marker_count:
        notes.append(f"{c.null_marker_count} null markers")
    if c.parseable_dates:
        notes.append(f"{c.parseable_dates} date-like values in text")
    if len(c.distinct_units) > 1:
        notes.append("mixed units: " + ", ".join(c.distinct_units))
    if c.case_variants:
        notes.append(f"{c.case_variants} case-variant labels")
    if c.suspicious_values:
        notes.append(f"{c.suspicious_values} suspicious placeholders")
    if c.outlier_candidates:
        notes.append(f"{c.outlier_candidates} outliers (IQR)")
    return notes


def profile_dataset(df: pd.DataFrame, *, max_rows_check: int | None = None) -> ProfileReport:
    """Compute a full read-only profile of a dataframe."""
    rows, cols = df.shape
    if max_rows_check is not None and rows > max_rows_check:
        raise LimitExceededError(f"profiling refused: {rows:,} rows")

    memory_mb = float(df.memory_usage(deep=True).sum()) / 1048576.0
    dup_rows = int(df.duplicated(keep=False).sum())
    dup_groups = int(df.duplicated().sum())

    total_missing = 0
    col_profiles: list[ColumnProfile] = []
    completeness_cells = rows * cols if cols else 1

    for col in df.columns:
        s = df[col]
        prof = _profile_column(col, s)
        total_missing += prof.missing
        col_profiles.append(prof)

    missing_pct = 100.0 * total_missing / completeness_cells if completeness_cells else 0.0
    duplicate_pct = 100.0 * dup_groups / rows if rows else 0.0

    findings = _findings(df, col_profiles, dup_groups)

    # Quality score: three transparent components in [0, 100].
    completeness = max(0.0, 100.0 - missing_pct * 5)  # 20% missing -> 0
    uniqueness = max(0.0, 100.0 - duplicate_pct * 5)  # 20% dupes -> 0
    consistency_cells = sum(
        c.mixed_types.__len__()
        + (1 if len(c.distinct_units) > 1 else 0)
        + (1 if c.case_variants else 0)
        + (1 if c.null_marker_count else 0)
        for c in col_profiles
    )
    consistency = max(0.0, 100.0 - 100.0 * consistency_cells / max(1, cols))
    score = (completeness + uniqueness + consistency) / 3.0

    return ProfileReport(
        rows=rows,
        columns=cols,
        memory_mb=memory_mb,
        duplicate_rows=dup_rows,
        duplicate_pct=duplicate_pct,
        total_missing=total_missing,
        missing_pct=missing_pct,
        quality_score=score,
        score_components={
            "completeness": completeness,
            "uniqueness": uniqueness,
            "consistency": consistency,
        },
        column_profiles=col_profiles,
        findings=findings,
    )


def _python_type_name(v: Any) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)) or pd.isna(v):
        return "missing"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        return "decimal"
    if isinstance(v, (pd.Timestamp,)):
        return "datetime"
    return "text"


def _profile_column(name: str, s: pd.Series) -> ColumnProfile:
    missing = int(s.isna().sum())
    marker_mask = pd.Series(False, index=s.index)
    if s.dtype == object or pd.api.types.is_string_dtype(s):
        text = s.astype("string").str.strip().str.lower()
        marker_mask = (text.isin(_NULL_MARKERS) & s.notna()).fillna(False)
        missing += int(marker_mask.sum())
    # "meaningful" values = neither NaN nor a null marker
    real = s[~marker_mask & s.notna()]
    kinds = pd.Series([_python_type_name(v) for v in real.head(200_000)], dtype=object)
    kind_counts = kinds.value_counts()
    # for all-text columns, classify by parseability (numeric strings vs prose)
    if len(real) and list(kind_counts.index) == ["text"]:
        sample = real.head(200_000).astype(str).str.strip()
        numeric_text = pd.to_numeric(sample.str.replace(",", "", regex=False), errors="coerce")
        int_like = (numeric_text.notna() & (numeric_text % 1 == 0)).fillna(False)
        dec_like = (numeric_text.notna() & ~int_like).fillna(False)
        n_text = int((~int_like & ~dec_like).sum())
        kind_counts = pd.Series(
            {
                k: v
                for k, v in {
                    "integer": int(int_like.sum()),
                    "decimal": int(dec_like.sum()),
                    "text": n_text,
                }.items()
                if v > 0
            }
        )
    all_kinds = sorted(kind_counts.index)
    inferred = all_kinds[0] if len(all_kinds) == 1 else ("mixed" if all_kinds else "empty")
    mixed = all_kinds if len(all_kinds) > 1 else []

    unique = int(real.nunique(dropna=True))
    top: list[tuple[str, int]] = []
    if unique > 0 and len(real):
        vc = real.astype(str).value_counts().head(5)
        top = [(str(k), int(v)) for k, v in vc.items()]

    numeric_stats = None
    outliers = 0
    num = pd.to_numeric(real, errors="coerce") if len(real) else None
    if num is not None and num.notna().sum() >= 5 and (num.notna().sum() / max(1, len(real))) > 0.5:
        desc = num.describe()
        q1, q3 = float(desc["25%"]), float(desc["75%"])
        iqr = q3 - q1
        if iqr > 0:
            outliers = int(((num < q1 - 1.5 * iqr) | (num > q3 + 1.5 * iqr)).sum())
        numeric_stats = {
            "min": float(desc["min"]),
            "q1": q1,
            "median": float(desc["50%"]),
            "mean": float(desc["mean"]),
            "q3": q3,
            "max": float(desc["max"]),
            "std": float(desc["std"]) if desc["std"] == desc["std"] else 0.0,
            "outliers_iqr": outliers,
        }

    parseable_dates = 0
    distinct_units: list[str] = []
    whitespace_padded = 0
    null_markers = 0
    suspicious = 0
    if len(real) and inferred in ("text", "mixed"):
        sample = real.astype(str)
        whitespace_padded = int((sample != sample.str.strip()).sum())
        null_markers = int(sample.str.strip().str.lower().isin(_NULL_MARKERS).sum())
        parseable_dates = int(sample.str.match(_DATEISH_RE).sum())
        units = set()
        for v in sample.head(5000):
            m = _UNIT_SUFFIX_RE.match(v)
            if m:
                units.add(m.group(2).lower())
        distinct_units = sorted(units)
        as_num = pd.to_numeric(sample.str.replace(",", "", regex=False), errors="coerce")
        suspicious = int(as_num.isin(_PLACEHOLDERS).sum())

    case_variants = 0
    if len(real) and 1 < unique <= 50:  # genuinely categorical-looking only
        vals = pd.Series(real.unique()).astype(str)
        lowered = vals.str.lower()
        case_variants = int(len(set(lowered)) < len(set(vals)))

    return ColumnProfile(
        name=str(name),
        pandas_dtype=str(s.dtype),
        inferred_kind=inferred if inferred != "mixed" else "text",
        missing=missing,
        missing_pct=100.0 * missing / len(s) if len(s) else 0.0,
        unique=unique,
        top_values=top,
        numeric_stats=numeric_stats,
        outlier_candidates=outliers,
        mixed_types=mixed,
        whitespace_padded=whitespace_padded,
        null_marker_count=null_markers,
        parseable_dates=parseable_dates,
        distinct_units=distinct_units,
        case_variants=case_variants,
        suspicious_values=suspicious,
    )


def _findings(
    df: pd.DataFrame, profiles: list[ColumnProfile], dup_groups: int
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if dup_groups:
        findings.append(
            {
                "severity": "high",
                "area": "duplicates",
                "message": f"{dup_groups:,} duplicate row(s) detected (exact matches).",
            }
        )
    for c in profiles:
        if c.missing_pct >= 50 and c.missing > 0:
            findings.append(
                {
                    "severity": "medium",
                    "area": "missing",
                    "message": f"column {c.name!r} is {c.missing_pct:.0f}% missing.",
                }
            )
        if c.mixed_types and "text" in c.mixed_types and (
            {"integer", "decimal", "boolean"} & set(c.mixed_types)
        ):
            findings.append(
                {
                    "severity": "medium",
                    "area": "types",
                    "message": f"column {c.name!r} mixes text and numeric/boolean values.",
                }
            )
        if len(c.distinct_units) > 1:
            findings.append(
                {
                    "severity": "high",
                    "area": "units",
                    "message": f"column {c.name!r} mixes units: {', '.join(c.distinct_units)}.",
                }
            )
        if c.case_variants:
            findings.append(
                {
                    "severity": "low",
                    "area": "labels",
                    "message": f"column {c.name!r} has {c.case_variants} case-variant label(s).",
                }
            )
        if c.null_marker_count:
            findings.append(
                {
                    "severity": "low",
                    "area": "missing",
                    "message": f"column {c.name!r} uses text null markers "
                    f"({c.null_marker_count} value(s) like 'N/A' or 'unknown').",
                }
            )
        if c.parseable_dates and c.inferred_kind == "text":
            findings.append(
                {
                    "severity": "medium",
                    "area": "dates",
                    "message": f"column {c.name!r} stores date-like values as text.",
                }
            )
        if c.whitespace_padded:
            findings.append(
                {
                    "severity": "low",
                    "area": "strings",
                    "message": f"column {c.name!r} has {c.whitespace_padded} "
                    "whitespace-padded value(s).",
                }
            )
        if c.outlier_candidates:
            findings.append(
                {
                    "severity": "low",
                    "area": "outliers",
                    "message": f"column {c.name!r} has {c.outlier_candidates} "
                    "statistical outlier candidate(s) (IQR rule).",
                }
            )
        if c.suspicious_values:
            findings.append(
                {
                    "severity": "low",
                    "area": "suspicious",
                    "message": f"column {c.name!r} contains {c.suspicious_values} "
                    "placeholder-like number(s) (e.g. -1, 999, 9999).",
                }
            )
    for col in df.columns:
        if df[col].nunique(dropna=True) <= 1 and len(df) > 1 and not df[col].isna().all():
            findings.append(
                {
                    "severity": "low",
                    "area": "schema",
                    "message": f"column {str(col)!r} is constant across all rows.",
                }
            )
    return findings
