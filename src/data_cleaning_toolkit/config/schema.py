"""Validated cleaning configuration (YAML/JSON -> Pydantic v2 models).

Design principles
-----------------
* ``extra="forbid"`` everywhere: unknown keys are rejected, never ignored.
* No arbitrary Python is ever executed: patterns are compiled ``re`` patterns,
  formats are validated ``strftime`` formats, units are lookup tables.
* Every rule has a unique ``id`` (auto-generated when absent).
* Validation happens *before* any data is touched.
"""

from __future__ import annotations

import re
from abc import ABC
from datetime import datetime
from typing import Annotated, Any, Literal

import pandas as pd
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from ..core.errors import ConfigError

# ---------------------------------------------------------------------------
# shared enums / constants
# ---------------------------------------------------------------------------

CASE_MODES = ("none", "lower", "upper", "title", "sentence")
UNICODE_MODES = ("none", "NFC", "NFD", "NFKC", "NFKD")
TYPE_ERROR_ACTIONS = ("flag", "set_null", "remove_row", "fail")
VIOLATION_ACTIONS = ("flag", "remove_rows", "set_null")
MISSING_STRATEGIES = (
    "retain",
    "remove_rows",
    "remove_columns",
    "fill_constant",
    "mean",
    "median",
    "mode",
    "ffill",
    "bfill",
)
DUPLICATE_KEEP = ("first", "last", "none")
OUTLIER_METHODS = ("none", "iqr", "zscore")
UNIT_CATEGORIES = {
    "mass": {
        "mg": 0.001,
        "g": 1.0,
        "kg": 1000.0,
        "t": 1_000_000.0,
        "lb": 453.59237,
        "oz": 28.349523125,
    },
    "length": {
        "mm": 0.001,
        "cm": 0.01,
        "m": 1.0,
        "km": 1000.0,
        "in": 0.0254,
        "ft": 0.3048,
        "yd": 0.9144,
        "mi": 1609.344,
    },
    "temperature": {"c", "f", "k"},
}
BOOLEAN_TRUE = {"y", "yes", "true", "t", "1"}
BOOLEAN_FALSE = {"n", "no", "false", "f", "0"}
CROSS_OPERATORS = ("==", "!=", ">", ">=", "<", "<=")
EXPORT_FORMATS = ("csv", "xlsx", "json", "none")


def _new_rule_id(rule_type: str, counter: list[int]) -> str:
    counter[0] += 1
    return f"{rule_type}-{counter[0]:02d}"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# ---------------------------------------------------------------------------
# sub-configs
# ---------------------------------------------------------------------------


class ExportConfig(_StrictModel):
    fmt: Literal["csv", "xlsx", "json", "none"] = "csv"
    directory: str = "cleaned"
    filename_suffix: str = "_cleaned"
    delimiter: str = ","
    encoding: str = "utf-8"
    include_index: bool = False
    formula_injection_guard: bool = True
    validate_output: bool = True

    @field_validator("delimiter")
    @classmethod
    def _one_char(cls, v: str) -> str:
        if len(v) != 1:
            raise ValueError("delimiter must be a single character")
        return v

    @field_validator("encoding")
    @classmethod
    def _known_encoding(cls, v: str) -> str:
        try:
            "x".encode(v)
        except LookupError as exc:
            raise ValueError(f"unknown encoding: {v}") from exc
        return v


class LimitsConfig(_StrictModel):
    max_file_mb: float = 200.0
    max_rows: int = 1_000_000
    max_columns: int = 500
    chunk_rows: int = 0  # 0 = never chunk (load whole file)

    @field_validator("max_file_mb", "max_rows", "max_columns", "chunk_rows")
    @classmethod
    def _positive(cls, v: float) -> float:
        if v < 0:
            raise ValueError("limits must be >= 0")
        return v


class AuditConfig(_StrictModel):
    max_change_records: int = Field(default=50_000, ge=0)
    key_columns: list[str] = Field(default_factory=list)
    redact_columns: list[str] = Field(default_factory=list)
    write_excel_workbook: bool = False


# ---------------------------------------------------------------------------
# rule configs (discriminated union on "type")
# ---------------------------------------------------------------------------


class _RuleBase(_StrictModel, ABC):
    id: str | None = None
    enabled: bool = True
    description: str = ""

    def resolve_id(self, fallback: str) -> str:
        return self.id or fallback


class MissingValuesRuleConfig(_RuleBase):
    type: Literal["missing_values"]
    columns: list[str] | None = None  # None = all columns
    null_markers: list[str] = Field(
        default_factory=lambda: ["", "n/a", "na", "null", "none", "nan", "unknown", "-", "?"],
    )
    case_insensitive_markers: bool = True
    strategy: Literal[
        "retain",
        "remove_rows",
        "remove_columns",
        "fill_constant",
        "mean",
        "median",
        "mode",
        "ffill",
        "bfill",
    ] = "retain"
    fill_value: str | int | float | bool | None = None
    scope: Literal["any", "all"] = "any"

    @model_validator(mode="after")
    def _check(self) -> MissingValuesRuleConfig:
        if self.strategy == "fill_constant" and self.fill_value is None:
            raise ValueError("strategy 'fill_constant' requires 'fill_value'")
        if self.strategy in {"mean", "median", "mode"} and self.fill_value is not None:
            raise ValueError(f"strategy '{self.strategy}' must not set 'fill_value'")
        return self


class DuplicatesRuleConfig(_RuleBase):
    type: Literal["duplicates"]
    columns: list[str] | None = None  # None = full-row comparison
    keep: Literal["first", "last", "none"] = "first"
    flag_only: bool = False
    ignore_case: bool = False
    strip_whitespace: bool = False


class TypeConversionRuleConfig(_RuleBase):
    type: Literal["type_conversion"]
    column: str
    target: Literal["integer", "decimal", "boolean", "text", "category"]
    thousands_sep: str | None = None
    decimal_sep: str | None = None
    on_error: Literal["flag", "set_null", "remove_row", "fail"] = "flag"
    keep_leading_zeros: bool = False
    true_values: list[str] = Field(default_factory=lambda: sorted(BOOLEAN_TRUE))
    false_values: list[str] = Field(default_factory=lambda: sorted(BOOLEAN_FALSE))

    @field_validator("thousands_sep", "decimal_sep")
    @classmethod
    def _sep(cls, v: str | None) -> str | None:
        if v is not None and len(v) != 1:
            raise ValueError("separators must be single characters")
        return v


class DateNormalizeRuleConfig(_RuleBase):
    type: Literal["date_normalize"]
    columns: list[str]
    input_formats: list[str] | None = None  # explicit strptime formats, tried in order
    dayfirst: bool | None = None  # None = never guess ambiguous d/m vs m/d
    output_format: str = "%Y-%m-%d"
    output_type: Literal["text", "date"] = "text"
    on_error: Literal["flag", "set_null", "remove_row", "fail"] = "flag"
    allow_fallback_parsing: bool = False  # pandas flexible parser (non-strict)
    target_tz: str | None = None

    @field_validator("output_format")
    @classmethod
    def _valid_strftime(cls, v: str) -> str:
        try:
            datetime(2026, 1, 31, 14, 30, 45).strftime(v)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid strftime format: {v!r}") from exc
        if v.strip() == "":
            raise ValueError("output_format must not be blank")
        # some platforms silently pass unknown %directives through: reject them
        import re as _re

        if _re.search(r"%(?![aAbBcdfGHIjmMpSuvUwWxXyYzZfg%])", v):
            raise ValueError(
                f"output_format contains an unsupported strftime directive: {v!r}"
            )
        return v


class StringStandardizeRuleConfig(_RuleBase):
    type: Literal["string_standardize"]
    columns: list[str] | None = None
    apply_to_all_text: bool = False  # explicit opt-in for whole-dataset text sweep
    exclude_columns: list[str] = Field(default_factory=list)
    trim_whitespace: bool = True
    collapse_internal_whitespace: bool = False
    case: Literal["none", "lower", "upper", "title", "sentence"] = "none"
    unicode_normalize: Literal["none", "NFC", "NFD", "NFKC", "NFKD"] = "none"
    value_mappings: dict[str, str] = Field(default_factory=dict)
    mapping_ignore_case: bool = False

    @model_validator(mode="after")
    def _check(self) -> StringStandardizeRuleConfig:
        if self.columns is None and not self.apply_to_all_text:
            raise ValueError(
                "string_standardize requires explicit 'columns' "
                "(or apply_to_all_text: true for a whole-dataset text sweep)"
            )
        if self.columns is not None and self.apply_to_all_text:
            raise ValueError("use either 'columns' or 'apply_to_all_text', not both")
        return self


class NumericValidateRuleConfig(_RuleBase):
    type: Literal["numeric_validate"]
    columns: list[str]
    min: float | None = None
    max: float | None = None
    allow_negative: bool = True
    allow_decimal: bool = True
    thousands_sep: str | None = None
    decimal_sep: str | None = None
    outlier_method: Literal["none", "iqr", "zscore"] = "none"
    outlier_action: Literal["flag", "remove_rows"] = "flag"
    iqr_k: float = 1.5
    zscore_threshold: float = 3.0
    on_invalid: Literal["flag", "remove_rows"] = "flag"

    @model_validator(mode="after")
    def _check(self) -> NumericValidateRuleConfig:
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min must be <= max")
        if self.iqr_k <= 0 or self.zscore_threshold <= 0:
            raise ValueError("iqr_k and zscore_threshold must be positive")
        return self


class UnitNormalizeRuleConfig(_RuleBase):
    type: Literal["unit_normalize"]
    value_column: str
    unit_column: str | None = None
    source_unit: str | None = None
    category: Literal["mass", "length", "temperature"]
    target_unit: str
    rounding_digits: int | None = None

    @model_validator(mode="after")
    def _check(self) -> UnitNormalizeRuleConfig:
        if (self.unit_column is None) == (self.source_unit is None):
            raise ValueError("provide exactly one of 'unit_column' or 'source_unit'")
        table = UNIT_CATEGORIES[self.category]
        allowed = set(table) if isinstance(table, dict) else table
        tu = self.target_unit.lower()
        if tu not in allowed:
            raise ValueError(
                f"target_unit {self.target_unit!r} is not valid for category "
                f"{self.category!r}; allowed: {sorted(allowed)}"
            )
        if self.source_unit is not None and self.source_unit.lower() not in allowed:
            raise ValueError(
                f"source_unit {self.source_unit!r} is not valid for category "
                f"{self.category!r}; allowed: {sorted(allowed)}"
            )
        return self


class _CustomRuleBase(_RuleBase):
    on_violation: Literal["flag", "remove_rows", "set_null"] = "flag"


class RequiredColumnRuleConfig(_CustomRuleBase):
    type: Literal["required_column"]
    column: str


class AllowedValuesRuleConfig(_CustomRuleBase):
    type: Literal["allowed_values"]
    column: str
    values: list[str | int | float]
    ignore_case: bool = False


class RegexMatchRuleConfig(_CustomRuleBase):
    type: Literal["regex_match"]
    column: str
    pattern: str
    inverse: bool = False

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, v: str) -> str:
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError(f"invalid regex: {exc}") from exc
        return v


class UniqueKeyRuleConfig(_CustomRuleBase):
    type: Literal["unique_key"]
    columns: list[str] = Field(min_length=1)


class CrossColumnRuleConfig(_CustomRuleBase):
    type: Literal["cross_column"]
    left: str
    operator: Literal["==", "!=", ">", ">=", "<", "<="]
    right_column: str | None = None
    right_value: float | str | None = None
    factor_column: str | None = None  # compare left vs right * factor_column
    numeric: bool = True

    @model_validator(mode="after")
    def _check(self) -> CrossColumnRuleConfig:
        if (self.right_column is None) == (self.right_value is None):
            raise ValueError("provide exactly one of 'right_column' or 'right_value'")
        if self.factor_column is not None and not self.numeric:
            raise ValueError("factor_column requires numeric: true")
        return self


class ConditionalRequiredRuleConfig(_CustomRuleBase):
    type: Literal["conditional_required"]
    column: str
    when_column: str
    when_operator: Literal["==", "!="]
    when_value: str | int | float


RuleConfig = Annotated[
    MissingValuesRuleConfig
    | DuplicatesRuleConfig
    | TypeConversionRuleConfig
    | DateNormalizeRuleConfig
    | StringStandardizeRuleConfig
    | NumericValidateRuleConfig
    | UnitNormalizeRuleConfig
    | RequiredColumnRuleConfig
    | AllowedValuesRuleConfig
    | RegexMatchRuleConfig
    | UniqueKeyRuleConfig
    | CrossColumnRuleConfig
    | ConditionalRequiredRuleConfig,
    Field(discriminator="type"),
]

RULE_TYPE_NAMES = frozenset(
    {
        "missing_values",
        "duplicates",
        "type_conversion",
        "date_normalize",
        "string_standardize",
        "numeric_validate",
        "unit_normalize",
        "required_column",
        "allowed_values",
        "regex_match",
        "unique_key",
        "cross_column",
        "conditional_required",
    }
)


# ---------------------------------------------------------------------------
# top-level config
# ---------------------------------------------------------------------------


class ImportOptionsConfig(_StrictModel):
    delimiter: str | None = None  # None = auto-detect (CSV)
    encoding: str | None = None  # None = auto-detect cascade
    header_row: int = 0
    columns: list[str] | None = None  # optional column selection / ordering
    rename: dict[str, str] = Field(default_factory=dict)  # {original: new}


class SourceInfoConfig(_StrictModel):
    filename: str = ""
    sheet: str | None = None


class CleaningConfig(_StrictModel):
    version: Literal["1.0"] = "1.0"
    name: str = "unnamed-config"
    description: str = ""
    import_options: ImportOptionsConfig = Field(default_factory=ImportOptionsConfig)
    source: SourceInfoConfig = Field(default_factory=SourceInfoConfig)
    rules: list[RuleConfig] = Field(min_length=0, default_factory=list)
    export: ExportConfig = Field(default_factory=ExportConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)

    @field_validator("rules")
    @classmethod
    def _unique_rule_ids(
        cls, rules: list[Any]
    ) -> list[Any]:
        seen: set[str] = set()
        counter = [0]
        for rule in rules:
            rid = rule.resolve_id(_new_rule_id(rule.type, counter))
            if rid in seen:
                raise ValueError(f"duplicate rule id: {rid!r}")
            seen.add(rid)
        return rules

    def rule_ids(self) -> list[str]:
        counter = [0]
        return [r.resolve_id(_new_rule_id(r.type, counter)) for r in self.rules]

    def to_snapshot(self) -> dict[str, Any]:
        """Deterministic dict for the config snapshot written with each run."""
        data = self.model_dump(mode="json")
        return {"snapshot_version": "1.0", "config": data}


def _wrap_pydantic(exc: Exception) -> ConfigError:
    """Turn a pydantic ValidationError into a readable ConfigError."""
    lines: list[str] = []
    errors = getattr(exc, "errors", None)
    if callable(errors):
        for err in errors():
            loc = ".".join(str(p) for p in err.get("loc", ()))
            msg = err.get("msg", str(err))
            lines.append(f"  - {loc or '<config>'}: {msg}")
    detail = "\n".join(lines) if lines else str(exc)
    return ConfigError(f"invalid cleaning configuration:\n{detail}")


def parse_config(raw: dict[str, Any] | str) -> CleaningConfig:
    """Parse YAML/JSON text or a mapping into a validated config."""
    import json

    import yaml

    if isinstance(raw, CleaningConfig):
        return raw
    if isinstance(raw, (dict, list)):
        data: Any = raw
    elif isinstance(raw, (str, bytes)):
        text = raw.decode() if isinstance(raw, bytes) else raw
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ConfigError(f"invalid YAML: {exc}") from exc
        if data is None:
            raise ConfigError("configuration file is empty")
        if not isinstance(data, dict):
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                raise ConfigError(
                    "configuration must be a mapping of keys to values"
                ) from None
    else:
        raise ConfigError(f"unsupported configuration payload type: {type(raw)!r}")
    try:
        return CleaningConfig.model_validate(data)
    except Exception as exc:
        raise _wrap_pydantic(exc) from exc


def load_config_file(path: str) -> CleaningConfig:
    import pathlib

    p = pathlib.Path(path)
    if not p.exists():
        raise ConfigError(f"configuration file not found: {path}")
    if p.suffix.lower() not in {".yaml", ".yml", ".json"}:
        raise ConfigError(
            f"unsupported configuration format {p.suffix!r}; use .yaml, .yml or .json"
        )
    if p.stat().st_size > 2_000_000:
        raise ConfigError("configuration file is unreasonably large (>2 MB)")
    return parse_config(p.read_text(encoding="utf-8"))


def config_yaml(config: CleaningConfig) -> str:
    import yaml

    return yaml.safe_dump(
        config.model_dump(mode="json"), sort_keys=False, allow_unicode=True
    )


def empty_frame() -> pd.DataFrame:  # pragma: no cover - convenience for typing
    return pd.DataFrame()
