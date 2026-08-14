"""Saved module states (`foundry_workshop` p.200–206).

    "State saving … allows module consumers to store the current state of
    their work within a module and then either return to that saved state or
    share the saved state with other users." (p.200)

The API tests prove a state stores and restores the right values, and the
document tests prove which variables may be in one. What needs a browser is
the sentence those cannot make: **a reader filters, names what they are
looking at, comes back later and gets it** — through the same parameter
context a filter writes to, so a restored state cannot show something a live
interaction could not.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import WEB_BASE, eventually, open_module

COUNTS = {"north": 3, "south": 2}
TOTAL = sum(COUNTS.values())


def document(type_id: str, **settings) -> dict:
    return {
        "format": 2,
        "state_saving": {"enabled": True, **settings},
        "layout": layout(
            {
                "ctl": {
                    "resolvedName": "CanvasParameterControl",
                    "props": {"name": "v_region", "label": "Region", "control": "text"},
                },
                "tbl": {
                    "resolvedName": "CanvasObjectTable",
                    "props": {"objectSetVariable": "v_narrowed",
                              "columns": "id,region", "pageSize": 25},
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
                "external_id": "region", "save_state": True,
            },
            # Deliberately not saved: proves a state carries what the builder
            # chose rather than everything the reader touched.
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


def build(api, name: str, **settings) -> Module:
    rows = [
        {"id": f"{region[0].upper()}{i}", "region": region}
        for region, count in COUNTS.items()
        for i in range(1, count + 1)
    ]
    mod = Module(api, name)
    type_id = mod.object_type(columns=["id", "region"], rows=rows, key="id")
    mod.define(document(type_id, **settings))
    return mod


@pytest.fixture(scope="module")
def saving(api):
    return build(api, "Saving")


def rows(page) -> int:
    return page.locator(".canvas-block table tbody tr").count()


def type_region(page, value: str) -> None:
    box = page.get_by_label("Region", exact=True)
    box.fill(value)
    box.blur()


def save_as(page, name: str, *, called: str = "module state") -> None:
    box = page.get_by_label(f"Name this {called}", exact=True)
    box.fill(name)
    page.get_by_role("button", name="Save", exact=True).click()


def test_a_reader_saves_a_view_and_comes_back_to_it(page, saving):
    """p.200's first example, end to end: filter, name it, return to it. The
    reload is what makes this a *saved* state rather than a variable."""
    open_module(page, saving)
    eventually(lambda: rows(page), lambda n: n == TOTAL, what="every site")

    type_region(page, "north")
    eventually(lambda: rows(page), lambda n: n == COUNTS["north"],
               what="the filter narrowing the table")
    name = f"north-{uuid.uuid4().hex[:6]}"
    save_as(page, name)
    expect(page.get_by_test_id("state-note")).to_contain_text(name)

    # A fresh open: the filter is gone until the state is opened, which is what
    # makes the assertion afterwards mean something.
    open_module(page, saving)
    eventually(lambda: rows(page), lambda n: n == TOTAL, what="the unfiltered module")
    page.get_by_role("button", name=name, exact=True).click()
    eventually(lambda: rows(page), lambda n: n == COUNTS["north"],
               what="the saved view, restored")
    expect(page.get_by_label("Region", exact=True)).to_have_value("north")


def test_a_state_is_shared_rather_than_private(page, saving):
    """p.200's second sentence - "share the saved state with other users". The
    list is the module's, not the reader's, so a name saved once is a name
    everybody sees."""
    open_module(page, saving)
    name = f"shared-{uuid.uuid4().hex[:6]}"
    type_region(page, "south")
    save_as(page, name)
    eventually(lambda: page.get_by_role("button", name=name, exact=True).count(),
               lambda n: n == 1, what="the state in the list")

    open_module(page, saving)
    expect(page.get_by_role("button", name=name, exact=True)).to_be_visible()


def test_a_state_that_lost_a_value_says_so(page, api):
    """p.203: changing an external ID "may cause previously configured states
    to reload unsuccessfully". A view that came back short has to say which
    part is missing, or the reader believes they are looking at what they
    saved."""
    mod = build(api, "Renamed")
    open_module(page, mod)
    type_region(page, "north")
    eventually(lambda: rows(page), lambda n: n == COUNTS["north"], what="the filter")
    name = f"stale-{uuid.uuid4().hex[:6]}"
    save_as(page, name)
    eventually(lambda: page.get_by_test_id("state-note").count(), lambda n: n == 1,
               what="the save confirmation")

    # The external ID moves, which is exactly what p.203 warns about.
    rebuilt = mod.api.call(
        "GET", f"{mod.base}/canvas-apps/{mod.app_id}"
    )["definition"]
    rebuilt["variables"]["v_region"]["external_id"] = "where"
    mod.api.call(
        "PUT", f"{mod.base}/canvas-apps/{mod.app_id}/definition",
        {"definition": rebuilt, "version_description": "renamed the external id"},
    )

    open_module(page, mod)
    page.get_by_role("button", name=name, exact=True).click()
    expect(page.get_by_test_id("state-note")).to_contain_text("no longer")
    # And nothing was restored, rather than something wrong being restored.
    eventually(lambda: rows(page), lambda n: n == TOTAL, what="the unfiltered module")


def test_a_module_calls_its_states_whatever_its_readers_call_them(page, api):
    """p.204: "If set to a value of `inbox`, module consumers will see
    on-screen references to a saved inbox rather than a saved module state."
    Wording only, and it has to reach the control a reader actually uses."""
    mod = build(api, "Inboxes", display_name="inbox", display_name_plural="inboxes")
    open_module(page, mod)
    expect(page.get_by_label("Name this inbox", exact=True)).to_be_visible()
    expect(page.get_by_test_id("state-bar")).to_contain_text("inboxes")


def test_a_module_that_does_not_save_state_offers_nothing(page, api):
    """p.206's shape: with state saving off "module consumers will not see any
    state saving options". Not a disabled control - absent."""
    mod = build(api, "Plain")
    mod.define({**document(mod.object_type_id), "state_saving": {"enabled": False}})
    open_module(page, mod)
    eventually(lambda: rows(page), lambda n: n == TOTAL, what="the module rendering")
    expect(page.get_by_test_id("state-bar")).to_have_count(0)


def test_the_builder_is_not_offered_a_state_to_save(page, saving):
    """p.200 calls this a feature for "module consumers". In Edit mode there is
    no reading state worth naming, and a save bar there would invite an author
    to name the arrangement they are halfway through."""
    page.goto(f"{WEB_BASE}{saving.url}")
    expect(page.get_by_role("button", name="Preview", exact=True)).to_be_visible(
        timeout=30000
    )
    expect(page.get_by_test_id("state-bar")).to_have_count(0)
