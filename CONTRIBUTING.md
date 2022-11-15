# Contributing

Thanks for considering a contribution! This project values **correctness and
auditability over cleverness**: every change to cleaning behavior must be
tested and must not break the safety guarantees in `docs/safety.md`.

## Development setup

```bash
git clone https://github.com/sanjaymouraly/python-data-cleaning-toolkit.git
cd python-data-cleaning-toolkit
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -e ".[app,dev]"
pre-commit-free linting: ruff check .
```

## Before opening a PR

```bash
ruff check .            # zero findings
pytest                  # full suite passes (unit + integration + e2e)
pytest -m slow -s       # if you touched engine internals: performance still sane
```

## Ground rules

- **Tests are mandatory** for behavior changes. New rule options need at least:
  a happy path, a violation/error path, and an idempotence check.
- **Never weaken a safety test** to make a change pass. If a guarantee in
  `docs/safety.md` changes, that's a design discussion first.
- **No new dependencies** without justification in the PR description
  (the core has exactly: pandas, openpyxl, pydantic, pyyaml).
- **Type hints and docstrings** on public functions; ruff enforces style.
- **Docs stay honest**: update `README.md` / `docs/*.md` when behavior,
  commands, or performance numbers change. No fabricated benchmarks.
- Config schema changes must keep `extra="forbid"` and update
  `docs/configuration.md` + the bundled profiles.

## Adding a cleaning rule

1. Add a config class in `src/data_cleaning_toolkit/config/schema.py`
   (discriminated union member, `extra="forbid"`, validate everything).
2. Implement `CleaningRule.apply` in `src/data_cleaning_toolkit/cleaners/`
   and register it with `@register`.
3. Record *every* effect through the `AuditCollector`.
4. Add unit tests (behavior + idempotence + preview/apply consistency).
5. Document the rule in `docs/configuration.md`.

## Commit & PR style

- Conventional-ish prefixes: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`.
- One logical change per PR; include the reasoning in the description.
- Screenshots for dashboard changes (real ones — `scripts/capture_screenshots.py`).

## Reporting bugs

Open an issue with: minimal input data (fictional!), the config used, the
command/calls, expected vs actual behavior, and the full error output.
For security issues, see SECURITY.md.
