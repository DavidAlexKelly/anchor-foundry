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

# **What `expect(...)` waits, when nobody said.** Playwright's own default is
# five seconds, and that default has now produced five failures in this suite
# that had nothing to do with the code under test: §237's ontology search,
# §241's two (a formatter dialog and a `<select>` still being fetched), and
# §243's two - a shared property asserted straight after a save, and the action
# editor's cross-module rename check, which is the same test §233 saw fail once
# and recorded as unexplained.
#
# Every one is the same shape: **an assertion that follows a server round trip,
# given five seconds because nobody chose a number.** They pass in isolation and
# fail in a full run, which is exactly when the box is slowest - so the suite
# reports as flaky when what it is really saying is that one assertion was
# budgeted differently from its neighbours.
#
# Fixing them one at a time has not worked; five is enough evidence for a
# default. This is not a licence to skip `eventually` or `stays`: those exist
# for *derived* reads and for negative claims, and neither is a timeout
# question. It only means a positive locator assertion no longer has to
# out-guess the machine it runs on.
EXPECT_MS = int(os.environ.get("ANCHOR_E2E_EXPECT_MS", "15000"))
expect.set_options(timeout=EXPECT_MS)


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
    _refuse_a_stale_api()


def _refuse_a_stale_api() -> None:
    """Refuse to run against an API older than the code it is supposed to test.

    **`dev-up.sh` starts the API only if nothing is answering**, which is right
    - it is documented as idempotent, and restarting somebody's running server
    because they ran it twice would be worse. The consequence is that editing
    `apps/api/src` and then running this suite tests the *previous* build, and
    Next's hot reload hides how asymmetric that is: browser changes are picked
    up and server ones are not.

    That has cost real time twice. The failure is the worst shape there is - a
    suite that goes red for a change that is actually correct, or green for one
    that is not - and it is the same family as §220's leaked fixture server: a
    result that is not about the code under test. So the suite says so instead
    of running.

    Compares the newest mtime under `apps/api/src` against when the server
    process started. Best-effort: if the process cannot be found or `/proc` is
    not there, this says nothing rather than blocking a run it cannot judge.

    **An mtime, not a hash, and a tool that rewrites a file trips it.** A
    mutation harness that restores a file with `git show HEAD:<path>` writes
    identical bytes and a new mtime, so this refuses a tree that is in fact
    exactly what the server loaded. That is the right way round - this cannot
    know what the process read, and the alternative guess is the failure shape
    the docstring above is about - but it has a consequence worth knowing
    before it costs an afternoon: a harness whose *later* sweeps depend on this
    suite must put the mtime back (`os.utime`) after each restore, or every one
    of those mutants dies on this guard and is scored as caught while proving
    nothing at all.
    """
    import subprocess

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    source = os.path.join(root, "apps", "api", "src")
    if not os.path.isdir(source):
        return
    try:
        found = subprocess.run(
            ["pgrep", "-f", "dev_server.py"], capture_output=True, text=True, timeout=5
        ).stdout.split()
        started = max(os.path.getmtime(f"/proc/{pid}") for pid in found)
    except Exception:
        return
    newest = max(
        (os.path.getmtime(os.path.join(where, name))
         for where, _, names in os.walk(source)
         for name in names if name.endswith(".py")),
        default=0.0,
    )
    # A second of slack: a file written in the same second the server started
    # is one it almost certainly loaded, and the alternative is a suite that
    # refuses to run immediately after `dev-up.sh`.
    if newest > started + 1:
        pytest.fail(
            "the running API is older than apps/api/src, so this suite would test "
            "the previous build. Run scripts/dev-down.sh && scripts/dev-up.sh."
        )


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

    **§249 added canvas apps, and the argument was already written above.**
    Nothing was removing those, so they had reached **28,500 in one workspace**
    by §248 — enough to slow the whole suite to a third of its rate, and enough
    to hide a defect in plain sight: `parameter_usages` read every one of them
    on every action-definition save and had since §129, at 1.44s a time, which
    nobody could notice on a workspace anybody had *meant* to build. The
    leftovers were the only large workspace this build has.

    Teardown runs after the last test, and reports rather than asserts — some
    types cannot be deleted by design (p.256 refuses an `active` one), and
    those are exactly the ones the suite creates to prove the refusal works.
    """
    caller = Api(API_BASE, token)
    yield caller
    removed, left = caller.cleanup()
    print(f"\ncleanup: removed {removed} rows, left {left} that refused deletion")


# ---- what a failure leaves behind (§275) -------------------------------------
#: Where a failing test's screenshot and DOM go. Read by the workflow, which
#: uploads it as an artifact when the job is red.
FAILURE_DIR = os.environ.get("ANCHOR_E2E_FAILURES", "/tmp/anchor-e2e-failures")


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    """Hang each phase's result on the item, so a fixture's teardown can ask
    whether the test it was serving actually failed.

    pytest gives a fixture no way to know this on its own, and the alternative
    - capturing on every test - is what makes an artefact nobody looks at.
    """
    outcome = yield
    setattr(item, f"report_{outcome.get_result().when}", outcome.get_result())


def _capture_failure(page, name: str) -> None:
    """A screenshot and the DOM, and only when something went wrong.

    **Written because three separate investigations could not say which test
    was failing.** §271 fixed this suite's CI diagnostic from printing nothing,
    §272 from printing too much, and §275 found the runner appending three
    hundred lines of Postgres healthcheck noise underneath either. A failure
    that leaves an image behind does not depend on a log window at all.

    Deliberately not a Playwright trace: `snapshots=True` records the DOM on
    every action, and this suite runs eight hundred tests. The cost of a
    diagnostic has to be paid on the failing run, not on all of them.
    """
    try:
        os.makedirs(FAILURE_DIR, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)[:120]
        page.screenshot(path=os.path.join(FAILURE_DIR, f"{safe}.png"), full_page=True)
        with open(os.path.join(FAILURE_DIR, f"{safe}.html"), "w") as f:
            f.write(page.content())
    except Exception:
        # A page that has been closed, or a browser that died with the test,
        # cannot be photographed - and a diagnostic that turns a test failure
        # into a fixture error would hide the thing it exists to explain.
        pass


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
def page(browser, token: str, request):
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
    report = getattr(request.node, "report_call", None)
    if report is not None and report.failed:
        _capture_failure(opened, request.node.name)
    context.close()


def eventually(read, matches, *, what: str, timeout_ms: int | None = None):
    """Poll `read()` until `matches(...)`, then return the value.

    Playwright's own `expect` covers anything that *is* a locator — a count, a
    text, an attribute — and is used directly wherever it fits. This exists for
    the derived reads a locator assertion cannot express: a grid of numbers
    parsed out of table cells, a list of counts pulled from SVG tooltips.

    The failure message carries the last value seen, because "still [3, 2] after
    20s" says what went wrong and "timed out" does not.

    **Never poll `page.url` with this** (§284, and it cost a probe). `page.url`
    is a value Playwright caches and refreshes when its driver processes a
    navigation event; the loop below never yields, so the driver never gets a
    turn and the same stale string comes back for the whole timeout. The test
    then reports that nothing happened when the address bar changed seconds
    earlier. `page.wait_for_url(...)` is the waiter for that, and the same
    caution applies to anything else that is a cached property rather than a
    fresh read: this is for values *derived* from the DOM or fetched over HTTP.

    **And a caution about the opposite shape** (§291, found by a survivor):
    `expect(locator).to_have_count(0)` passes the instant it is called if the
    thing has not rendered yet, so an absence asserted straight after opening a
    dialog or navigating is a check that cannot fail. Nothing is absent more
    convincingly than something that has not arrived. Wait for a *sibling* that
    must be there — the row above it, the panel's heading — and then assert the
    absence, so the assertion is about the product rather than about timing.
    `stays(...)` below is the other answer, for absences that must hold over
    time rather than at one moment.
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


def stays(read, matches, *, what: str, for_ms: int = 5000):
    """`eventually`'s counterpart: assert a thing **keeps** being true.

    **The primitive a negative claim about an async page actually needs**, and
    §233 is what asked for it. "Pressing Escape wrote nothing" cannot be checked
    by reading once: the write it is ruling out takes a round trip, so a read
    taken straight after the keypress sees the page *before* the thing that
    would have failed it, and passes either way. `settled` does not help - it
    waits for a canvas block that is already on screen - and neither does
    re-reading through a retrying matcher, because `expect` stops at the first
    read that matches, which is the one taken too early.

    So the shape is: keep looking for long enough that the write would have
    landed, and fail on the first look that disagrees. §233's mutant committed
    within about a second; the default window is five.

    This is a timeout-based assertion and says so - it can only ever show that
    nothing happened *yet*. Where an ordered positive signal exists, wait for
    that instead; this is for the cases where there is none.
    """
    deadline = time.monotonic() + for_ms / 1000
    last = None
    while time.monotonic() < deadline:
        last = read()
        if not matches(last):
            raise AssertionError(f"{what}: became {last!r}")
        time.sleep(POLL_MS / 1000)
    return last


def option_values(select_locator, *, count: int) -> list[str]:
    """A `<select>`'s option *values*, once there are `count` of them.

    **The wait is the whole helper.** `evaluate_all` and `all_text_contents`
    are one-shot reads, and every property picker in this suite is empty until
    the object type resolves — so a read taken straight after `to_be_visible()`
    catches the built-in options and nothing else. `expect(...).to_have_count`
    retries; the read after it is then safe.

    §202 and §231 found this, and `test_prominent_terms.py` has done it
    correctly ever since — which did not stop five other call sites reading the
    list raw. §271 is what that cost: those tests passed against a long-lived
    development database, where the ontology query is warm, and failed against
    every fresh one. CI has a fresh database on every run, so the browser job
    was red for ten merges while nobody could reproduce it locally.
    """
    options = select_locator.locator("option")
    expect(options).to_have_count(count)
    return options.evaluate_all("nodes => nodes.map(n => n.value)")


def option_labels(select_locator, *, count: int) -> list[str]:
    """The same, for the text a person reads rather than the stored value."""
    options = select_locator.locator("option")
    expect(options).to_have_count(count)
    return options.all_text_contents()


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
