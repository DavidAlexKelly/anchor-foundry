"""p.181's display optimization, not supported in loop layouts (§679).

> "Note that display optimization settings are not supported in loop
> layouts." (p.181)

A card module whose text is set to Delay until on-screen and Unmount when
off-screen, looped once per site: every copy takes p.182's defaults, while the
same settings on a widget of the host itself still apply. What the defaults
are, and that a loop takes them, is `display-optimization.test.ts`.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import open_module

OPTIMISED = {"display": {"mode": "auto", "mount": "on_screen", "unmount": "off_screen"}}


@pytest.fixture(scope="module")
def host(api):
    card = Module(api, "Loop display card")
    type_id = card.object_type(columns=["id", "name"], rows=[{"id": "S1", "name": "Alpha"},
                                                           {"id": "S2", "name": "Bravo"}],
                               key="id", title="name")
    card.define({
        "format": 2,
        "layout": layout({"txt": {"resolvedName": "CanvasText", "props": {"tag": "p", "text": "CARD {{v_name}}"},
                                  "custom": OPTIMISED}}),
        "variables": {
            "v_obj": {"id": "v_obj", "kind": "single_object", "label": "The object", "external_id": "obj",
                      "interface": {"display_name": "Object", "required": True}},
            "v_name": {"id": "v_name", "kind": "string", "label": "Name",
                       "derivation": {"transform": "object_property", "inputs": ["v_obj"],
                                      "config": {"property": "name"}}},
        },
        "events": {},
    })
    mod = Module(api, "Loop display host", beside=card)
    mod.define({
        "format": 2,
        "layout": layout({
            "own": {"resolvedName": "CanvasText", "props": {"tag": "p", "text": "HOST OWN"}, "custom": OPTIMISED},
            "loop": {"resolvedName": "CanvasLoopSection",
                     "props": {"objectSetVariable": "v_all", "moduleId": card.app_id, "itemVariable": "obj",
                               "paging": "limit", "maxItems": 12, "display": "list"}},
        }),
        "variables": {"v_all": {"id": "v_all", "kind": "object_set", "label": "All sites",
                                "object_set": object_set(type_id)}},
        "events": {},
    })
    return mod


def test_a_looped_module_s_widgets_take_the_defaults(page, host) -> None:
    open_module(page, host)
    items = page.locator(".canvas-loop-item")
    expect(items).to_have_count(2, timeout=30000)
    expect(page.get_by_text("CARD Alpha")).to_be_visible()
    expect(page.get_by_text("CARD Bravo")).to_be_visible()
    # Inside the loop, nothing is optimised.
    expect(items.locator("[data-mount]")).to_have_count(0)
    # The host's own widget keeps its settings.
    own = page.locator("[data-mount]").filter(has_text="HOST OWN")
    expect(own).to_have_attribute("data-mount", "on_screen")
    expect(own).to_have_attribute("data-unmount", "off_screen")
