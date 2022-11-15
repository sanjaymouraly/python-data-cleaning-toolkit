#!/usr/bin/env python3
"""Generate reproducible example datasets with realistic data-quality problems.

Every dataset is fictional. A fixed random seed makes the output byte-stable
across runs and machines, so tests and documentation can rely on exact values.

Usage:
    python scripts/generate_samples.py                 # write to examples/data
    python scripts/generate_samples.py --out /tmp/data # custom directory
    python scripts/generate_samples.py --stats         # print planted-issue stats
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd

SEED = 42
MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
]


def _rng(seed: int = SEED) -> np.random.Generator:
    return np.random.default_rng(seed)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _fmt_iso(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def _fmt_ambiguous(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _fmt_text(d: date) -> str:
    return f"{MONTH_NAMES[d.month - 1]} {d.day}, {d.year}"


# ---------------------------------------------------------------------------
# sales transactions
# ---------------------------------------------------------------------------


def build_sales_clean(n: int = 500, seed: int = SEED) -> pd.DataFrame:
    rng = _rng(seed)
    products = {
        "Laptop Pro 14": ("Electronics", 1299.0, 1.6),
        "Wireless Mouse": ("Electronics", 24.5, 0.12),
        "Office Chair": ("Furniture", 189.99, 14.5),
        "Standing Desk": ("Furniture", 449.0, 28.0),
        "Notebook Pack": ("Stationery", 12.9, 0.8),
        "Mechanical Keyboard": ("Electronics", 89.0, 0.95),
        "Monitor 27in": ("Electronics", 279.0, 5.4),
        "Desk Lamp": ("Furniture", 35.5, 1.1),
    }
    regions = ["north", "south", "east", "west"]
    people = ["Amara Okafor", "Ben Liu", "Carla Mendes", "Dmitri Volkov", "Elena Rossi"]
    statuses = ["completed", "pending", "cancelled", " refunded"]
    base = date(2026, 1, 1)
    rows = []
    for i in range(n):
        product = rng.choice(list(products))
        category, price, weight_kg = products[product]
        qty = int(rng.integers(1, 6))
        d = base + timedelta(days=int(rng.integers(0, 240)))
        cust = f"CU{rng.integers(1000, 9999)}"
        unit_price = round(float(price) * float(rng.choice([1.0, 1.0, 1.0, 0.9, 1.1])), 2)
        rows.append(
            {
                "transaction_id": f"T{20000 + i}",
                "order_date": _fmt_iso(d),
                "customer_id": cust,
                "product": product,
                "category": category,
                "quantity": qty,
                "unit_price": unit_price,
                "total": round(qty * unit_price, 2),
                "currency": "USD",
                "region": rng.choice(regions),
                "shipping_weight": round(weight_kg * qty, 2),
                "weight_unit": "kg",
                "salesperson": rng.choice(people),
                "status": rng.choice(statuses, p=[0.7, 0.15, 0.1, 0.05]),
                "notes": "" if rng.random() < 0.6 else f"Order {20000 + i}",
            }
        )
    return pd.DataFrame(rows)


def inject_sales_issues(df: pd.DataFrame, seed: int = SEED) -> tuple[pd.DataFrame, dict]:
    rng = _rng(seed + 1)
    df = df.copy()
    stats: dict[str, int] = {}

    idx = np.arange(len(df))
    df["quantity"] = df["quantity"].astype(object)
    df["unit_price"] = df["unit_price"].astype(object)

    # missing region: 25 cells split between empty and 'N/A'
    miss = rng.choice(idx, size=25, replace=False)
    df.loc[miss[:12], "region"] = ""
    df.loc[miss[12:], "region"] = "N/A"
    stats["missing_region_cells"] = 25

    # missing quantity: 8 cells
    mq = rng.choice(idx, size=8, replace=False)
    df.loc[mq, "quantity"] = None
    stats["missing_quantity_cells"] = 8

    # mixed date formats: 25% day-first slash, 10% textual, 3 invalid, 4 empty
    md = rng.choice(idx, size=int(len(df) * 0.35), replace=False)
    slash_n = int(len(md) * 0.7)
    for i, pos in enumerate(md[:slash_n]):
        d = date.fromisoformat(df.at[pos, "order_date"])
        df.at[pos, "order_date"] = _fmt_ambiguous(d)
    for pos in md[slash_n : slash_n + int(len(md) * 0.3)]:
        d = date.fromisoformat(df.at[pos, "order_date"])
        df.at[pos, "order_date"] = _fmt_text(d)
    bad = rng.choice(idx, size=7, replace=False)
    df.loc[bad[:3], "order_date"] = "2026-02-30"   # invalid calendar date
    df.loc[bad[3:7], "order_date"] = ""            # empty
    stats["non_iso_or_invalid_dates"] = int(len(md)) + 7

    # quantity whitespace + negatives
    wq = rng.choice(idx, size=12, replace=False)
    df.loc[wq] = df.loc[wq].assign(
        quantity=df.loc[wq, "quantity"].map(lambda v: f"  {v} " if pd.notna(v) else v)
    )
    stats["whitespace_quantity_cells"] = 12
    nq = rng.choice(idx, size=6, replace=False)
    df.loc[nq, "quantity"] = -2
    stats["negative_quantities"] = 6

    # European-formatted unit_price with thousands separator
    up = rng.choice(idx, size=15, replace=False)
    df.loc[up] = df.loc[up].assign(
        unit_price=df.loc[up, "unit_price"].map(lambda v: f"{v:,.2f}")
    )
    stats["formatted_unit_price_cells"] = 15

    # category case chaos
    cats = rng.choice(idx, size=40, replace=False)
    df.loc[cats[:20], "category"] = df.loc[cats[:20], "category"].str.upper()
    df.loc[cats[20:], "category"] = df.loc[cats[20:], "category"].str.capitalize()
    stats["category_case_variants"] = 40

    # mixed weight units: convert some kg rows to grams
    wu = rng.choice(idx, size=30, replace=False)
    for pos in wu:
        w = pd.to_numeric(df.at[pos, "shipping_weight"], errors="coerce")
        if pd.notna(w):
            df.at[pos, "shipping_weight"] = round(float(w) * 1000, 1)
            df.at[pos, "weight_unit"] = "g"
    df.loc[wu[:3], "weight_unit"] = "unknown"
    stats["mixed_weight_units"] = 30

    # status typos
    st = rng.choice(idx, size=9, replace=False)
    df.loc[st[:5], "status"] = "compleated"
    df.loc[st[5:], "status"] = "canceld"
    stats["status_typos"] = 9

    # invalid customer ids
    cu = rng.choice(idx, size=6, replace=False)
    df.loc[cu, "customer_id"] = ["x1234", "cU77", "12AB", "CU_12", "cust01", "c123"]
    stats["invalid_customer_ids"] = 6

    # price outlier
    ol = rng.choice(idx, size=1, replace=False)
    df.loc[ol, "unit_price"] = 99999.0
    stats["price_outliers"] = 1

    # inconsistent totals (cross-column violations)
    tc = rng.choice(idx, size=10, replace=False)
    for pos in tc:
        q = pd.to_numeric(df.at[pos, "quantity"], errors="coerce")
        p = pd.to_numeric(df.at[pos, "unit_price"], errors="coerce")
        if pd.notna(q) and pd.notna(p):
            df.at[pos, "total"] = round(float(q) * float(p) * 1.5, 2)
    stats["total_mismatches"] = 10

    # unicode-padded names
    nm = rng.choice(idx, size=5, replace=False)
    df.loc[nm, "salesperson"] = df.loc[nm, "salesperson"].map(lambda s: s.replace(" ", "\u00a0"))
    stats["nbsp_names"] = 5

    # exact duplicates LAST, appended after all value edits so the copies stay exact
    dup_idx = rng.choice(len(df), size=20, replace=False)
    df = pd.concat([df, df.iloc[dup_idx]], ignore_index=True)
    stats["exact_duplicate_rows"] = 20

    return df.reset_index(drop=True), stats


# ---------------------------------------------------------------------------
# inventory workbook (2 sheets, includes a formula row)
# ---------------------------------------------------------------------------


def build_inventory_sheets(seed: int = SEED) -> dict[str, pd.DataFrame]:
    rng = _rng(seed + 2)
    items = ["Widget A", "Widget B", "Gear C", "Lever D", "Bolt E", "Panel F",
             "Cable G", "Sensor H", "Motor I", "Valve J"]
    stock = pd.DataFrame(
        {
            "sku": [f"SKU-{1000 + i}" for i in range(10)],
            "item_name": items,
            "qty_in_stock": [int(v) for v in rng.integers(0, 400, size=10)],
            "reorder_level": [25, 40, 30, 35, 20, 45, 25, 30, 50, 25],
            "unit_cost": [round(float(v), 2) for v in rng.uniform(2, 80, size=10)],
            "warehouse": ["W1", "W2", "W1", "W3", "W2", "W1", "W3", "W2", "W1", "W3"],
        }
    )
    suppliers = pd.DataFrame(
        {
            "supplier_code": ["SUP-01", "SUP-02", "SUP-03", "SUP-01", "SUP-04"],
            "supplier_name": ["Acme Parts", "Bravo Goods", "Cedar Supplies", "Acme Parts", "Delta Tools"],
            "lead_time_days": [7, 12, 5, 7, 20],
            "contact": ["a@acme.example", "b@bravo.example", "c@cedar.example",
                        "a@acme.example", "d@delta.example"],
        }
    )
    return {"stock": stock, "suppliers": suppliers}


def inject_inventory_issues(sheets: dict[str, pd.DataFrame], seed: int = SEED) -> tuple[dict, dict]:
    stock = sheets["stock"].copy()
    sup = sheets["suppliers"].copy()
    stats: dict[str, int] = {}
    stock["qty_in_stock"] = stock["qty_in_stock"].astype(object)
    stock["unit_cost"] = stock["unit_cost"].astype(object)

    stock.loc[2, "qty_in_stock"] = -15          # impossible negative stock
    stock.loc[5, "qty_in_stock"] = "12 "        # whitespace numeric
    stock.loc[7, "reorder_level"] = None        # missing value
    stock.loc[1, "unit_cost"] = "forty"         # text in numeric column
    stock.loc[4, "item_name"] = "  Panel F  "   # padded text
    stock.loc[9, "qty_in_stock"] = 99999        # outlier / placeholder-like
    stats["stock_issues"] = 6

    # duplicated supplier rows
    sup = pd.concat([sup, sup.iloc[[0, 2]]], ignore_index=True)
    sup.loc[5, "contact"] = "ACME@acme.example"  # case-variant duplicate email
    stats["duplicate_supplier_rows"] = 2
    return {"stock": stock, "suppliers": sup}, stats


def write_inventory_workbook(path: str, sheets: dict[str, pd.DataFrame]) -> None:
    """Write the inventory workbook; the stock sheet gets one formula row."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "stock"
    cols = list(sheets["stock"].columns)
    ws.append(cols)
    for _, row in sheets["stock"].iterrows():
        ws.append([None if pd.isna(v) else v for v in row])
    # row 12 (one past data): a formula computing stock value with a cached result
    r = ws.max_row + 2
    ws.cell(row=r, column=1, value="TOTAL VALUE")
    cell = ws.cell(row=r, column=5, value="=SUM(E2:E11)")
    cell._value = None
    ws2 = wb.create_sheet("suppliers")
    ws2.append(list(sheets["suppliers"].columns))
    for _, row in sheets["suppliers"].iterrows():
        ws2.append([None if pd.isna(v) else v for v in row])
    wb.save(path)


# ---------------------------------------------------------------------------
# freelancer income & expenses workbook
# ---------------------------------------------------------------------------


def build_freelancer_sheets(seed: int = SEED) -> dict[str, pd.DataFrame]:
    rng = _rng(seed + 4)
    clients = ["Northwind Ltd", "acme corp", "Globex", "Initech", "ACME Corp"]
    base = date(2026, 1, 5)
    income = pd.DataFrame(
        {
            "invoice_id": [f"INV-{300 + i}" for i in range(40)],
            "invoice_date": [_fmt_iso(base + timedelta(days=int(rng.integers(0, 250)))) for _ in range(40)],
            "client": [str(rng.choice(clients)) for _ in range(40)],
            "description": ["Consulting", "Design work", "Development", "Support retainer"] * 10,
            "amount": [round(float(v), 2) for v in rng.uniform(200, 4000, size=40)],
            "currency": ["EUR"] * 40,
            "paid": [str(rng.choice(["yes", "no", "YES", "Y"])) for _ in range(40)],
        }
    )
    expenses = pd.DataFrame(
        {
            "expense_id": [f"EXP-{70 + i}" for i in range(30)],
            "expense_date": [_fmt_iso(base + timedelta(days=int(rng.integers(0, 250)))) for _ in range(30)],
            "category": [str(rng.choice(["Software", "software", "SOFTWARE", "Travel", "Hardware", "Offuce"])) for _ in range(30)],
            "amount": [round(float(v), 2) for v in rng.uniform(5, 500, size=30)],
            "vat": [round(float(v) * 0.19, 2) for v in rng.uniform(5, 500, size=30)],
        }
    )
    return {"income": income, "expenses": expenses}


def inject_freelancer_issues(sheets: dict[str, pd.DataFrame], seed: int = SEED) -> tuple[dict, dict]:
    rng = _rng(seed + 5)
    income = sheets["income"].copy()
    expenses = sheets["expenses"].copy()
    stats: dict[str, int] = {}
    income["amount"] = income["amount"].astype(object)
    expenses["vat"] = expenses["vat"].astype(object)

    # mixed date formats in income
    md = rng.choice(len(income), size=12, replace=False)
    for pos in md[:6]:
        d = date.fromisoformat(income.at[pos, "invoice_date"])
        income.at[pos, "invoice_date"] = _fmt_ambiguous(d)
    for pos in md[6:]:
        d = date.fromisoformat(income.at[pos, "invoice_date"])
        income.at[pos, "invoice_date"] = _fmt_text(d)
    income.loc[md[6], "invoice_date"] = "31/04/2026"  # invalid: April has 30 days
    stats["mixed_income_dates"] = 12

    # euro-prefixed amounts
    ea = rng.choice(len(income), size=8, replace=False)
    income.loc[ea, "amount"] = income.loc[ea, "amount"].map(lambda v: f"â‚¬{v:,.2f}")
    stats["euro_amounts"] = 8

    # client case variants + paid markers
    income.loc[0:5, "client"] = income.loc[0:5, "client"].str.upper()
    income.loc[[6, 7, 8], "paid"] = ["maybe", "", "1"]
    stats["client_variants"] = 6
    stats["paid_markers_invalid"] = 3

    # duplicate invoice rows
    dup = income.iloc[[3, 11]]
    income = pd.concat([income, dup], ignore_index=True)
    stats["duplicate_invoices"] = 2

    # expenses: category typos, missing amounts, negative
    expenses.loc[2, "amount"] = None
    expenses.loc[9, "amount"] = -45.0
    expenses.loc[14, "vat"] = "19"
    stats["expense_issues"] = 3
    return {"income": income, "expenses": expenses}, stats


# ---------------------------------------------------------------------------
# customer contacts
# ---------------------------------------------------------------------------


def build_customers_clean(n: int = 220, seed: int = SEED) -> pd.DataFrame:
    rng = _rng(seed + 6)
    first = ["Ava", "Noah", "Mia", "Liam", "Zoe", "Ethan", "Isla", "Kai", "Nina", "Omar"]
    last = ["Bennett", "Kowalski", "Silva", "Tanaka", "Muller", "Okafor", "Novak", "Haddad"]
    countries = ["US", "GB", "DE", "FR", "IN", "NL"]
    tiers = ["free", "standard", "premium"]
    base = date(2025, 1, 1)
    rows = []
    for i in range(n):
        name = f"{rng.choice(first)} {rng.choice(last)}"
        handle = name.lower().replace(" ", ".")
        dom = rng.choice(["mail.example", "post.example", "inbox.example"])
        rows.append(
            {
                "customer_id": f"CU{1000 + i}",
                "full_name": name,
                "email": f"{handle}.{i}@{dom}",
                "phone": f"+1 555 {rng.integers(100, 999)} {rng.integers(1000, 9999)}",
                "country": str(rng.choice(countries)),
                "tier": str(rng.choice(tiers, p=[0.5, 0.3, 0.2])),
                "signup_date": _fmt_iso(base + timedelta(days=int(rng.integers(0, 500)))),
                "marketing_opt_in": bool(rng.random() < 0.4),
            }
        )
    return pd.DataFrame(rows)


def inject_customer_issues(df: pd.DataFrame, seed: int = SEED) -> tuple[pd.DataFrame, dict]:
    rng = _rng(seed + 7)
    df = df.copy()
    stats: dict[str, int] = {}
    idx = np.arange(len(df))

    # whitespace + case chaos on names
    nm = rng.choice(idx, size=25, replace=False)
    df.loc[nm] = df.loc[nm].assign(full_name=df.loc[nm, "full_name"].map(lambda s: f"  {s.upper()} "))
    stats["messy_names"] = 25

    # emails in mixed case + a few invalid
    em = rng.choice(idx, size=20, replace=False)
    df.loc[em, "email"] = df.loc[em, "email"].str.upper()
    bad = rng.choice(idx, size=5, replace=False)
    df.loc[bad, "email"] = ["not-an-email", "a@b", "missing-at.example", "x y@z.example", "@"]
    stats["invalid_emails"] = 5

    # country variants
    co = rng.choice(idx, size=18, replace=False)
    df.loc[co[:6], "country"] = "usa"
    df.loc[co[6:12], "country"] = "U.S."
    df.loc[co[12:], "country"] = " united kingdom "
    stats["country_variants"] = 18

    # duplicate rows on email (different ids, same person)
    dup_src = df.iloc[[4, 10, 20, 30]]
    dup = dup_src.copy()
    dup["customer_id"] = ["CU9", "CU9", "CU9", "CU9"]
    df = pd.concat([df, dup], ignore_index=True)
    stats["duplicate_emails"] = 4

    # tier typos
    ti = rng.choice(len(df), size=7, replace=False)
    df.loc[ti[:4], "tier"] = "Premium"
    df.loc[ti[4:], "tier"] = "STANDARD"
    stats["tier_case_variants"] = 7

    # mixed signup dates + broken phones
    sd = rng.choice(len(df), size=10, replace=False)
    for pos in sd[:5]:
        d = date.fromisoformat(df.at[pos, "signup_date"])
        df.at[pos, "signup_date"] = d.strftime("%m/%d/%Y")
    for pos in sd[5:]:
        d = date.fromisoformat(df.at[pos, "signup_date"])
        df.at[pos, "signup_date"] = _fmt_text(d)
    df.loc[sd[5], "signup_date"] = "2025-13-40"
    stats["mixed_signup_dates"] = 10
    ph = rng.choice(len(df), size=4, replace=False)
    df.loc[ph, "phone"] = ["555-CALL-ME", "none", "++4455", "12"]
    stats["invalid_phones"] = 4
    return df.reset_index(drop=True), stats


# ---------------------------------------------------------------------------
# workforce report
# ---------------------------------------------------------------------------


def build_workforce_clean(n: int = 180, seed: int = SEED) -> pd.DataFrame:
    rng = _rng(seed + 8)
    depts = ["Engineering", "Sales", "Finance", "Human Resources", "IT"]
    names = ["Ada Lovelace", "Grace Hopper", "Alan Turing", "Katherine Johnson",
             "Margaret Hamilton", "Edsger Dijkstra", "Barbara Liskov", "Donald Knuth"]
    base = date(2015, 1, 1)
    rows = []
    for i in range(n):
        salary = float(rng.integers(40, 160) * 1000)
        rows.append(
            {
                "employee_id": f"EMP-{1000 + i}",
                "employee_name": str(rng.choice(names)),
                "department": str(rng.choice(depts)),
                "seniority": str(rng.choice(["junior", "mid", "senior"], p=[0.3, 0.45, 0.25])),
                "manager_id": f"EMP-{int(rng.integers(1000, 1100))}",
                "hire_date": _fmt_iso(base + timedelta(days=int(rng.integers(0, 3800)))),
                "annual_salary": salary,
                "weekly_hours": int(rng.choice([35, 40, 40, 40, 20])),
            }
        )
    return pd.DataFrame(rows)


def inject_workforce_issues(df: pd.DataFrame, seed: int = SEED) -> tuple[pd.DataFrame, dict]:
    rng = _rng(seed + 9)
    df = df.copy()
    stats: dict[str, int] = {}
    idx = np.arange(len(df))
    df["annual_salary"] = df["annual_salary"].astype(object)

    # department variants
    dp = rng.choice(idx, size=30, replace=False)
    df.loc[dp[:10], "department"] = "engineering"
    df.loc[dp[10:20], "department"] = "HUMAN RESOURCES "
    df.loc[dp[20:], "department"] = "inf. tech"
    stats["department_variants"] = 30

    # salaries: thousands format, text, outlier, negative
    sa = rng.choice(idx, size=12, replace=False)
    df.loc[sa[:6], "annual_salary"] = df.loc[sa[:6], "annual_salary"].map(lambda v: f"{v:,.2f}")
    df.loc[sa[6:8], "annual_salary"] = "TBD"
    df.loc[sa[8], "annual_salary"] = 999000.0
    df.loc[sa[9], "annual_salary"] = -5000.0
    stats["salary_issues"] = 12

    # weekly hours violations
    wh = rng.choice(idx, size=6, replace=False)
    df.loc[wh[:3], "weekly_hours"] = 0
    df.loc[wh[3:], "weekly_hours"] = 120
    stats["weekly_hours_violations"] = 6

    # mixed hire dates
    hd = rng.choice(idx, size=15, replace=False)
    for i, pos in enumerate(hd):
        d = date.fromisoformat(df.at[pos, "hire_date"])
        df.at[pos, "hire_date"] = _fmt_ambiguous(d) if i % 2 else _fmt_text(d)
    df.loc[hd[0], "hire_date"] = "2020-02-31"
    stats["mixed_hire_dates"] = 15

    # duplicate employee ids + bad formats
    dup_src = df.iloc[[2, 5]]
    dup = dup_src.copy()
    df = pd.concat([df, dup], ignore_index=True)
    stats["duplicate_employee_rows"] = 2
    bf = rng.choice(len(df), size=4, replace=False)
    df.loc[bf, "employee_id"] = ["emp-1", "E12", "EMP_9", "12-EMP"]
    stats["bad_employee_ids"] = 4

    # seniors without manager
    sm = df.index[df["seniority"] == "senior"][:5]
    df.loc[sm, "manager_id"] = None
    stats["senior_missing_manager"] = 5

    # padded names
    nm = rng.choice(len(df), size=8, replace=False)
    df.loc[nm, "employee_name"] = df.loc[nm, "employee_name"].map(lambda s: f" {s}  ")
    stats["padded_names"] = 8
    return df.reset_index(drop=True), stats


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------


def build_all(output_dir: str) -> dict:
    """Generate every example dataset and the expected-issues manifest."""
    data_dir = output_dir
    ref_dir = os.path.join(data_dir, "reference")
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(ref_dir, exist_ok=True)
    # seed-derived content only: generation is byte-reproducible (no wall-clock data)
    manifest: dict = {"seed": SEED, "datasets": {}}

    # sales CSV
    clean = build_sales_clean()
    clean.to_csv(os.path.join(ref_dir, "sales_transactions_clean.csv"), index=False, lineterminator="\n")
    dirty, stats = inject_sales_issues(clean)
    dirty.to_csv(os.path.join(data_dir, "sales_transactions.csv"), index=False, lineterminator="\n")
    manifest["datasets"]["sales_transactions.csv"] = stats

    # inventory XLSX (2 sheets)
    sheets = build_inventory_sheets()
    sheets, stats = inject_inventory_issues(sheets)
    write_inventory_workbook(os.path.join(data_dir, "inventory.xlsx"), sheets)
    with pd.ExcelWriter(os.path.join(ref_dir, "inventory_reference.xlsx"), engine="openpyxl") as w:
        for name, df in sheets.items():
            df.to_excel(w, sheet_name=name, index=False)
    manifest["datasets"]["inventory.xlsx"] = stats

    # freelancer XLSX
    sheets = build_freelancer_sheets()
    sheets, stats = inject_freelancer_issues(sheets)
    with pd.ExcelWriter(os.path.join(data_dir, "freelancer_income_expenses.xlsx"), engine="openpyxl") as w:
        for name, df in sheets.items():
            df.to_excel(w, sheet_name=name, index=False)
    with pd.ExcelWriter(os.path.join(ref_dir, "freelancer_reference.xlsx"), engine="openpyxl") as w:
        for name, df in sheets.items():
            df.to_excel(w, sheet_name=name, index=False)
    manifest["datasets"]["freelancer_income_expenses.xlsx"] = stats

    # customers CSV
    clean = build_customers_clean()
    clean.to_csv(os.path.join(ref_dir, "customer_contacts_clean.csv"), index=False, lineterminator="\n")
    dirty, stats = inject_customer_issues(clean)
    dirty.to_csv(os.path.join(data_dir, "customer_contacts.csv"), index=False, lineterminator="\n")
    manifest["datasets"]["customer_contacts.csv"] = stats

    # workforce CSV
    clean = build_workforce_clean()
    clean.to_csv(os.path.join(ref_dir, "workforce_report_clean.csv"), index=False, lineterminator="\n")
    dirty, stats = inject_workforce_issues(clean)
    dirty.to_csv(os.path.join(data_dir, "workforce_report.csv"), index=False, lineterminator="\n")
    manifest["datasets"]["workforce_report.csv"] = stats

    with open(os.path.join(data_dir, "expected_issues.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(manifest, fh, indent=2)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=None, help="output directory (default: examples/data)")
    parser.add_argument("--stats", action="store_true", help="print the planted-issue manifest")
    args = parser.parse_args(argv)
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = args.out or os.path.join(repo_root, "examples", "data")
    manifest = build_all(out)
    if True:  # always print the planted-issue manifest
        for name, stats in manifest["datasets"].items():
            print(f"{name}:")
            for k, v in stats.items():
                print(f"  - {k}: {v}")
    print(f"\nwrote example datasets to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
