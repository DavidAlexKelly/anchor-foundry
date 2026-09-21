"""A picked object, carried in a link (§416; `workshop` p.199).

> "Object set variables are limited to single objects, specified by their RID"
> (p.199)

`object-ref.test.ts` decides the format, `routing.test.ts` decides what gets
written, and `apps/api/tests/test_routed_selection.py` decides what a reference
turns back into. What needs a browser is the loop none of them can close: click
a row, and the address bar can be handed to somebody else and show them the
same object.
"""
from __future__ import annotations

from urllib.parse import parse_qs

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import WEB_BASE, eventually, open_builder, open_module, select_node, settled

ROWS = [
    {"id": "S1", "name": "North Depot", "region": "north"},
    {"id": "S2", "name": "South Depot", "region": "south"},
]


@pytest.fixture(scope="module")
def routed(api):
    """A table whose row click writes a routed `single_object` variable, and a
    text widget that can only render what the object actually holds."""
    mod = Module(api, "Routed selection")
    type_id = mod.object_type(
        columns=["id", "name", "region"], rows=ROWS, key="id", title="name",
    )
    mod.type_id = type_id
    mod.define({
        "format": 2,
        "routing": {"enabled": True},
        "layout": layout({
            "tbl": {"resolvedName": "CanvasObjectTable",
                    "props": {"objectSetVariable": "v_all", "columns": "name,region",
                              "pageSize": 25}},
            "txt": {"resolvedName": "CanvasText",
                    "props": {"tag": "p", "text": "Picked: {{v_name}}"}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All sites",
                      "object_set": object_set(type_id)},
            "v_sel": {"id": "v_sel", "kind": "single_object", "label": "Picked site",
                      "external_id": "selected", "interface": True,
                      "url_behavior": "always"},
            "v_name": {"id": "v_name", "kind": "string", "label": "Picked name",
                       "derivation": {"transform": "object_property",
                                      "inputs": ["v_sel"],
                                      "config": {"property": "name"}}},
        },
        # How a picked object is actually written: a row click runs events with
        # the selection in context, and `set_variable` with `from: "object"`
        # puts it in the variable. The table's `activeVariable` is p.224's
        # *Active object* and carries narrowing clauses, not an object — wiring
        # this to that is what the first draft of this file did, and the server
        # refused it at resolve time with "reads a property of something that
        # is not an object", which is the document being wrong rather than the
        # product.
        "events": {
            "e_pick": {
                "id": "e_pick", "trigger": {"node": "tbl", "on": "row_select"},
                "effects": [{"type": "set_variable",
                             "config": {"variable": "v_sel", "from": "object"}}],
            },
        },
    })
    return mod


def query(page) -> dict[str, list[str]]:
    """Read out of the browser, not from `page.url` — routing writes with
    `replaceState`, which fires no navigation event for Playwright's cache."""
    return parse_qs(page.evaluate("location.search").lstrip("?"))


def picked_text(page) -> str:
    return page.locator(".canvas-block p").filter(has_text="Picked:").inner_text()


def click_row(page, name: str) -> None:
    page.locator(".canvas-block table tbody tr", has_text=name).first.click()


def test_clicking_a_row_puts_a_reference_in_the_address(page, routed) -> None:
    """p.199's RID, as an address bar. Two ids and nothing else — the row's
    name is on screen and must not be in the link."""
    open_module(page, routed)
    eventually(lambda: page.locator(".canvas-block table tbody tr").count(),
               lambda n: n == len(ROWS), what="the table's rows")
    click_row(page, "North Depot")
    eventually(lambda: query(page).get("selected", [""])[0],
               lambda v: v.startswith(routed.type_id),
               what="the selection, in the address")
    ref = query(page)["selected"][0]
    assert ":" in ref, ref
    # A reference, not a snapshot.
    assert "North" not in ref, ref
    assert "depot" not in ref.lower(), ref


def test_the_same_link_shows_the_same_object(page, routed) -> None:
    """**The loop this unit exists to close.** The address is handed over and
    the recipient sees the object — properties and all — which is only possible
    because the server read it back."""
    open_module(page, routed)
    eventually(lambda: page.locator(".canvas-block table tbody tr").count(),
               lambda n: n == len(ROWS), what="the table's rows")
    click_row(page, "South Depot")
    eventually(lambda: picked_text(page), lambda t: "South Depot" in t,
               what="the picked object's name")
    link = page.evaluate("location.pathname + location.search")

    page.goto(f"{WEB_BASE}{link}")
    settled(page)
    eventually(lambda: picked_text(page), lambda t: "South Depot" in t,
               what="the same object, restored from the link alone")


def test_a_link_naming_no_object_opens_the_module_anyway(page, routed) -> None:
    """A deleted object, or a hand-typed address. Nothing picked is the state
    the module is in before the first click, and the rest of the view still
    arrives — an error page would lose everything the link was shared for."""
    page.goto(f"{WEB_BASE}{routed.url}?selected=banana")
    settled(page)
    eventually(lambda: page.locator(".canvas-block table tbody tr").count(),
               lambda n: n == len(ROWS), what="the table, which still loads")
    assert "North" not in picked_text(page)
    assert "South" not in picked_text(page)


def test_the_builder_offers_the_url_setting_for_a_picked_object(page, routed) -> None:
    """The control opens off `ROUTABLE_KINDS`, so adding the kind to that list
    is what offers it — and a setting the server would refuse must not be
    offered (§214). This is the same list on both sides, seen from the panel."""
    open_builder(page, routed)
    page.get_by_role("button", name="Variables (3)", exact=True).click()
    page.get_by_text("Picked site", exact=True).click()
    control = page.get_by_test_id("variable-url-behavior")
    expect(control).to_be_visible()
    expect(control).to_be_enabled()
    expect(control).to_have_value("always")
