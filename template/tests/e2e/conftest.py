"""Fixtures for the Playwright journeys: a live server and a signed-in page."""

import os
from typing import Any

import pytest
from playwright.sync_api import Page

from tests.factories import UserFactory


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args: dict[str, Any]) -> dict[str, Any]:
    """Use a preinstalled Chromium when PLAYWRIGHT_CHROMIUM_EXECUTABLE names one.

    Cloud sandboxes ship a browser but block Playwright's download; CI
    installs its own and leaves this unset.
    """
    if path := os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE"):
        return {**browser_type_launch_args, "executable_path": path}
    return browser_type_launch_args


@pytest.fixture
def signed_in_page(page: Page, live_server: Any) -> Page:
    """A page signed in through the real form, controlled by the service worker."""
    UserFactory.create(username="walker")
    page.goto(f"{live_server.url}/login/")
    page.get_by_label("Username").fill("walker")
    page.get_by_label("Password").fill("password")
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url("**/notes/")
    # The first load installs the worker; it takes control without a reload.
    page.wait_for_function("navigator.serviceWorker.controller !== null")
    # Load once more through the worker, so this page is cached for offline.
    page.reload()
    return page
