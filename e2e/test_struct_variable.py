"""Workshop struct variables and p.143's Extract struct field (parity
`workshop.md` §3.2; Foundry `workshop` p.75, p.143, p.152–155).

> "Struct: Stores a composite type that maps string fieldIDs to values." (p.75)

> "Extract struct field: Returns a struct field value given a struct and field
> ID." (p.143)

> "Widgets and variable transformation operations cannot use structs as a
> whole, so individual struct fields must be extracted for use." (p.155)

Two things need a browser and the rest does not. The rules — what extracts to
what, what is empty, what is refused — are unit-tested in
`test_workshop_variables.py`, where a wrong answer is a line rather than a
screenshot.

What a browser is for is **the chain**: an object type declaring a struct
property (db 0064), a sync coercing the column into one, a click turning a row
into an object, `object_property` reading the struct off it, and
`extract_struct_field` turning that into text a widget draws. Each hop is
provable alone and none of them proves the module works.

And **the panel**: that the kind and the transform are offered at all, and that
what the builder produces is something the server accepts — a struct default
typed into a box has to arrive as an *object*, and a panel that sent the text
would fail on save with the dialog already closed.
"""
from __future__ import annotations

import json

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, settled

FIELDS = [
    {"api_name": "street", "display_name": "Street", "data_type": "string"},
    {"api_name": "postal_code", "display_name": "Postal code", "data_type": "string"},
]

SITES = [
    {"code": "A1", "name": "Aberdeen Yard",
     "address": json.dumps({"street": "12 Main St", "postal_code": "AB1 2CD"})},
    {"code": "B2", "name": "Bristol Depot",
     "address": json.dumps({"street": "9 Dock Road", "postal_code": "BS1 4XY"})},
]


@pytest.fixture(scope="module")
def module(api):
    mod = Module(api, "Struct variable")
    type_id = mod.object_type(
        columns=["code", "name", "address"],
        rows=SITES,
        key="code",
        title="name",
        types={"address": "struct"},
        struct_fields={"address": FIELDS},
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "tbl": {"resolvedName": "CanvasObjectTable",
                    "props": {"objectSetVariable": "v_all",
                              "columns": "code,name", "pageSize": 25}},
            "txt": {"resolvedName": "CanvasText",
                    "props": {"tag": "p", "text": "STREET={{v_street}}"}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All sites",
                      "object_set": object_set(type_id)},
            "v_picked": {"id": "v_picked", "kind": "single_object", "label": "Picked"},
            # p.152's second source: "using an object's struct property". It
            # needed nothing new — a struct property is a property, so
            # `object_property` already read one.
            "v_addr": {
                "id": "v_addr", "kind": "struct", "label": "Address",
                "derivation": {"transform": "object_property", "inputs": ["v_picked"],
                               "config": {"property": "address"}},
            },
            # p.155's only door out of a struct.
            "v_street": {
                "id": "v_street", "kind": "string", "label": "Street",
                "derivation": {"transform": "extract_struct_field", "inputs": ["v_addr"],
                               "config": {"field": "street"}},
            },
        },
        "events": {
            "e_row": {
                "id": "e_row", "trigger": {"node": "tbl", "on": "row_select"},
                "effects": [{"type": "set_variable",
                             "config": {"variable": "v_picked", "from": "object"}}],
            },
        },
    })
    return mod


def readout(page) -> str:
    return page.get_by_text("STREET=", exact=False).first.inner_text()


def test_a_struct_read_off_a_picked_object_reaches_a_widget(page, module):
    """The chain, and the second click is what makes it one.

    A single click could be satisfied by a widget showing a constant. Picking a
    *different* row is what says the value travelled: through
    `object_property`, through `extract_struct_field`, and onto the page.
    """
    open_module(page, module)
    settled(page)
    # Nothing picked yet, so there is nothing to extract — and that reads as
    # empty rather than as an error, which is `object_property`'s own rule.
    eventually(lambda: readout(page), lambda t: t == "STREET=",
               what="the readout before anything is picked")

    page.locator("table tbody tr").filter(has_text="Aberdeen Yard").first.click()
    eventually(lambda: readout(page), lambda t: t == "STREET=12 Main St",
               what="the street of the object picked")

    page.locator("table tbody tr").filter(has_text="Bristol Depot").first.click()
    eventually(lambda: readout(page), lambda t: t == "STREET=9 Dock Road",
               what="the street of the *other* object, so the value travelled")


def test_the_panel_offers_the_kind_and_the_transform_and_the_server_takes_it(
    page, api, module
):
    """§247's own half: the two mirrored lists reaching the builder.

    `KINDS` and `TRANSFORMS` are compared with the server's by a test that
    scans the panel, so what is left to prove here is the thing a scan cannot
    see — that a struct declared through these controls is **something the
    server accepts**. A struct default is the one default that is not a string,
    so a panel that sent the text somebody typed would produce a module that
    fails to save with the form already gone.
    """
    open_builder(page, module)
    page.get_by_role("button", name="Variables", exact=False).first.click()

    page.get_by_role("button", name="New", exact=True).click()
    page.locator(".vars-row").last.click()
    page.get_by_label("Label").fill("Typed address")
    page.get_by_label("Type", exact=True).select_option("struct")

    # p.152's first source — "initialized statically within Workshop".
    page.get_by_test_id("struct-default").fill('{"street": "1 Panel Way"}')
    expect(page.get_by_test_id("struct-default-problem")).to_have_count(0)

    # Waits for the *save*, not for a moment: the header prints "· saved".
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.locator(".ws-actions .sub")).to_contain_text("saved")
    eventually(
        lambda: [
            v for v in api.call(
                "GET", f"{module.base}/canvas-apps/{module.app_id}"
            )["definition"]["variables"].values()
            if v["label"] == "Typed address"
        ],
        lambda found: bool(found) and found[0]["default"] == {"street": "1 Panel Way"},
        what="the struct the panel saved, as an object rather than as its text",
    )


def test_a_default_that_is_not_a_struct_says_so_before_the_save(page, module):
    """The refusal that makes the box above safe to type in.

    Half-written JSON is the normal state of a box somebody is typing into, so
    it cannot clear the variable on every keystroke — it says what is wrong and
    leaves the last good value alone.
    """
    open_builder(page, module)
    page.get_by_role("button", name="Variables", exact=False).first.click()
    page.locator(".vars-row").filter(has_text="Typed address").first.click()

    page.get_by_test_id("struct-default").fill('{"street": ')
    expect(page.get_by_test_id("struct-default-problem")).to_contain_text("valid JSON")

    page.get_by_test_id("struct-default").fill('["a list"]')
    expect(page.get_by_test_id("struct-default-problem")).to_contain_text(
        "field names and values"
    )
