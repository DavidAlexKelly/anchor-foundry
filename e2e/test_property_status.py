"""A property's own status, and statuses where people read objects (§732;
`object-link-types` p.253-256).

> "Every object type, property, link type, action, or interface in the
> Ontology has a status… These statuses are viewable in Object Explorer,
> Object Views, and Workshop." (p.253)

A property's status was carried and propagated, and set nowhere one property
at a time (`test_statuses.py` set it through the API for that reason). The
cap the note predicts is `ontology-status.test.ts`'s; the propagation is the
server's (§170).
"""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import eventually
from test_object_type_editor_carry import open_type_editor
from test_standard_object_view import open_first_object

ROWS = [{"id": "Q1", "name": "Pump", "code": "P-1"},
        {"id": "Q2", "name": "Valve", "code": "V-2"}]


@pytest.fixture
def parts(api):
    mod = Module(api, "Property status")
    mod.object_type_id = mod.object_type(columns=["id", "name", "code"], rows=ROWS,
                                         key="id", title="name")
    return mod


def detail(api, mod) -> dict:
    return api.call("GET", f"/workspaces/{mod.workspace_id}/object-types/{mod.object_type_id}")


def names_of(page) -> list[str]:
    boxes = page.get_by_role("textbox", name=re.compile(r"^Property \d+ name$"))
    return [b.input_value() for b in boxes.all()]


def test_a_property_s_status_is_set_on_the_type_form(page, api, parts) -> None:
    open_type_editor(page, parts)
    row = names_of(page).index("code") + 1
    button = page.get_by_role("button", name=f"Property {row} status")
    expect(button).to_have_text("Experimental")
    button.click()
    dialog = page.locator("dialog.dialog").filter(has=page.get_by_role("heading", name="Status of code")).last
    options = dialog.get_by_test_id("status-select").locator("option")
    # p.255: promoted is an object type's alone.
    expect(options).to_have_text(["Deprecated", "Example", "Experimental", "Active"])
    # p.256: no more ready than its type, and said before saving.
    dialog.get_by_test_id("status-select").select_option("active")
    expect(dialog.get_by_test_id("property-status-capped")).to_contain_text(
        "Saved as Experimental")
    dialog.get_by_test_id("status-select").select_option("deprecated")
    expect(dialog.get_by_test_id("property-status-capped")).to_have_count(0)
    dialog.get_by_test_id("deprecation-reason").fill("Replaced by the serial")
    dialog.get_by_role("button", name="Done").click()
    expect(button).to_have_text("Deprecated")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    eventually(lambda: {p["api_name"]: (p["status"], (p.get("deprecation") or {}).get("reason"))
                        for p in detail(api, parts)["properties"]}["code"],
               lambda got: got == ("deprecated", "Replaced by the serial"),
               what="the property's status and note saved")


def test_statuses_show_in_the_explorer_and_the_object_view(page, api, parts) -> None:
    """p.253's "viewable in Object Explorer, Object Views": the type's in the
    Explorer's list and the view's header, a property's beside its name, and
    a deprecated one's note in the tooltip."""
    got = detail(api, parts)
    properties = [{k: p[k] for k in ("api_name", "data_type", "status")}
                  | ({"status": "deprecated", "deprecation": {"reason": "Replaced by the serial"}}
                     if p["api_name"] == "code" else {})
                  for p in got["properties"]]
    api.call("PATCH", f"/workspaces/{parts.workspace_id}/object-types/{parts.object_type_id}",
             {"display_name": got["display_name"], "properties": properties,
              "title_property": "name", "status": "active"})
    open_first_object(page, parts)
    head = page.locator(".sov-type")
    expect(head.get_by_test_id("status-badge-active")).to_be_visible()
    code = page.get_by_test_id("sov-normal").locator("[data-property='code'] th")
    badge = code.get_by_test_id("status-badge-deprecated")
    expect(badge).to_have_attribute("title", "Replaced by the serial")
    # Experimental is the default and draws nothing.
    expect(page.get_by_test_id("sov-normal").locator(
        "[data-property='name'] [data-testid^='status-badge']")).to_have_count(0)
    # And in the Explorer's list of types.
    expect(page.get_by_test_id(f"type-mark-{parts.object_type_id}").locator(
        "xpath=..").get_by_test_id("status-badge-active")).to_be_visible()


def test_the_cap_follows_the_type_s_status_on_the_form(page, api, parts) -> None:
    """The note reads the type's status as the form holds it, not as saved:
    raising the type above the property clears it before anything is sent."""
    open_type_editor(page, parts)
    row = names_of(page).index("code") + 1
    page.get_by_test_id("status-select").first.select_option("active")
    page.get_by_role("button", name=f"Property {row} status").click()
    dialog = page.locator("dialog.dialog").filter(
        has=page.get_by_role("heading", name="Status of code")).last
    dialog.get_by_test_id("status-select").select_option("active")
    expect(dialog.get_by_test_id("property-status-capped")).to_have_count(0)


def test_moving_off_deprecated_drops_the_note(page, api, parts) -> None:
    """p.254's note belongs to a deprecated resource, and the server refuses
    it on anything else - so choosing another status clears it, and the save
    goes through."""
    open_type_editor(page, parts)
    row = names_of(page).index("code") + 1
    page.get_by_role("button", name=f"Property {row} status").click()
    dialog = page.locator("dialog.dialog").filter(
        has=page.get_by_role("heading", name="Status of code")).last
    dialog.get_by_test_id("status-select").select_option("deprecated")
    dialog.get_by_test_id("deprecation-reason").fill("Second thoughts")
    dialog.get_by_test_id("status-select").select_option("example")
    dialog.get_by_role("button", name="Done").click()
    with page.expect_response(
        lambda r: "/object-types/" in r.url and r.request.method == "PATCH"
    ) as saved:
        page.get_by_role("button", name="Save", exact=True).click()
    assert saved.value.ok, saved.value.text()
    code = next(p for p in detail(api, parts)["properties"] if p["api_name"] == "code")
    assert (code["status"], code.get("deprecation")) == ("example", None)
