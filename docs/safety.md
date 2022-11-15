# Safety & Data Preservation

This document states exactly what the toolkit does and does not do to your
data, and how each guarantee is enforced and tested.

## Guarantees

### 1. Source files are never modified

Readers open files read-only. Cleaning happens on in-memory copies. Outputs
are written to **new** files. Tests: `test_source_never_modified_by_*`,
verified by byte-comparison of the input before/after full runs.

### 2. Preview cannot write anything

`cleaner preview`, `cleaner clean --dry-run`, `engine.preview()` and the
dashboard preview never construct an output path. The dry-run summary has the
same shape as an apply run so you can compare them (tests assert equality).

### 3. No silent changes

Every modification requires an explicit rule in a validated configuration.
Every modified cell is recorded (rule, row, column, before, after, reason).
Values the engine cannot interpret *safely* — ambiguous dates, unknown units,
unparseable numbers under the default `flag` policy, statistical outliers —
are **flagged and left untouched**.

### 4. Deletion is explicit and provenanced

Rows are removed only by `remove_rows` strategies, `keep: none`, or
`on_violation: remove_rows` — always a configured choice. Each removed row is
logged with its `audit.key_columns` values ("what exactly was deleted").

### 5. Common corruption traps are blocked

| Trap | Behavior |
|---|---|
| Leading-zero identifiers (`00123`) → numbers | `keep_leading_zeros: true` keeps them as text + flag; plain text conversion preserves them |
| `0` treated as missing | zeros are never null markers (tested) |
| `1,234.56` parsed as text garbage | configured separators parse correctly |
| `5.7` → integer silently truncated | rejected: precision-loss flag / policy |
| `03/04/2026` guessed | flagged unless `dayfirst` set |
| `2026-02-30` coerced to March 2 | flagged, never auto-corrected |
| `=SUM(A1)` in exported text | formula-injection guard prefixes `'` |
| Unknown unit `stones` | flagged, value untouched |
| Mean-fill on a text column | refused with a warning (no garbage imputation) |

### 6. Overwrite protection

Existing output files cause a `SafetyError` unless you explicitly allow
overwriting (`--force-overwrite` / `allow_overwrite=True`). The dashboard
apply flow writes to a fresh workspace run directory.

### 7. Atomic outputs

Exports write to a temp file in the destination directory and `os.replace`
into place; a failure deletes the temp file. A killed run cannot leave a
partially written "clean" file. (Tested by forcing a mid-write failure.)

### 8. No code execution from data or configs

- Configs: `yaml.safe_load` (the `!!python/object/apply` test payload is
  rejected) + Pydantic validation. Regexes are compiled, not executed; units
  come from fixed tables; no `eval`/`exec` anywhere in the codebase.
- Excel: formulas are never evaluated — cells are read as their last cached
  value, and the file is scanned so this is disclosed per import.
- Filenames are sanitized before reuse in output paths.

### 9. Sensitive values stay out of logs

`audit.redact_columns` replaces values with `[REDACTED]` in every audit
record (JSON, CSV, HTML, Excel workbook). Bundled PII-handling profiles
(`customer_contacts`) demonstrate the pattern. Credentials are never logged
because the toolkit never asks for them — it is fully offline.

### 10. Reproducibility without false claims

Re-running the same input + config yields identical cleaned data and change
records (tested). Run IDs and timestamps are kept separate from data
artifacts. The audit never claims reversibility: only `ChangeRecord`s retain
original values, and the logs say exactly that.

## Resource limits

- `limits.max_file_mb` — refuses large files up front (no partial reads).
- `limits.max_rows` / `max_columns` — refuses after load, before any rule runs.
- `audit.max_change_records` — bounds audit memory; counts remain exact.
- Whole-dataset rules (`requires_full_dataset`) are declared per rule so
  future chunked modes know which rules cannot be chunked safely.

## What this tool is not

- Not a workbook round-trip tool (formatting/charts/macros are not preserved).
- Not a fuzzy-matching deduplicator (exact/key-based only).
- Not a data *repair* oracle — it makes your explicit rules auditable; it does
  not decide truth for you.
