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
import time
import urllib.error
import urllib.request

import pytest
from playwright.sync_api import expect

from api import Api

API_BASE = os.environ.get("ANCHOR_API_BASE", "http://localhost:8300/api")
WEB_BASE = os.environ.get("ANCHOR_WEB_BASE", "http://localhost:3100")
TOKENS_FILE = os.environ.get("ANCHOR_TOKENS_FILE", "/tmp/anchor-dev-tokens.json")
ADMIN_DSN = os.environ.get(
    "TEST_ADMIN_DSN", "postgresql://platform:devpass@localhost:5432/platform?sslmode=disable"
)
CHROMIUM = os.environ.get("PLAYWRIGHT_CHROMIUM", "/opt/pw-browsers/chromium")

# **How long a check may wait, not how long it does wait.** These are deadlines
# for the polling helpers below; a test that is ready in 200ms takes 200ms.
#
# The suite used to sleep these amounts unconditionally, which had two costs.
# It was slow — twelve minutes for twenty-eight tests, nearly all of it spent
# waiting for things that had already happened. And it was tuned to one
# machine: a slower CI runner would have started failing tests that were merely
# late, and a suite that flakes gets ignored, which is worse than no suite.
SETTLE_MS = int(os.environ.get("ANCHOR_E2E_SETTLE_MS", "20000"))
FIRST_RENDER_MS = int(os.environ.get("ANCHOR_E2E_FIRST_RENDER_MS", "30000"))
# How often a derived value is re-read while waiting. Small enough to be
# invisible, large enough not to spin.
POLL_MS = 100


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
    """The suite's one API caller — and the thing that tidies up after it.

    **The suite used to leave every object type it created behind.** In a
    long-lived dev workspace that accumulates: about 1,400 of them over one
    session, which is enough that the Ontology Manager's listing (it fetches
    and renders every type in the workspace) took seven seconds to open a
    dialog, and a test relying on Playwright's five-second default went red.
    Nothing had changed in the product; the suite had aged into failing on its
    own leftovers.

    Teardown runs after the last test, and reports rather than asserts — some
    types cannot be deleted by design (p.256 refuses an `active` one), and
    those are exactly the ones the suite creates to prove the refusal works.
    """
    caller = Api(API_BASE, token)
    yield caller
    removed, left = caller.cleanup()
    print(f"\ncleanup: removed {removed} object types, left {left} that refused deletion")


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
    # Waits for the redirect off /login rather than for a fixed interval.
    opened.wait_for_url(lambda url: "/login" not in url, timeout=FIRST_RENDER_MS)
    opened.console_errors = errors  # type: ignore[attr-defined]
    yield opened
    context.close()


def eventually(read, matches, *, what: str, timeout_ms: int | None = None):
    """Poll `read()` until `matches(...)`, then return the value.

    Playwright's own `expect` covers anything that *is* a locator — a count, a
    text, an attribute — and is used directly wherever it fits. This exists for
    the derived reads a locator assertion cannot express: a grid of numbers
    parsed out of table cells, a list of counts pulled from SVG tooltips.

    The failure message carries the last value seen, because "still [3, 2] after
    20s" says what went wrong and "timed out" does not.
    """
    deadline = time.monotonic() + (timeout_ms or SETTLE_MS) / 1000
    last = None
    while True:
        last = read()
        if matches(last):
            return last
        if time.monotonic() > deadline:
            raise AssertionError(f"{what}: still {last!r} after {timeout_ms or SETTLE_MS}ms")
        time.sleep(POLL_MS / 1000)


def settled(page, locator_or_none=None) -> None:
    """Wait for the module to have rendered *something* before asserting.

    **This is the guard that makes negative assertions honest.** `expect(x).
    to_have_count(0)` passes instantly on a page that has not drawn yet, so a
    check for "this widget offers no handles" would be green before the widget
    existed. Every test that asserts an absence waits for a presence first.
    """
    expect(page.locator(".canvas-block, .canvas-section, .canvas-cards").first).to_be_visible(
        timeout=FIRST_RENDER_MS
    )
    if locator_or_none is not None:
        expect(locator_or_none).to_be_visible(timeout=FIRST_RENDER_MS)


def open_module(page, module, *, settle_ms: int | None = None) -> None:
    """Open a module and switch to Preview, which is where widgets read data.

    The builder renders the same widgets, but in edit mode a click is a
    selection rather than an interaction - so anything about *behaviour* has to
    be asked in Preview.
    """
    page.goto(f"{WEB_BASE}{module.url}")
    preview = page.get_by_role("button", name="Preview", exact=True)
    expect(preview).to_be_visible(timeout=FIRST_RENDER_MS)
    preview.click()
    settled(page)


def open_builder(page, module) -> None:
    """Open a module and stay in the builder.

    The opposite of `open_module`, and needed for anything about *authoring*:
    layout handles, settings panels and the layout tree only exist in edit
    mode, because what they change is the saved document rather than what a
    viewer is looking at.
    """
    page.goto(f"{WEB_BASE}{module.url}")
    settled(page)


# Console noise the *dev server* makes, which no deployed build can produce and
# no test should fail on.
#
# The favicon 404 was the first. The second was found the hard way: a full-suite
# run failed once on `test_resource_filter` with
#
#   "Failed to fetch RSC payload for http://localhost:3100/home.
#    Falling back to browser navigation."
#
# and passed on every re-run, which read convincingly as flakiness for two
# sessions. It is not flaky - it is Next's router prefetching a route while the
# dev server is recompiling, which happens exactly when somebody is editing
# source during a run. The message even names its source: `hot-reloader-client`.
# Next says "falling back to browser navigation" because it *recovered*, so
# failing on it is failing on a message about something that worked.
#
# Matched narrowly on purpose. "Failed to fetch" on its own would swallow a real
# API call that did not come back, which is precisely the class of bug this
# assertion exists to catch.
DEV_SERVER_NOISE = (
    "favicon",
    "Failed to fetch RSC payload",
    # **`hot-reloader-client` used to be here, and it was swallowing everything.**
    # It was added because the prefetch message above names that file as its
    # source - but in Next's dev build *React's own `console.error` is routed
    # through the same client*, so every React error carried the string and
    # every one of them was filtered out. This assertion was decoration for as
    # long as that line existed.
    #
    # Found by §198's mutation harness: a mutant keying loop copies by value
    # instead of by position makes React log "Encountered two children with the
    # same key", the test asserted no console errors, and it passed anyway.
    #
    # The rule: **match a noise filter to the message, never to its source.** A
    # source is shared with the things worth failing on. The prefetch message is
    # matched by its own text one line up, which is what it should have been
    # matched by all along.
)


def no_console_errors(page) -> list[str]:
    """Console errors worth failing on - the app's, not the dev server's."""
    return [
        e for e in page.console_errors
        if not any(ignored in e for ignored in DEV_SERVER_NOISE)
    ]
