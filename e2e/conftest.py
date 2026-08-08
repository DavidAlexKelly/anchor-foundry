"""Fixtures for the browser suite.

**These tests drive a real browser against real dev servers.** They do not
mock, stub or render components in isolation, because the defects they exist to
catch have consistently not been visible to the API tests: a widget that read
the right data and drew the wrong thing, a filter that was sent when it should
have been dropped, an action form that never refreshed the table beside it.

They are written in Python rather than in a JavaScript test runner for one
reason: the seeding is API calls, the assertions are about server-computed
numbers, and the repo already has one test runner. A second runner with its own
lockfile and its own fixtures would be a second place test setup lives. The
cost is real and worth stating - a front-end change is verified by a suite in
another language, in another directory - and `scripts/check.sh` exists so that
nobody has to remember that.

Run them with the stack up:

    scripts/dev-up.sh          # Postgres, the API on 8300, Next on 3100
    scripts/check.sh           # everything, including these
    .venv-api/bin/python -m pytest e2e -q     # just these
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import pytest

from api import Api

API_BASE = os.environ.get("ANCHOR_API_BASE", "http://localhost:8300/api")
WEB_BASE = os.environ.get("ANCHOR_WEB_BASE", "http://localhost:3100")
TOKENS_FILE = os.environ.get("ANCHOR_TOKENS_FILE", "/tmp/anchor-dev-tokens.json")
ADMIN_DSN = os.environ.get(
    "TEST_ADMIN_DSN", "postgresql://platform:devpass@localhost:5432/platform?sslmode=disable"
)
CHROMIUM = os.environ.get("PLAYWRIGHT_CHROMIUM", "/opt/pw-browsers/chromium")

# Waits, in one place because they are the thing most likely to need tuning on
# a slower machine, and because scattering magic numbers through assertions is
# how a suite becomes flaky without anybody deciding to make it flaky.
SETTLE_MS = int(os.environ.get("ANCHOR_E2E_SETTLE_MS", "7000"))
FIRST_RENDER_MS = int(os.environ.get("ANCHOR_E2E_FIRST_RENDER_MS", "9000"))


def _reachable(url: str) -> bool:
    try:
        urllib.request.urlopen(url, timeout=2).read()
        return True
    except urllib.error.HTTPError:
        return True  # answered, which is all this asks
    except Exception:
        return False


@pytest.fixture(scope="session")
def stack() -> None:
    """Refuse to run against half a stack.

    Skipping with a message beats failing with a timeout: a suite that reports
    twelve assertion failures because Next was not running has told you nothing
    about the code. `ANCHOR_E2E_REQUIRED=1` turns the skip into a failure,
    which is what CI wants - there, a missing stack *is* the bug.
    """
    missing = [
        name
        for name, url in (("api", f"{API_BASE}/health"), ("web", f"{WEB_BASE}/login"))
        if not _reachable(url)
    ]
    if missing:
        message = (
            f"the dev stack is not up ({', '.join(missing)} unreachable). "
            "Run scripts/dev-up.sh first."
        )
        if os.environ.get("ANCHOR_E2E_REQUIRED"):
            pytest.fail(message)
        pytest.skip(message)


@pytest.fixture(scope="session")
def token(stack: None) -> str:
    """The owner's dev token, from the file `dev_server.py --tokens-file` wrote."""
    if not os.path.exists(TOKENS_FILE):
        pytest.fail(
            f"{TOKENS_FILE} does not exist - start the API with "
            "--tokens-file (scripts/dev-up.sh does)."
        )
    with open(TOKENS_FILE) as handle:
        tokens = json.load(handle)
    return tokens["owner@acme.dev.local"]


@pytest.fixture(scope="session")
def api(token: str) -> Api:
    return Api(API_BASE, token)


@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        launched = playwright.chromium.launch(
            **({"executable_path": CHROMIUM} if os.path.exists(CHROMIUM) else {})
        )
        yield launched
        launched.close()


@pytest.fixture
def page(browser, token: str):
    """A signed-in page, and a failure on any console error.

    The console check is not decoration. A React error boundary catches a
    thrown render and shows *something*, so a widget can be broken while a
    screenshot looks plausible - the errors are how that surfaces.
    """
    context = browser.new_context(viewport={"width": 1500, "height": 1200})
    opened = context.new_page()
    errors: list[str] = []
    opened.on(
        "console",
        lambda message: errors.append(message.text) if message.type == "error" else None,
    )
    opened.goto(f"{WEB_BASE}/login")
    opened.fill("input[placeholder='Paste an access token']", token)
    opened.get_by_role("button", name="Use token").click()
    opened.wait_for_timeout(2500)
    opened.console_errors = errors  # type: ignore[attr-defined]
    yield opened
    context.close()


def open_module(page, module, *, settle_ms: int | None = None) -> None:
    """Open a module and switch to Preview, which is where widgets read data.

    The builder renders the same widgets, but in edit mode a click is a
    selection rather than an interaction - so anything about *behaviour* has to
    be asked in Preview.
    """
    page.goto(f"{WEB_BASE}{module.url}")
    page.wait_for_timeout(FIRST_RENDER_MS)
    page.get_by_role("button", name="Preview", exact=True).click()
    page.wait_for_timeout(settle_ms or FIRST_RENDER_MS)


def no_console_errors(page) -> list[str]:
    """Console errors worth failing on. The favicon 404 is the dev server's,
    not the app's."""
    return [e for e in page.console_errors if "favicon" not in e]
