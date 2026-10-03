"""The Inline Action's **Action table** layout (§702; Foundry `workshop` p.511-512).

> "Action tables … are recommended for large-scale datasets … The table layout
> offers several benefits, including keyboard navigation" (p.511)
> "End-user features: Configure additional user interactions, including layout
> switching, row management … Also note that batch call limits apply to the
> table layout, as well as the requirement that edits do not conflict." (p.512)

Which actions a table can draw is `apps/api/tests/test_action_table.py`, and
what a row lacks is `action-table.test.ts`. What needs a browser is the table
itself: a row per object, cells seeded from it, rows added and removed, every
row checked before any is sent, and the layout switch.

**Each test that writes gets its own module**, for `test_action_form.py`'s
reason.
"""
from __future__ import annotations

import uuid

from playwright.sync_api import expect

from api import Module, layout
from conftest import eventually, no_console_errors, open_module


def build(api, name: str, *, layout_switch: bool = False, props: dict | None = None,
          events: dict | None = None, variables: dict | None = None) -> Module:
    mod = Module(api, name)
    type_id = mod.object_type(
        columns=["ticket_id", "status"],
        rows=[{"ticket_id": k, "status": "open"} for k in ("T1", "T2", "T3")],
        key="ticket_id",
        title="ticket_id",
    )
    action = api.call("POST", f"/workspaces/{mod.workspace_id}/action-types", {
        "object_type_id": type_id,
        "api_name": f"set_{uuid.uuid4().hex[:8]}",
        "display_name": "Set status",
        "editable_properties": ["status"],
    })
    api.call("PUT", f"/workspaces/{mod.workspace_id}/action-types/{action['id']}/definition", {
        "parameters": [
            {"api_name": "status", "display_name": "Status", "data_type": "string",
             "required": True},
        ],
        "rules": [
            {"kind": "modify_object", "config": {"property": "status", "parameter": "status"}},
        ],
        "criteria": [
            {"message": "Tickets cannot be marked deleted.",
             "config": {"left": {"kind": "parameter", "parameter": "status"},
                        "operator": "is_not",
                        "right": {"kind": "value", "value": "deleted"}}},
        ],
    })
    mod.define({
        "format": 2,
        "layout": layout({
            "txt": {"resolvedName": "CanvasText",
                    "props": {"tag": "p", "text": "Fired: {{v_done}}"}},
            "frm": {"resolvedName": "CanvasActionForm",
                    "props": {"actionTypeId": action["id"], "layout": "table",
                              "layoutSwitch": layout_switch, **(props or {})}},
        }),
        "variables": {"v_done": {"id": "v_done", "kind": "string", "label": "Done"},
                      **(variables or {})},
        "events": events or {},
    })
    mod.type_id = type_id
    return mod


def statuses(api, mod: Module) -> dict[str, str]:
    items = api.call(
        "GET", f"/workspaces/{mod.workspace_id}/object-types/{mod.type_id}/instances"
    )["items"]
    return {i["primary_key"]: i["properties"]["status"] for i in items}


def rows(page):
    return page.get_by_test_id("action-table-row")


def fill_row(page, index: int, ticket: str, status: str) -> None:
    row = rows(page).nth(index)
    row.locator("select").first.select_option(label=ticket)
    cell = row.locator("[data-cell$=':1'] input")
    # Seeded from the object first (p.27), then typed over.
    expect(cell).to_have_value("open")
    cell.fill(status)


def test_each_row_is_one_object_and_starts_at_what_it_says(page, api) -> None:
    mod = build(api, "Action table seed")
    open_module(page, mod)
    expect(page.get_by_test_id("action-table")).to_be_visible()
    expect(rows(page)).to_have_count(1)
    rows(page).first.locator("select").first.select_option(label="T2")
    expect(rows(page).first.locator("[data-cell$=':1'] input")).to_have_value("open")
    page.get_by_test_id("action-table-add").click()
    expect(rows(page)).to_have_count(2)
    rows(page).nth(1).get_by_role("button", name="Remove row 2").click()
    expect(rows(page)).to_have_count(1)
    assert not no_console_errors(page)


def test_every_row_is_submitted(page, api) -> None:
    mod = build(api, "Action table submit")
    open_module(page, mod)
    fill_row(page, 0, "T1", "closed")
    page.get_by_test_id("action-table-add").click()
    fill_row(page, 1, "T2", "waiting")
    page.get_by_test_id("action-table-submit").click()
    expect(page.get_by_test_id("action-table-done")).to_have_count(2)
    eventually(lambda: statuses(api, mod),
               lambda got: got == {"T1": "closed", "T2": "waiting", "T3": "open"},
               what="both rows written, the third object untouched")
    expect(page.get_by_test_id("action-table-submit")).to_be_disabled()


def test_one_object_in_two_rows_sends_nothing(page, api) -> None:
    """p.512's "the requirement that edits do not conflict"."""
    mod = build(api, "Action table conflict")
    open_module(page, mod)
    fill_row(page, 0, "T1", "closed")
    page.get_by_test_id("action-table-add").click()
    fill_row(page, 1, "T1", "waiting")
    page.get_by_test_id("action-table-submit").click()
    expect(page.get_by_test_id("action-table-problem")).to_contain_text("also in row 1")
    assert statuses(api, mod)["T1"] == "open"


def test_a_refused_row_is_found_before_anything_is_written(page, api) -> None:
    """Every row's criteria are asked first, so a refusal in the second row
    leaves the first unwritten - and the message is the criterion's own (p.56)."""
    mod = build(api, "Action table refusal")
    open_module(page, mod)
    fill_row(page, 0, "T1", "closed")
    page.get_by_test_id("action-table-add").click()
    fill_row(page, 1, "T2", "deleted")
    page.get_by_test_id("action-table-submit").click()
    expect(page.get_by_test_id("action-table-problem")).to_contain_text(
        "Tickets cannot be marked deleted.")
    expect(page.get_by_test_id("action-table-done")).to_have_count(0)
    assert statuses(api, mod) == {"T1": "open", "T2": "open", "T3": "open"}

    # Fixed, and sent: both rows, since neither went the first time.
    rows(page).nth(1).locator("[data-cell$=':1'] input").fill("waiting")
    page.get_by_test_id("action-table-submit").click()
    expect(page.get_by_test_id("action-table-done")).to_have_count(2)


def test_a_required_cell_left_empty_is_named(page, api) -> None:
    mod = build(api, "Action table required")
    open_module(page, mod)
    fill_row(page, 0, "T1", "")
    page.get_by_test_id("action-table-submit").click()
    expect(page.get_by_test_id("action-table-problem")).to_contain_text("Status is required.")


def test_enter_moves_down_a_column(page, api) -> None:
    """p.511's keyboard navigation."""
    mod = build(api, "Action table keys")
    open_module(page, mod)
    page.get_by_test_id("action-table-add").click()
    first = rows(page).nth(0).locator("[data-cell$=':1'] input")
    first.focus()
    first.press("Enter")
    expect(rows(page).nth(1).locator("[data-cell$=':1'] input")).to_be_focused()
    rows(page).nth(1).locator("[data-cell$=':1'] input").press("Shift+Enter")
    expect(first).to_be_focused()


def test_a_reader_can_switch_layouts(page, api) -> None:
    """p.512's "layout switching", where the builder allowed it."""
    mod = build(api, "Action table switch", layout_switch=True)
    open_module(page, mod)
    switch = page.get_by_test_id("action-layout-switch")
    expect(page.get_by_test_id("action-table")).to_be_visible()
    switch.get_by_role("button", name="Form").click()
    expect(page.get_by_test_id("action-table")).to_have_count(0)
    expect(page.locator("form select").first).to_be_visible()
    switch.get_by_role("button", name="Table").click()
    expect(page.get_by_test_id("action-table")).to_be_visible()


def test_a_whole_batch_fires_the_submit_event(page, api) -> None:
    """p.513's "On successful action submit", once every row went through."""
    mod = build(api, "Action table event", events={
        "e_done": {"id": "e_done", "trigger": {"node": "frm", "on": "submit"},
                   "effects": [{"type": "set_variable",
                                "config": {"variable": "v_done", "value": "yes"}}]}})
    open_module(page, mod)
    expect(page.get_by_text("Fired:")).to_be_visible()
    fill_row(page, 0, "T3", "closed")
    page.get_by_test_id("action-table-submit").click()
    expect(page.get_by_test_id("action-table-done")).to_have_count(1)
    expect(page.get_by_text("Fired: yes")).to_be_visible()


def test_rows_pick_their_own_objects_when_the_form_is_bound(page, api) -> None:
    """The form edits the bound object; a table's rows are each about one, so
    the list of objects is still there to pick from."""
    mod = build(api, "Action table bound", props={"subjectVariable": "v_pick"},
                variables={"v_pick": {"id": "v_pick", "kind": "single_object",
                                      "label": "Picked"}})
    open_module(page, mod)
    expect(rows(page).first.locator("select").first.locator("option")).to_have_count(4)


def test_an_action_the_table_cannot_hold_is_a_form(page, api) -> None:
    """p.511: "some Actions … are not yet usable in the Table because some
    feature of the Action is only supported in the Form layout" - said, and the
    form drawn, since the action is still one somebody can submit."""
    mod = Module(api, "Action table refused")
    type_id = mod.object_type(
        columns=["site_id", "where"],
        rows=[{"site_id": "S1", "where": "51.5,-0.12"}],
        key="site_id", title="site_id", types={"where": "geopoint"},
    )
    action = api.call("POST", f"/workspaces/{mod.workspace_id}/action-types", {
        "object_type_id": type_id, "api_name": f"move_{uuid.uuid4().hex[:8]}",
        "display_name": "Move site", "editable_properties": ["where"],
    })
    mod.define({
        "format": 2,
        "layout": layout({"frm": {"resolvedName": "CanvasActionForm",
                                  "props": {"actionTypeId": action["id"], "layout": "table"}}}),
        "variables": {}, "events": {},
    })
    open_module(page, mod)
    expect(page.get_by_test_id("action-table-refused")).to_contain_text("geopoint")
    expect(page.get_by_test_id("action-table")).to_have_count(0)
    expect(page.locator("form")).to_be_visible()
