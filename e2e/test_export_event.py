"""p.489's Export event (parity `workshop.md` §3's effects table; §459).

> "Export events take an object set variable as an input and trigger the
> export of the objects in the object set to either Excel or the user's
> clipboard. An application builder may optionally configure a file name and
> select the set of properties that should be included in the export."
> (p.489)

What the file holds is `object-export.test.ts`; what the runner hands over is
`events.test.ts`; what the server accepts is `test_workshop_variables.py`.
**What needs a browser is the file arriving**: a real click, a real download
with a real name, and the clipboard holding what was exported - plus the
strip that says so, since a button that produced nothing looks exactly like
one that is broken.
"""
from __future__ import annotations

import uuid

from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import open_builder, open_module, save, settled

ROWS = [
    {"id": "S1", "region": "north", "name": "Alpha, the first"},
    {"id": "S2", "region": "north", "name": "=HYPERLINK(1)"},
    {"id": "S3", "region": "south", "name": "Charlie"},
]


def build(api, name: str, effect_config: dict) -> Module:
    mod = Module(api, name)
    tag = uuid.uuid4().hex[:8]
    type_id = mod.object_type(
        columns=["id", "region", "name"], rows=ROWS, key="id", title="name",
        slug=f"site_{tag}",
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "btn": {"resolvedName": "CanvasButton", "props": {"label": "Export"}},
        }),
        "variables": {
            "v_north": {"id": "v_north", "kind": "object_set", "label": "North",
                        "object_set": object_set(type_id, [
                            {"property": "region", "op": "eq", "value": "north"}])},
            # A set whose type only the server works out: the panel cannot
            # list its properties, and has to say so.
            "v_flag": {"id": "v_flag", "kind": "boolean", "label": "Flag", "default": True},
            "v_either": {"id": "v_either", "kind": "object_set", "label": "Either",
                         "derivation": {"transform": "if_else",
                                        "inputs": ["v_flag", "v_north", "v_north"]}},
        },
        "events": {
            "e_1": {"id": "e_1", "trigger": {"node": "btn", "on": "click"},
                    "effects": [{"type": "export",
                                 "config": {"variable": "v_north", **effect_config}}]},
        },
    })
    return mod


def status(page):
    return page.locator(".canvas-action-status")


def test_a_click_downloads_the_set_as_a_csv_file(page, api) -> None:
    """The set's objects and no others, the chosen properties in the chosen
    order after the key, and the file named as configured."""
    mod = build(api, "Export file", {"file_name": "north sites",
                                     "properties": ["name", "region"]})
    open_module(page, mod)

    with page.expect_download() as waiting:
        page.get_by_role("button", name="Export", exact=True).click()
    download = waiting.value
    assert download.suggested_filename == "north sites.csv"
    # `newline=""`: the file's own CRLFs, not Python's reading of them.
    with open(download.path(), encoding="utf-8", newline="") as handle:
        body = handle.read()
    assert body == (
        # The headers are the properties' display names, in the chosen order.
        "Key,Name,Region\r\n"
        'S1,"Alpha, the first",north\r\n'
        # Written as text, not as a formula a spreadsheet would run.
        "S2,'=HYPERLINK(1),north\r\n"
    ), body
    expect(status(page)).to_contain_text("Exported 2 objects to north sites.csv.")


def test_a_click_copies_the_set_to_the_clipboard(page, api) -> None:
    """p.489's other destination. Tab-separated, which is what a spreadsheet
    makes rows and columns of when it is pasted into one."""
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    mod = build(api, "Export clipboard", {"format": "clipboard", "properties": ["region"]})
    open_module(page, mod)

    page.get_by_role("button", name="Export", exact=True).click()
    expect(status(page)).to_contain_text("Copied 2 objects to the clipboard.")
    assert page.evaluate("() => navigator.clipboard.readText()") == (
        "Key\tRegion\nS1\tnorth\nS2\tnorth"
    )


def test_the_builder_configures_an_export(page, api) -> None:
    """The panel offers p.489's settings, lists the set's real properties to
    tick, and what it writes is what the server stores."""
    mod = build(api, "Export panel", {})
    open_builder(page, mod)
    settled(page)
    page.get_by_role("button", name="Events (1)").click()
    page.get_by_role("button", name="Button · Export Clicked · 1 effect").click()

    expect(page.get_by_test_id("effect-export-variable")).to_have_value("v_north")
    # The type is known from the set's own definition, so its properties are
    # offered to tick rather than typed.
    page.get_by_test_id("effect-export-property-region").check()
    page.get_by_test_id("effect-export-file-name").fill("regions")
    page.get_by_test_id("effect-export-format").select_option("csv")
    save(page)

    effect = mod.definition()["events"]["e_1"]["effects"][0]
    assert effect == {"type": "export", "config": {
        "variable": "v_north", "properties": ["region"], "file_name": "regions",
    }}, effect

    # Choosing the clipboard drops the file name field: a paste has no name.
    page.get_by_test_id("effect-export-format").select_option("clipboard")
    expect(page.get_by_test_id("effect-export-file-name")).to_have_count(0)

    # A set whose type the document cannot state: no list to tick, and a
    # sentence saying the export carries everything.
    expect(page.get_by_test_id("effect-export-properties-unknown")).to_have_count(0)
    page.get_by_test_id("effect-export-variable").select_option("v_either")
    expect(page.get_by_test_id("effect-export-properties-unknown")).to_be_visible()
    expect(page.get_by_test_id("effect-export-property-region")).to_have_count(0)
