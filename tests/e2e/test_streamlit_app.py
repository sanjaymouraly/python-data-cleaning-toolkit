"""E2E tests for the Streamlit dashboard using streamlit.testing.AppTest.

These run the real app script and exercise real widget interactions; they
complement (not replace) the Playwright browser smoke test in
tests/e2e/test_browser.py.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("streamlit.testing")

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP = os.path.join(REPO, "app", "app.py")
DATA = os.path.join(REPO, "examples", "data")
CONFIGS = os.path.join(REPO, "configs")

from streamlit.testing.v1 import AppTest


@pytest.fixture()
def at():
    app = AppTest.from_file(APP, default_timeout=120)
    app.run()
    assert not len(app.exception), f"app crashed: {[e.value for e in app.exception]}"
    return app


class TestShell:
    def test_app_renders_without_exceptions(self, at):
        assert not len(at.exception)

    def test_navigation_lists_all_pages(self, at):
        assert set(at.radio[0].options) == {
            "Dashboard", "Upload & Import", "Data Profiling", "Cleaning Studio",
            "Before vs After", "Reports & Audit", "Settings",
        }

    @pytest.mark.parametrize(
        "page",
        ["Dashboard", "Upload & Import", "Data Profiling", "Cleaning Studio",
         "Before vs After", "Reports & Audit", "Settings"],
    )
    def test_every_page_renders(self, at, page):
        at.radio[0].set_value(page).run()
        assert not len(at.exception), f"{page}: {[e.value for e in at.exception]}"

    def test_empty_states_guide_the_user(self, at):
        at.radio[0].set_value("Data Profiling").run()
        assert not len(at.exception)


class TestSettings:
    def test_settings_defaults(self, at):
        at.radio[0].set_value("Settings").run()
        assert not len(at.exception)
        # default format selectbox exists with csv selected
        assert any(sb.value == "csv" for sb in at.selectbox)


class TestStudioRequiresDataset:
    def test_studio_shows_empty_state_without_data(self, at):
        at.radio[0].set_value("Cleaning Studio").run()
        assert not len(at.exception)
        assert not at.button  # no apply/preview buttons without a dataset
