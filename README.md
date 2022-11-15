# Advanced CSV & Excel Data Cleaner

A safety-first data cleaning toolkit for CSV and Excel files. It provides a reusable Python library, a `cleaner` CLI, and a Streamlit dashboard that all run the same rule engine. Every change is previewed and recorded in an audit trail.

## Features

- Profile datasets before cleaning: missing values, duplicates, types, mixed units, case variants, outliers, and date-like text.
- 13 rule types: missing values, duplicates, type conversion, date normalization, string standardization, numeric validation, unit normalization, and custom validation.
- Preview by default; apply only with explicit approval.
- Per-cell audit log, removed-row provenance, and flagged values.
- Export CSV, XLSX, and JSON with atomic writes, formula-injection protection, and overwrite protection.
- YAML/JSON cleaning configs with validation and snapshots.
- Five example configs and deterministic sample datasets.
- Fully offline: no accounts, API keys, or telemetry.

## Requirements

- Python 3.11+
- pandas, openpyxl, pydantic, PyYAML
- Streamlit and Plotly for the dashboard

## Clone and install

```bash
git clone https://github.com/sanjaymouraly/python-data-cleaning-toolkit.git
cd python-data-cleaning-toolkit
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[app]"
```

Linux/macOS:

```bash
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[app]"
```

For development and tests use `pip install -e ".[app,dev]"`.

## Quick start

```bash
# Profile a sample dataset
cleaner profile -i examples/data/sales_transactions.csv -c configs/sales_report.yaml

# See exactly what would change
cleaner preview -i examples/data/sales_transactions.csv -c configs/sales_report.yaml

# Apply the plan
cleaner clean -i examples/data/sales_transactions.csv -c configs/sales_report.yaml --yes

# Validate
cleaner validate -i examples/data/customer_contacts.csv -c configs/customer_contacts.yaml

# Batch clean a folder
cleaner batch -i path/to/csvs -c configs/sales_report.yaml -o cleaned --yes
```

The `clean` command prints the run folder. Export its report with:

```bash
cleaner report --run-dir cleaned/run-<timestamp>
```

## Dashboard

```bash
streamlit run app/app.py
```

The dashboard supports upload, profiling, preview, apply, audit review, and downloads.

## Configuration

List or create a config:

```bash
cleaner config --list-profiles
cleaner config --init my_config.yaml --profile financial_transactions
cleaner config --validate my_config.yaml
```

Bundled profiles: `general_business`, `financial_transactions`, `sales_inventory`, `customer_contacts`, `workforce_report`. Example configs are in `configs/`.

## Safety

- Source files are opened read-only and never modified.
- Cleaning requires a validated config and an explicit apply step.
- Ambiguous dates and unknown units are flagged, not guessed.
- Exports refuse to overwrite existing files unless explicitly allowed.
- CSV values that look like formulas are escaped.

## Tests

```bash
python -m pytest -q
python -m ruff check .
```

Slow performance checks: `python -m pytest -m slow -s`.

## License

MIT © 2022 [Sanjay Mouraly](https://github.com/sanjaymouraly)
