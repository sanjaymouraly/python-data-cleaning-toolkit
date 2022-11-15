#!/usr/bin/env python3
"""Capture genuine screenshots of the running Streamlit dashboard.

Prerequisites:
    pip install playwright && playwright install chromium
    streamlit run app/app.py --server.port 8501   (in another terminal)

The script drives the real UI with a real example dataset (no mocks):
upload -> import -> profile -> cleaning profile -> preview -> apply ->
before/after -> audit downloads, capturing docs/images/*.png along the way.
"""

from __future__ import annotations

import argparse
import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.environ.get("DTK_BASE_URL", "http://localhost:8501")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG_DIR = os.path.join(REPO, "docs", "images")
SAMPLE = os.path.join(REPO, "examples", "data", "sales_transactions.csv")


def shot(page, name: str) -> None:
    os.makedirs(IMG_DIR, exist_ok=True)
    path = os.path.join(IMG_DIR, f"{name}.png")
    page.screenshot(path=path, full_page=False)
    size = os.path.getsize(path) / 1024
    print(f"  saved {name}.png ({size:.0f} KB)")


def go_to(page, label: str) -> None:
    page.locator("section[data-testid='stSidebar'] label", has_text=label).first.click()
    page.wait_for_timeout(2500)  # allow the rerun to render


def wait_for_text(page, text: str, timeout: int = 45000) -> None:
    page.wait_for_selector(f"text={text}", timeout=timeout)


def click_button(page, text: str, timeout: int = 15000) -> None:
    btn = page.locator("button", has_text=text).first
    btn.wait_for(state="visible", timeout=timeout)
    btn.click()


def select_option(page, label: str, option: str) -> None:
    """Interact with a Streamlit selectbox (React Aria combobox) via its aria-label."""
    box = page.locator(f"input[role='combobox'][aria-label='{label}']").first
    box.wait_for(state="visible", timeout=30000)
    box.click()
    page.wait_for_timeout(400)
    box.fill(option)
    page.wait_for_timeout(900)
    opt = page.locator("[role='option']", has_text=option).first
    if opt.count() > 0:
        opt.click()
    else:
        box.press("Enter")
    page.wait_for_timeout(800)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=BASE)
    args = parser.parse_args()

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_default_timeout(45000)

        print("1. opening dashboard ...")
        page.goto(args.base_url, wait_until="domcontentloaded")
        wait_for_text(page, "Advanced CSV & Excel Data Cleaner")
        page.wait_for_timeout(1500)

        print("2. upload & import the sales sample ...")
        go_to(page, "Upload & Import")
        page.set_input_files("input[type='file']", SAMPLE)
        page.wait_for_timeout(800)
        click_button(page, "Load dataset")
        wait_for_text(page, "Data preview")
        page.wait_for_timeout(1200)
        shot(page, "02-upload-import")

        print("3. dashboard with loaded dataset ...")
        go_to(page, "Dashboard")
        wait_for_text(page, "Quality score")
        page.wait_for_timeout(1200)
        shot(page, "01-dashboard")

        print("4. data profiling ...")
        go_to(page, "Data Profiling")
        wait_for_text(page, "Quality score (0-100)")
        page.wait_for_timeout(2500)
        shot(page, "03-profiling")

        print("5. cleaning studio: load profile ...")
        go_to(page, "Cleaning Studio")
        wait_for_text(page, "Configuration source")
        select_option(page, "Profile", "example: sales_report")
        click_button(page, "Load profile")
        wait_for_text(page, "Active configuration")
        shot(page, "04-cleaning-config")

        print("6. run preview ...")
        page.get_by_text("2 · Preview", exact=False).first.click()
        page.wait_for_timeout(800)
        click_button(page, "Run preview")
        wait_for_text(page, "Cells changed")
        page.wait_for_timeout(1500)
        shot(page, "05-preview")

        print("7. apply ...")
        page.get_by_text("3 · Apply", exact=False).first.click()
        page.wait_for_timeout(800)
        page.get_by_text("I reviewed the preview and approve", exact=False).first.click()
        page.wait_for_timeout(400)
        click_button(page, "Apply cleaning")
        wait_for_text(page, "Applied:", timeout=90000)
        page.wait_for_timeout(1200)
        shot(page, "06-applied")

        print("8. before vs after ...")
        go_to(page, "Before vs After")
        wait_for_text(page, "Quality metrics before vs after")
        page.wait_for_timeout(2500)
        shot(page, "07-before-after")

        print("9. reports & audit ...")
        go_to(page, "Reports & Audit")
        wait_for_text(page, "Rule outcomes")
        page.wait_for_timeout(1500)
        shot(page, "08-reports-audit")

        browser.close()
    print("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
