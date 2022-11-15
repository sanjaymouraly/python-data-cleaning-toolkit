# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 1.0.x | ✅ |

## Reporting a vulnerability

Please do **not** open a public issue for exploitable behavior. Use GitHub's
"Report a vulnerability" (Security → Advisories) or contact the maintainers
privately. Include a minimal reproduction and the affected version. You can
expect an initial response within 14 days.

## Security design notes

This tool is built to process **untrusted files** with these invariants:

- **No code execution from data.** Cleaning configurations are parsed with
  `yaml.safe_load` and validated with Pydantic (`extra="forbid"`); rule
  patterns are compiled regexes; units come from fixed lookup tables. There
  is no `eval`/`exec`/`pickle` in the codebase. Excel formulas are never
  evaluated (cached values only, with an explicit per-file warning).
- **CSV/formula injection mitigation.** Exported text starting with `=`, `+`,
  `@`, TAB or CR is prefixed with `'` so spreadsheet applications treat it as
  text (counts reported per export). This follows the OWASP CSV Injection
  guidance; consumers re-importing the output should keep the guard enabled.
- **Path safety.** Output filenames are derived from sanitized dataset names;
  path separators and control characters are stripped. The tool never writes
  outside the directories you give it, and never overwrites without explicit
  consent.
- **Resource limits.** Configurable file-size, row and column limits refuse
  pathological inputs instead of exhausting memory.
- **Data minimization in logs.** `audit.redact_columns` keeps sensitive values
  out of audit artifacts; the toolkit is fully offline and performs no
  telemetry or network calls.

## Known non-goals

- The toolkit does not encrypt outputs; clean the data on a trusted machine
  and handle the results under your normal data-protection procedures.
- Excel (.xlsx) parsing relies on openpyxl; keep dependencies updated
  (`pip install -U data-cleaning-toolkit`) to receive fixes for upstream
  parser advisories.
