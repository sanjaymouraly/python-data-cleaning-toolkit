"""Browser-based smoke test with Playwright against the real running app.

Skipped automatically unless:
  * playwright is installed AND chromium is available, and
  * DTK_E2E_BROWSER=1 is set (the repo's own CI/docs workflow starts the app
    first:  streamlit run app/app.py --server.port 8501).

Run:  DTK_E2E_BROWSER=1 pytest tests/e2e/test_browser.py -v
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("playwright.sync_api")

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASE_URL = os.environ.get("DTK_BASE_URL", "http://localhost:8501")
SAMPLE = os.path.join(REPO, "examples", "data", "sales_transactions.csv")

if not os.environ.get("DTK_E2E_BROWSER"):
    pytest.skip(
        "browser smoke test needs a running dashboard; set DTK_E2E_BROWSER=1 "
        "(and start `streamlit run app/app.py`) to enable",
        allow_module_level=True,
    )

from playwright.sync_api import sync_playwright  # noqa: E402


@pytest.fixture(scope="module")
def page():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        pg = browser.new_page(viewport={"width": 1440, "height": 900})
        pg.set_default_timeout(45000)
        pg.goto(BASE_URL, wait_until="domcontentloaded")
        pg.wait_for_selector("text=Data Cleaner", timeout=60000)
        yield pg
        browser.close()


def go_to(pg, label):
    pg.locator("section[data-testid='stSidebar'] label", has_text=label).first.click()
    pg.wait_for_timeout(2500)


def test_app_loads(page):
    assert page.locator("text=Advanced CSV").first.is_visible() or page.locator(
        "text=Data Cleaner"
    ).first.is_visible()


def test_load_sample_and_profile(page):
    go_to(page, "Upload & Import")
    page.set_input_files("input[type='file']", SAMPLE)
    page.wait_for_timeout(800)
    page.locator("button", has_text="Load dataset").first.click()
    page.wait_for_selector("text=Data preview", timeout=60000)
    go_to(page, "Data Profiling")
    page.wait_for_selector("text=Quality score (0-100)", timeout=60000)


def test_full_cleaning_flow(page):
    go_to(page, "Cleaning Studio")
    box = page.locator("input[role='combobox'][aria-label='Profile']").first
    box.wait_for(state="visible", timeout=30000)
    box.click()
    box.fill("example: sales_report")
    page.wait_for_timeout(900)
    page.locator("[role='option']", has_text="example: sales_report").first.click()
    page.wait_for_timeout(600)
    page.locator("button", has_text="Load profile").first.click()
    page.wait_for_selector("text=Active configuration", timeout=60000)

    # preview
    page.get_by_text("2 · Preview", exact=False).first.click()
    page.wait_for_timeout(700)
    page.locator("button", has_text="Run preview").first.click()
    page.wait_for_selector("text=Cells changed", timeout=90000)

    # apply with approval
    page.get_by_text("3 · Apply", exact=False).first.click()
    page.wait_for_timeout(700)
    page.get_by_text("I reviewed the preview and approve", exact=False).first.click()
    page.wait_for_timeout(400)
    page.locator("button", has_text="Apply cleaning").first.click()
    page.wait_for_selector("text=Applied:", timeout=120000)

    # before/after renders
    go_to(page, "Before vs After")
    page.wait_for_selector("text=Quality metrics before vs after", timeout=60000)

    # audit page lists the run
    go_to(page, "Reports & Audit")
    page.wait_for_selector("text=Rule outcomes", timeout=60000)
