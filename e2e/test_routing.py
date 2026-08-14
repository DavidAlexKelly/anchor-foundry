"""Workshop routing (`foundry_workshop` p.195–199).

    "Workshop routing enables specific states or views of a module to be
    written to the URL, allowing users to easily share these views with others
    through link sharing." (p.195)

The rules about *which* values belong in a link are arithmetic and live in
`canvas/routing.test.ts`. What needs a browser is the claim the feature is
actually making: **that the address bar and the module stay in step**, in both
directions, through a real router. A pure function returning the right map is
not that — a viewer types in a filter, the URL changes, and the link they copy
opens the module where they left it.

Two modules, because the load-bearing distinction is between them:

    routed    routing on:  a filter and a page that appear in the URL
    unrouted  routing off: the same widgets, and an address bar that stays put
"""
from __future__ import annotations

from urllib.parse import parse_qs

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import WEB_BASE, eventually, open_module

COUNTS = {"north": 3, "south": 2}
TOTAL = sum(COUNTS.values())


def document(type_id: str, *, routing: bool) -> dict:
    """Two pages, one routed filter, one filter that is deliberately not."""
    return {
        "format": 2,
        **({"routing": {"enabled": True}} if routing else {}),
        "layout": layout(
            {
                "p1": {
                    "resolvedName": "CanvasPage",
                    "props": {"title": "Sites", "pageId": "sites"},
                    "nodes": ["ctl", "tbl"],
                },
                "ctl": {
                    "parent": "p1",
                    "resolvedName": "CanvasParameterControl",
                    "props": {"name": "v_region", "label": "Region", "control": "text"},
                },
                "tbl": {
                    "parent": "p1",
                    "resolvedName": "CanvasObjectTable",
                    "props": {"objectSetVariable": "v_narrowed",
                              "columns": "id,region", "pageSize": 25},
                },
                "p2": {
                    "resolvedName": "CanvasPage",
                    "props": {"title": "Notes", "pageId": "notes"},
                    "nodes": ["ctl2", "txt"],
                },
                # Bound only on page two, so `when_visible` has somewhere to be
                # invisible. Without a second page the two behaviours are
                # indistinguishable and the test proves half of what it says.
                "ctl2": {
                    "parent": "p2",
                    "resolvedName": "CanvasParameterControl",
                    "props": {"name": "v_note", "label": "Note", "control": "text"},
                },
                "txt": {
                    "parent": "p2",
                    "resolvedName": "CanvasText",
                    "props": {"tag": "p", "text": "Note: {{v_note}}"},
                },
                "tabs": {
                    "resolvedName": "CanvasTabs",
                    "props": {},
                },
            }
        ),
        "variables": {
            "v_all": {
                "id": "v_all", "kind": "object_set", "label": "All sites",
                "object_set": object_set(type_id),
            },
            "v_region": {
                "id": "v_region", "kind": "string", "label": "Region",
                "external_id": "region", "interface": True,
                "url_behavior": "always",
            },
            "v_note": {
                "id": "v_note", "kind": "string", "label": "Note",
                "external_id": "note", "interface": True,
                "url_behavior": "when_visible",
            },
            "v_narrowed": {
                "id": "v_narrowed", "kind": "object_set", "label": "Narrowed",
                "derivation": {
                    "transform": "filter_set", "inputs": ["v_all", "v_region"],
                    "config": {"property": "region", "op": "eq"},
                },
            },
        },
        "events": {},
    }


def build(api, name: str, *, routing: bool) -> Module:
    rows = [
        {"id": f"{region[0].upper()}{i}", "region": region}
        for region, count in COUNTS.items()
        for i in range(1, count + 1)
    ]
    mod = Module(api, name)
    type_id = mod.object_type(columns=["id", "region"], rows=rows, key="id")
    mod.define(document(type_id, routing=routing))
    return mod


@pytest.fixture(scope="module")
def routed(api):
    return build(api, "Routed", routing=True)


@pytest.fixture(scope="module")
def unrouted(api):
    return build(api, "Unrouted", routing=False)


def query(page) -> dict[str, list[str]]:
    """The live query string, read **out of the browser**.

    Not `page.url`, which is Playwright's cached view of the main frame and is
    refreshed by navigation events. Routing writes with `router.replace`, which
    is a `history.replaceState` and fires none — so `page.url` can sit on a
    stale value indefinitely while the address bar has moved on. This cost an
    hour: an identical check passed whenever some *other* locator call happened
    to refresh the cache, and failed when it did not.
    """
    return parse_qs(page.evaluate("location.search").lstrip("?"))


def rows(page) -> int:
    return page.locator(".canvas-block table tbody tr").count()


def type_region(page, value: str) -> None:
    box = page.get_by_label("Region", exact=True)
    box.fill(value)
    box.blur()


def test_a_routed_filter_reaches_the_address_bar(page, routed):
    """p.195's whole claim. The value a viewer chose is in the link they would
    copy, under the external ID they named it by."""
    open_module(page, routed)
    eventually(lambda: rows(page), lambda n: n == TOTAL, what="every site")

    type_region(page, "north")
    eventually(lambda: rows(page), lambda n: n == COUNTS["north"],
               what="the filter actually narrowing the table")
    eventually(lambda: query(page).get("region"), lambda v: v == ["north"],
               what="the chosen value in the URL")


def test_the_same_link_opens_the_same_view(page, routed):
    """The point of writing it: a link is only worth sharing if it restores
    what it described. Inbound is `seedFromQuery` and is a separate rule
    (p.198) - this is the round trip, which is what a reader experiences."""
    open_module(page, routed)
    type_region(page, "south")
    eventually(lambda: query(page).get("region"), lambda v: v == ["south"],
               what="the filter in the URL")
    link = page.evaluate("location.href")

    page.goto(link)
    eventually(lambda: rows(page), lambda n: n == COUNTS["south"],
               what="the shared view, restored from the link alone")
    expect(page.get_by_label("Region", exact=True)).to_have_value("south")


def test_clearing_a_filter_takes_it_out_of_the_link(page, routed):
    """A stale parameter is worse than a missing one: it would be read back on
    the next load and restore a filter nobody has applied. p.198's "the value
    is not the variable's default value", from the removing side."""
    open_module(page, routed)
    type_region(page, "north")
    eventually(lambda: query(page).get("region"), lambda v: v == ["north"],
               what="something to clear")

    type_region(page, "")
    eventually(lambda: query(page).get("region"), lambda v: v is None,
               what="the parameter gone, not left behind as empty")
    eventually(lambda: rows(page), lambda n: n == TOTAL, what="every site again")


def test_routing_off_leaves_the_address_bar_alone(page, unrouted):
    """p.195 puts the whole feature behind one toggle. The same widgets, the
    same variables configured the same way - and nothing written."""
    open_module(page, unrouted)
    before = page.evaluate("location.href")
    type_region(page, "north")
    eventually(lambda: rows(page), lambda n: n == COUNTS["north"],
               what="the filter working, which it does either way")
    # Given a moment to write, and it must not have.
    assert query(page).get("region") is None, page.evaluate("location.href")
    assert page.evaluate("location.href") == before, page.evaluate("location.href")


def test_a_when_visible_variable_stays_out_until_its_page_is_open(page, routed):
    """p.198's difference between the two behaviours, and the only one a
    browser can show: `v_note` is bound on page two only, so a value set for
    it belongs in the URL when page two is on screen and not before."""
    open_module(page, routed)
    # The page ID of the page we open on (p.197), written because it has one.
    eventually(lambda: query(page).get("page"), lambda v: v == ["sites"],
               what="the current page in the URL")
    assert query(page).get("note") is None, page.evaluate("location.href")

    page.locator(".canvas-tab").filter(has_text="Notes").click()
    eventually(lambda: query(page).get("page"), lambda v: v == ["notes"],
               what="the URL following the navigation")
    box = page.get_by_label("Note", exact=True)
    box.fill("check the roof")
    box.blur()
    eventually(lambda: query(page).get("note"), lambda v: v == ["check the roof"],
               what="the note, now that its page is the one on screen")

    page.locator(".canvas-tab").filter(has_text="Sites").click()
    eventually(lambda: query(page).get("note"), lambda v: v is None,
               what="the note leaving the URL with its page")


def test_a_link_naming_a_page_opens_on_that_page(page, routed):
    """p.197's inbound half. The one thing `seedFromQuery` does not cover,
    because a page is not a variable."""
    page.goto(f"{WEB_BASE}{routed.url}?page=notes")
    preview = page.get_by_role("button", name="Preview", exact=True)
    expect(preview).to_be_visible(timeout=30000)
    preview.click()
    expect(page.get_by_label("Note", exact=True)).to_be_visible()


def test_a_link_naming_a_page_that_is_gone_opens_the_module(page, routed):
    """p.197: "users will be returned to the module's default page on page
    load". A link that outlived its page should open the module, not fail -
    and the URL should end up saying where the reader actually is."""
    page.goto(f"{WEB_BASE}{routed.url}?page=deleted")
    preview = page.get_by_role("button", name="Preview", exact=True)
    expect(preview).to_be_visible(timeout=30000)
    preview.click()
    expect(page.get_by_label("Region", exact=True)).to_be_visible()
    eventually(lambda: query(page).get("page"), lambda v: v == ["sites"],
               what="the URL corrected to the page actually on screen")
