# Configuration Reference

Cleaning configurations are YAML or JSON files validated by Pydantic **before**
any data is read or modified. Unknown keys are rejected (typo-safe), rule IDs
must be unique, and formats/patterns/units are checked at load time.

    version: "1.0"        # required, pinned - forward-incompatible by design
    name: my-plan
    description: optional free text
    import_options: { ... }
    source: { ... }
    rules: [ ... ]        # list of rule objects, executed in order
    export: { ... }
    limits: { ... }
    audit: { ... }

## Top-level sections

### `import_options`

| Key | Type | Default | Notes |
|---|---|---|---|
| `delimiter` | `str` | `null` | CSV only; single character; `null` = auto-detect (`,` `;` `\t` `\|`) |
| `encoding` | `str` | `null` | CSV only; `null` = cascade `utf-8-sig → utf-8 → cp1252 → latin-1` |
| `header_row` | `int` | `0` | 0-based row containing column names |
| `columns` | `list[str]` | `null` | select/order columns (original names) |
| `rename` | `map[str,str]` | `{}` | rename original → new, applied after selection |

### `source`

Optional metadata for documentation: `filename`, `sheet`. The engine records
the real file name and SHA-256 in run manifests regardless.

### `export`

| Key | Type | Default | Notes |
|---|---|---|---|
| `fmt` | `csv\|xlsx\|json\|none` | `csv` | `none` = clean without exporting |
| `directory` | `str` | `cleaned` | created if missing |
| `filename_suffix` | `str` | `_cleaned` | appended to the dataset name |
| `delimiter` | `str` | `,` | CSV output |
| `encoding` | `str` | `utf-8` | CSV output |
| `include_index` | `bool` | `false` | write the dataframe index |
| `formula_injection_guard` | `bool` | `true` | prefix `=`/`+`/`@`/TAB text with `'` |
| `validate_output` | `bool` | `true` | reopen and verify the written file |

Existing files are **never** overwritten without explicit consent
(`--force-overwrite` in the CLI, `allow_overwrite=True` in the library).

### `limits`

| Key | Type | Default | Notes |
|---|---|---|---|
| `max_file_mb` | `float` | `200` | refuses larger inputs instead of truncating |
| `max_rows` | `int` | `1_000_000` | checked after load |
| `max_columns` | `int` | `500` | checked after load |
| `chunk_rows` | `int` | `0` | reserved; global rules require whole-file loads |

### `audit`

| Key | Type | Default | Notes |
|---|---|---|---|
| `max_change_records` | `int` | `50000` | per-row detail cap; totals stay exact |
| `key_columns` | `list[str]` | `[]` | captured as provenance for removed rows |
| `redact_columns` | `list[str]` | `[]` | values replaced with `[REDACTED]` in all logs |
| `write_excel_workbook` | `bool` | `false` | also write `audit/audit_workbook.xlsx` |

## Rule types

Every rule supports `id` (unique; auto-generated `type-NN` when omitted),
`enabled` (default `true`) and `description`.

### `missing_values`

| Key | Values |
|---|---|
| `columns` | list or `null` (= all columns) |
| `null_markers` | default `["", "n/a", "na", "null", "none", "nan", "unknown", "-", "?"]` |
| `case_insensitive_markers` | default `true` |
| `strategy` | `retain` · `remove_rows` · `remove_columns` · `fill_constant` · `mean` · `median` · `mode` · `ffill` · `bfill` |
| `fill_value` | required for `fill_constant`, forbidden otherwise |
| `scope` | `any` / `all` — which columns must be missing for `remove_rows` |

Notes: zeros are never treated as missing. `mean`/`median` refuse non-numeric
columns (with a warning) instead of imputing garbage; `mode` works on any
dtype. `ffill`/`bfill` leave unfillable edge gaps as `<NA>` and warn.

### `duplicates`

| Key | Values |
|---|---|
| `columns` | key columns; `null` = whole-row comparison |
| `keep` | `first` · `last` · `none` (remove all copies) |
| `flag_only` | `true` = report groups, delete nothing |
| `ignore_case` / `strip_whitespace` | normalize keys before comparison |

### `type_conversion`

| Key | Values |
|---|---|
| `column` | target column |
| `target` | `integer` · `decimal` · `boolean` · `text` · `category` |
| `thousands_sep` / `decimal_sep` | single characters, stripped before parsing |
| `on_error` | `flag` (default) · `set_null` · `remove_row` · `fail` |
| `keep_leading_zeros` | `true` = values like `00123` stay text + flag |
| `true_values` / `false_values` | boolean vocabularies (defaults: `y/yes/true/t/1`, `n/no/false/f/0`) |

Integer conversion rejects fractional values and >64-bit magnitudes rather
than losing precision. Invalid cells under `flag` keep their original text so
the evidence stays visible in the output.

### `date_normalize`

| Key | Values |
|---|---|
| `columns` | required list |
| `input_formats` | explicit strptime formats, tried in order |
| `dayfirst` | `null` (never guess: flag ambiguous) · `true` · `false` |
| `output_format` | strftime, default `%Y-%m-%d`; validated at load |
| `output_type` | `text` (default) or `date` (datetime cells) |
| `on_error` | `flag` · `set_null` · `remove_row` · `fail` |
| `allow_fallback_parsing` | opt-in flexible parser (off by default) |
| `target_tz` | IANA zone; aware inputs are converted, naive inputs localized |

Parsing order: explicit formats → strict ISO 8601 → unambiguous numeric
(`25/03/2026`) with `dayfirst` for the rest → unambiguous month-name formats.
Ambiguous numeric dates without `dayfirst` are flagged and left untouched.
Invalid dates (`2026-02-30`, `31/04/2026`) are flagged per `on_error`.
Two-digit years: `00–99` → `2000–2099`.

### `string_standardize`

| Key | Values |
|---|---|
| `columns` | explicit list, **or** |
| `apply_to_all_text` | `true` = every object-dtype column (explicit opt-in) |
| `exclude_columns` | skipped columns |
| `trim_whitespace` / `collapse_internal_whitespace` | whitespace handling |
| `case` | `none` · `lower` · `upper` · `title` · `sentence` |
| `unicode_normalize` | `none` · `NFC` · `NFD` · `NFKC` · `NFKD` |
| `value_mappings` | `{wrong: right}` exact map |
| `mapping_ignore_case` | match keys case-insensitively |

### `numeric_validate`

| Key | Values |
|---|---|
| `columns` | required list |
| `min` / `max` | inclusive bounds |
| `allow_negative` | default `true` |
| `allow_decimal` | default `true` |
| `thousands_sep` / `decimal_sep` | separators for text values |
| `outlier_method` | `none` (default) · `iqr` · `zscore` |
| `outlier_action` | `flag` (default) · `remove_rows` (explicit opt-in) |
| `iqr_k` / `zscore_threshold` | `1.5` / `3.0` defaults |
| `on_invalid` | `flag` · `remove_rows` |

### `unit_normalize`

| Key | Values |
|---|---|
| `value_column` | numeric values |
| `unit_column` **or** `source_unit` | exactly one |
| `category` | `mass` · `length` · `temperature` |
| `target_unit` | must belong to the category (validated at load) |
| `rounding_digits` | optional rounding after conversion |

Supported units — mass: `mg g kg t lb oz`; length: `mm cm m km in ft yd mi`;
temperature: `c f k`. Unknown/missing units are flagged, never converted.

### Custom validation rules

All support `on_violation`: `flag` (default) · `remove_rows` · `set_null`.

| Type | Keys |
|---|---|
| `required_column` | `column` |
| `allowed_values` | `column`, `values`, `ignore_case` |
| `regex_match` | `column`, `pattern` (compiled at load), `inverse` |
| `unique_key` | `columns` (composite allowed) |
| `cross_column` | `left`, `operator` (`== != > >= < <=`), `right_column` or `right_value`, optional `factor_column`, `numeric` |
| `conditional_required` | `column`, `when_column`, `when_operator` (`==`/`!=`), `when_value` |

## Validation errors you may see

- `invalid cleaning configuration: - rules.0.keep: ...` — a rule key has a bad value
- `duplicate rule id: 'x'` — two rules share an id
- `output_format contains an unsupported strftime directive` — bad date format
- `target_unit 'stones' is not valid for category 'mass'` — unit typo
- `extra inputs are not permitted` — unknown key (check spelling against this document)
