"""p.251's Searchable render hint, read by the applications that search
(§726; `object-link-types` p.251).

> "Searchable - Disable to improve reindex performance if the property will
> not be searched or sorted on in applications." (p.251)

That both stores leave such a property out of a free-text search, per type,
is `test_instance_store.py`; that the Object Dropdown leaves it out of what it
searches is `object-dropdown.test.ts`. What needs a browser is each
application asked the question somebody would type.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import WEB_BASE, open_module, settled
from test_object_dropdown import expect_titles, open_list

TAG = uuid.uuid4().hex[:6]
ROWS = [
    {"id": "L1", "name": f"Lantern {TAG}", "region": "north", "secret": f"Classified{TAG}"},
    {"id": "L2", "name": f"Beacon {TAG}", "region": "south", "secret": "public"},
]


@pytest.fixture(scope="module")
def lamps(api):
    mod = Module(api, "Searchable hint")
    mod.object_type_id = mod.object_type(
        columns=["id", "name", "region", "secret"], rows=ROWS, key="id", title="name",
        hints={"secret": ["keywords"]},
    )
    return mod


def test_the_explorer_does_not_search_it(page, lamps) -> None:
    page.goto(f"{WEB_BASE}/{lamps.workspace_slug}/explore?q=Lantern%20{TAG}")
    expect(page.locator("tbody tr")).to_have_count(1, timeout=30000)
    page.goto(f"{WEB_BASE}/{lamps.workspace_slug}/explore?q=Classified{TAG}")
    expect(page.get_by_text("Nothing matches that.")).to_be_visible(timeout=30000)


def test_the_object_dropdown_does_not_search_it(page, api, lamps) -> None:
    mod = Module(api, "Searchable hint dropdown", beside=lamps)
    mod.define({
        "format": 2,
        "layout": layout({
            "dd": {"resolvedName": "CanvasObjectDropdown",
                   "props": {"objectSetVariable": "v_set", "selectedVariable": "v_sel",
                             "label": "", "properties": "", "hideNull": False,
                             "sortProperty": "", "searchMode": "all",
                             "searchPropertyNames": "", "allowNoSelection": False}},
        }),
        "variables": {
            "v_set": {"id": "v_set", "kind": "object_set", "label": "Lamps",
                      "object_set": object_set(lamps.object_type_id)},
            "v_sel": {"id": "v_sel", "kind": "array", "label": "Chosen"},
        },
        "events": {},
    })
    open_module(page, mod)
    settled(page)
    open_list(page)
    # "Every string property" - and the region is one, and searched.
    page.get_by_test_id("dropdown-search").fill("south")
    expect_titles(page, [f"Beacon {TAG}"])
    # The secret is one too, and not searched.
    page.get_by_test_id("dropdown-search").fill(f"Classified{TAG}")
    expect(page.get_by_test_id("dropdown-option")).to_have_count(0)
