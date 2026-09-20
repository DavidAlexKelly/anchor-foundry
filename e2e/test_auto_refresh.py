"""Auto-refresh (parity `workshop.md` §9; Foundry workshop p.576-580).

> "With auto-refresh, you can register object sets within a module to be
> watched for updates from anywhere in Foundry. When an update occurs, all data
> in the current module will automatically refresh without user interaction."
> (p.576)

The rules are `auto-refresh.test.ts` — the ten-second floor, what counts as a
change, what a background tab does — and the watermark is
`apps/api/tests/test_freshness.py`. **What needs a browser is the only thing
that makes it a feature**: a module on screen, a write made somewhere else
entirely, and the table changing without anybody touching it.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, settled

ROWS = [{"id": "R1", "name": "First"}, {"id": "R2", "name": "Second"}]
LATER = {"id": "R3", "name": "Third from elsewhere"}
#: The floor (p.577), so the test waits the shortest interval the product
#: allows rather than one invented here.
SECONDS = 10


def build(api, name: str, *, watching=True, seconds=SECONDS, in_edit=False):
    mod = Module(api, name)
    type_id = mod.object_type(columns=["id", "name"], rows=ROWS, key="id", title="name")
    mod.type_id = type_id
    definition = {
        "format": 2,
        "layout": layout({
            "tbl": {"resolvedName": "CanvasObjectTable",
                    "props": {"objectSetVariable": "v_all", "columns": "id,name",
                              "pageSize": 25}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All rows",
                      "object_set": object_set(type_id)},
        },
        "events": {},
    }
    if watching:
        definition["auto_refresh"] = {
            "enabled": True, "seconds": seconds,
            "disable_in_edit": not in_edit, "variables": ["v_all"],
        }
    mod.define(definition)
    return mod


def add_row(mod) -> None:
    """A write from outside the module, which is p.576's whole premise.

    A second source on the same type rather than a re-upload: `/upload` always
    creates a dataset and refuses a name it already has. This is the shape of
    p.576's "edits from an upstream data integration".
    """
    csv = f"id,name\n{LATER['id']},{LATER['name']}\n".encode()
    dataset = mod.api.upload_csv(
        f"{mod.base}/datasets/upload", f"later_{mod.tag}", csv,
    )
    source = mod.api.call(
        "POST", f"{mod.base}/object-type-sources",
        {"object_type_id": mod.type_id, "dataset_id": dataset["id"],
         "primary_key_column": "id", "column_mappings": {"name": "name"}},
    )
    mod.api.call("POST", f"{mod.base}/object-type-sources/{source['id']}/sync", {})


def rows(page):
    return page.locator(".canvas-block table tbody tr")


def test_a_write_from_elsewhere_reaches_the_module_on_its_own(page, api):
    """p.576's sentence, end to end, and the only claim that needs a browser.

    **Nobody touches the page.** No click, no reload, no navigation — the
    module is open, a row appears in the ontology from somewhere else, and the
    table grows. That is the difference between auto-refresh and a refresh
    button.
    """
    mod = build(api, "Auto refresh watch")
    open_module(page, mod)
    eventually(lambda: rows(page).count(), lambda n: n == len(ROWS),
               what="the module's rows before anything changes")

    add_row(mod)

    # Up to a few intervals: the poll is on p.577's floor and the first tick
    # after the write is the one that sees it.
    eventually(lambda: rows(page).count(), lambda n: n == len(ROWS) + 1,
               what="the new row arriving without user interaction",
               timeout_ms=(SECONDS + 20) * 1000)
    expect(page.get_by_text(LATER["name"], exact=True)).to_be_visible()


def test_a_module_that_registered_nothing_does_not_refresh(page, api):
    """The switch is not the feature — p.576 is "register object sets… to be
    watched", and with none registered there is nothing to ask about.

    **A negative held over time, not read once** (§318 in spirit): the claim is
    that it *stays* unchanged across the window the watching module refreshed
    in, so a single read taken a frame after the write would pass against a
    module that refreshed a second later.
    """
    mod = build(api, "Auto refresh unregistered", watching=False)
    open_module(page, mod)
    eventually(lambda: rows(page).count(), lambda n: n == len(ROWS),
               what="the module's rows")

    add_row(mod)
    page.wait_for_timeout((SECONDS + 5) * 1000)
    assert rows(page).count() == len(ROWS), "it refreshed without being asked to"
    expect(page.get_by_text(LATER["name"], exact=True)).to_have_count(0)


def test_the_builder_is_left_alone_by_default(page, api):
    """p.578's "Disable in edit mode": "A builder may wish to use this if
    auto-refreshing data in edit mode distracts from the building experience."

    Stored as on by default, so a module that switches auto-refresh on does not
    start reloading the canvas somebody is working in.
    """
    mod = build(api, "Auto refresh not in edit")
    open_builder(page, mod)
    settled(page)
    eventually(lambda: rows(page).count(), lambda n: n == len(ROWS),
               what="the builder's rows")

    add_row(mod)
    page.wait_for_timeout((SECONDS + 5) * 1000)
    assert rows(page).count() == len(ROWS), "the builder refreshed under the author"


def test_the_panel_writes_a_registration_that_takes_effect(page, api):
    """The chain a browser has to make: the settings panel, the saved document,
    and a module that then refreshes on its own."""
    mod = build(api, "Auto refresh panel", watching=False)
    open_builder(page, mod)
    settled(page)

    page.get_by_test_id("auto-refresh-toggle").check()
    page.get_by_test_id("auto-refresh-watch-v_all").check()
    # p.577's floor is the default, and the control refuses less.
    page.get_by_test_id("auto-refresh-seconds").fill("3")
    page.get_by_test_id("auto-refresh-seconds").blur()
    eventually(lambda: page.get_by_test_id("auto-refresh-seconds").input_value(),
               lambda v: int(v or 0) >= SECONDS,
               what="the ten-second floor to hold")

    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.locator(".ws-actions .sub")).to_contain_text("saved")

    open_module(page, mod)
    eventually(lambda: rows(page).count(), lambda n: n == len(ROWS),
               what="the viewer's rows")
    add_row(mod)
    eventually(lambda: rows(page).count(), lambda n: n == len(ROWS) + 1,
               what="the registration written in the panel taking effect",
               timeout_ms=(SECONDS + 20) * 1000)
