"""The resource browser's kind filter lives in the URL (parity stage 1).

Foundry's project landing page is Files, a browser over the project's
resources, and each resource "opens in a different platform application"
(`docs/pal/foundry_getting-started.pdf` p.37). Our six pillar pages are a
second implementation of that list, which is the condition under which two
lists drift - and they have. The filter had to move into the URL first, so a
pillar page can *be* this browser with `?kind=` applied rather than a rewrite
of it.

`resource-filter.test.ts` covers the rules as arithmetic. This covers the two
things arithmetic cannot see: that the URL actually drives the rendered table,
and that a shared link survives a reload.

Every test here is written against a mutation: put the filter back in
`useState` so the URL is ignored, and all five go red. Two of them needed a
contrast against a narrower filter to manage it - asserting "these kinds are
present" alone passes happily on a page showing everything.

**Every read of the table goes through `eventually`.** The listing query keeps
the previous rows on screen while a new one is in flight (`placeholderData`),
which is right for the reader and a trap for a test: the URL changes first, so
reading the table immediately after asserting the URL sees the *previous*
filter's rows. That raced into a real failure at exactly one call site, and
only in the full-suite run - the shape of flake that gets a suite ignored.
"""
from __future__ import annotations

import re

import pytest

from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, FIRST_RENDER_MS, eventually, no_console_errors

ROWS = [{"id": "r-1", "name": "One"}, {"id": "r-2", "name": "Two"}]

BOTH = {"Canvas app", "Dataset"}


@pytest.fixture(scope="module")
def project(api):
    """A project holding two kinds of resource, so a filter has something to
    exclude. One kind alone could not tell filtering from listing."""
    built = Module(api, "ResourceFilter")
    built.object_type(columns=["id", "name"], rows=ROWS, key="id", title="name")
    built.define({"format": 2, "layout": {}, "variables": {}})
    return built


def browse(page, project, query: str = "") -> None:
    """Open the project browser and wait for it to have drawn.

    Not `conftest.settled`, which waits for a canvas widget: this page has
    none, and a helper that waits for the wrong thing is how a negative
    assertion passes against a page that never rendered.
    """
    page.goto(f"{WEB_BASE}/{project.workspace_slug}/{project.project_slug}{query}")
    expect(page.locator(".rb-chips")).to_be_visible(timeout=FIRST_RENDER_MS)
    # Then wait for the listing to have *finished*, by the disappearance of the
    # loading state. Waiting for ".rb-table, .state" instead looks equivalent
    # and is not: it matches the loading div too, so it returns while the table
    # is still empty - and on a filter test that is precisely the moment a
    # wrong answer looks like a right one. (It also trips Playwright's strict
    # mode the moment both are on screen at once, which is how this was found.)
    expect(page.get_by_text("Loading…")).to_have_count(0, timeout=FIRST_RENDER_MS)


def kinds_shown(page, expected: set[str], *, what: str) -> None:
    """Wait for the Type column to hold exactly `expected`, and no more.

    `eventually` rather than a bare read for the `placeholderData` reason in
    the module docstring, and *exactly* rather than a subset because a subset
    check cannot tell a filter that narrowed from one that did nothing.

    **`all_inner_texts()`, not `count()` then `nth(i)`.** The obvious loop
        {cells.nth(i).inner_text() for i in range(cells.count())}
    reads the count and the cells as separate round trips, so a re-render
    landing in between - which is exactly what a filter change causes - leaves
    it asking for a row that no longer exists, and `nth(i).inner_text()` then
    *blocks for the full 30s timeout* rather than returning something stale for
    `eventually` to reject. It cost a 48-second run and looked for a while like
    a slow machine. One call, one snapshot, no torn read.
    """
    cells = page.locator(".rb-table tbody tr td:nth-child(2)")
    eventually(
        lambda: {text.strip() for text in cells.all_inner_texts()},
        lambda seen: seen == expected,
        what=f"kinds listed for {what}",
    )


def test_kind_in_the_url_filters_the_table(page, project):
    """`?kind=canvas_app` renders canvas apps and nothing else.

    The project also contains a dataset, so a filter that silently did nothing
    would still show it and fail here. That is the assertion that makes this a
    check rather than a screenshot.
    """
    browse(page, project, "?kind=canvas_app")
    kinds_shown(page, {"Canvas app"}, what="?kind=canvas_app")

    browse(page, project, "?kind=dataset")
    kinds_shown(page, {"Dataset"}, what="?kind=dataset")
    assert not no_console_errors(page)


def test_two_kinds_are_a_union_not_an_intersection(page, project):
    """A repeated parameter widens the filter. Reading it as an intersection
    would render an empty table - a resource has exactly one kind - and the
    failure would read as "the filter is broken" rather than "the filter means
    the wrong thing"."""
    browse(page, project, "?kind=dataset")
    kinds_shown(page, {"Dataset"}, what="one kind, as a baseline")

    # Checked against the one-kind case above rather than asserted flat, so a
    # build ignoring the URL entirely - which shows every kind, and would
    # satisfy a bare equality here - still fails on the baseline.
    browse(page, project, "?kind=canvas_app&kind=dataset")
    kinds_shown(page, BOTH, what="two kinds")


def test_an_unknown_kind_is_disregarded_not_forwarded(page, project):
    """`?kind=nonsense` shows the unfiltered project.

    The alternative - passing it through to the API - renders an empty table,
    which a reader cannot tell apart from an empty project. `kind=toString` is
    here because the lookup was a plain object at first, so it walked the
    prototype chain and read that as a real kind.
    """
    browse(page, project, "?kind=dataset")
    kinds_shown(page, {"Dataset"}, what="a real filter still narrows")

    for junk in ("?kind=nonsense", "?kind=toString"):
        browse(page, project, junk)
        kinds_shown(page, BOTH, what=junk)


def test_a_chip_writes_the_url_and_the_link_survives_a_reload(page, project):
    """Clicking a chip is what produces a shareable link, so both halves are
    asserted together: the click writes `kind=`, and re-opening that URL cold
    comes back to the same filtered view."""
    browse(page, project)
    kinds_shown(page, BOTH, what="unfiltered, before the click")

    page.get_by_role("button", name="Canvas apps").click()
    expect(page).to_have_url(re.compile(r"kind=canvas_app"), timeout=FIRST_RENDER_MS)
    kinds_shown(page, {"Canvas app"}, what="after the click")

    # Opened in a *new tab*, not by navigating this one away and back. It is
    # both a stricter statement of "cold" - no component state survives a new
    # page at all, where a round trip through /login relies on the router
    # having really torn down - and one navigation instead of two. The two-hop
    # version timed out once on the first run after a source change, when the
    # dev server was recompiling routes; a check that fails when the machine is
    # busy is a check people learn to re-run rather than read.
    fresh = page.context.new_page()
    try:
        fresh.goto(page.url)
        kinds_shown(fresh, {"Canvas app"}, what="the shared link, opened cold")
        expect(fresh.get_by_role("button", name="Canvas apps")).to_have_attribute(
            "aria-pressed", "true"
        )
    finally:
        fresh.close()


def test_turning_the_last_chip_off_clears_the_filter(page, project):
    """The chip is a toggle, and the off state must remove the parameter rather
    than leave `kind=` empty behind - an empty repeated parameter is the kind of
    thing that reaches an API as a filter on the empty string."""
    browse(page, project, "?kind=canvas_app")
    kinds_shown(page, {"Canvas app"}, what="filtered, before the click")

    page.get_by_role("button", name="Canvas apps").click()
    expect(page).to_have_url(re.compile(r"^(?!.*kind=).*$"), timeout=FIRST_RENDER_MS)
    kinds_shown(page, BOTH, what="unfiltered again")
