"""A selection names its type where one widget picks objects of several (§692).

> "Timeline layers: Multiple timeline layers can be used to aggregate temporal
> data across multiple object types" … "Active object: outputs an object set
> of the currently selected object in the widget" (p.348–349)

> "each of the Flight Alert objects reference below is individually
> selectable by a user and will then become the output selected object set of
> the Markdown widget" (p.319)

Both widgets can show objects of two types, and two types' objects can share a
key. A selection that was only the key narrowed a set of either type to the
object with it - so picking Ada, a member of staff, also picked the site
Harbour, whose key is Ada's too. The picked object is read here through a
table over the union of both types (§686), which is where the two are told
apart.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_module

SITES = [{"id": "K1", "name": "Harbour", "seen": "2024-01-01"}]
STAFF = [{"id": "K1", "name": "Ada", "seen": "2024-02-01"},
         {"id": "K3", "name": "Grace", "seen": "2024-03-01"}]


@pytest.fixture(scope="module")
def shared(api):
    mod = Module(api, "Typed selections")
    tag = uuid.uuid4().hex[:8]
    mod.sites = mod.object_type(columns=["id", "name", "seen"], rows=SITES, key="id",
                                title="name", types={"seen": "date"}, slug=f"site_{tag}")
    mod.staff = mod.object_type(columns=["id", "name", "seen"], rows=STAFF, key="id",
                                title="name", types={"seen": "date"}, slug=f"staff_{tag}")
    mod.site_name, mod.staff_name = f"site_{tag}", f"staff_{tag}"
    return mod


def document(shared, widget: dict) -> dict:
    return {
        "format": 2,
        "layout": layout({
            "w": widget,
            "tbl": {"resolvedName": "CanvasObjectTable", "props": {
                "objectSetVariable": "v_shown", "columns": "name", "pageSize": 25,
                "sort": "key", "combineTypes": True, "autoSelect": False}},
        }),
        "variables": {
            "v_sites": {"id": "v_sites", "kind": "object_set", "label": "Sites",
                        "object_set": object_set(shared.sites)},
            "v_staff": {"id": "v_staff", "kind": "object_set", "label": "Staff",
                        "object_set": object_set(shared.staff)},
            "v_all": {"id": "v_all", "kind": "object_set", "label": "Everything",
                      "derivation": {"transform": "union_set", "inputs": ["v_sites", "v_staff"]}},
            "v_picked": {"id": "v_picked", "kind": "object_set_filter", "label": "Picked"},
            "v_shown": {"id": "v_shown", "kind": "object_set", "label": "Shown",
                        "derivation": {"transform": "narrow_set", "inputs": ["v_all", "v_picked"]}},
        },
        "events": {},
    }


def names(page) -> list[str]:
    return [c.strip() for c in page.locator(".data-grid tbody tr td:nth-child(2)")
            .all_text_contents()]


def test_a_timeline_event_is_its_own_object(api, page, shared) -> None:
    mod = Module(api, "Typed timeline", beside=shared)
    mod.define(document(shared, {"resolvedName": "CanvasTimeline", "props": {
        "layers": [{"label": "Sites", "objectSetVariable": "v_sites", "dateProperty": "seen"},
                   {"label": "Staff", "objectSetVariable": "v_staff", "dateProperty": "seen"}],
        "orientation": "vertical", "order": "oldest_first", "showLegend": True,
        "showGaps": False, "activeVariable": "v_picked", "highlightSelection": True,
        "pageSize": 50}}))
    open_module(page, mod)
    ada = page.locator("[data-testid=timeline-event][data-layer='1']",
                       has=page.get_by_test_id("timeline-mark-K1"))
    harbour = page.locator("[data-testid=timeline-event][data-layer='0']",
                           has=page.get_by_test_id("timeline-mark-K1"))
    ada.get_by_test_id("timeline-mark-K1").click()
    eventually(lambda: names(page), lambda got: got == ["Ada"], what="Ada alone")
    expect(ada).to_have_attribute("data-selected", "yes")
    expect(harbour).to_have_attribute("data-selected", "no")


def test_a_markdown_reference_is_its_own_object(api, page, shared) -> None:
    mod = Module(api, "Typed markdown", beside=shared)

    def ref(text: str, type_name: str) -> str:
        return f':objectreference[{text}]{{objectType="{type_name}" primaryKey="K1"}}'

    mod.define(document(shared, {"resolvedName": "CanvasMarkdown", "props": {
        "text": f"{ref('The harbour', shared.site_name)} and {ref('Ada', shared.staff_name)}.",
        "tagType": "inline_reference", "selectedVariable": "v_picked",
        "referenceTypes": [{"objectType": shared.site_name, "color": "#dc2626"},
                           {"objectType": shared.staff_name, "color": "#2563eb"}],
        "selectionBehavior": "selected"}}))
    open_module(page, mod)
    anchors = page.get_by_test_id("markdown-ref")
    expect(anchors).to_have_count(2, timeout=20000)
    anchors.filter(has_text="Ada").click()
    eventually(lambda: names(page), lambda got: got == ["Ada"], what="Ada alone")
    expect(anchors.filter(has_text="Ada")).to_have_attribute("aria-pressed", "true")
    expect(anchors.filter(has_text="The harbour")).to_have_attribute("aria-pressed", "false")
