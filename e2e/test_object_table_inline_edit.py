"""The Object Table's inline edits (parity `workshop.md` §10; Foundry
`workshop` p.240–243).

> "Enabling inline editing allows module users to modify cell-level data
> displayed within the Object Table and then save these edits to objects data."
> (p.240)

> "After the above is configured, users can enter into editing mode with the
> Edit table button visible in the table footer… Once in edit mode, users can
> edit any modifiable column mapped to an action parameter… Any staged edits can
> be undone with the Undo button." (p.242)

> "Once you make your edits and are ready to submit your changes, you can press
> the Submit button… A confirmation dialog will appear where you will again
> press Submit." (p.243)

**What is here is the chain a unit test cannot reach**: a cell becomes a
control, typing into it stages an edit, Submit sends one batch, and the *object*
carries the new value afterwards. `inline-edit.test.ts` holds the arithmetic —
what may be staged, what Undo removes, what the request body is — and §238's API
tests hold the writing. This is the join.

Every assertion about a value reads it back through a **second, read-only
table** bound to the same set rather than out of the editor it was typed into: a
control showing what somebody typed is the control agreeing with itself, and the
question is whether the object changed.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, settled, stays

ROWS = [
    {"id": "T1", "status": "open", "note": "first"},
    {"id": "T2", "status": "open", "note": "second"},
    {"id": "T3", "status": "open", "note": "third"},
]


def make_action(api, mod, type_id, *, properties=("status",), extra=None):
    """An action that edits `properties` on this type, and nothing else — which
    is exactly what §238's `inline_edit_refusals` calls eligible."""
    action = api.call(
        "POST",
        f"/workspaces/{mod.workspace_id}/action-types",
        {
            "object_type_id": type_id,
            "api_name": f"inline_{uuid.uuid4().hex[:8]}",
            "display_name": "Edit ticket",
            "editable_properties": list(properties),
        },
    )
    if extra:
        api.call(
            "PUT",
            f"/workspaces/{mod.workspace_id}/action-types/{action['id']}/definition",
            extra,
        )
    return action


def build(api, name: str, *, table_props=None, properties=("status",), extra=None,
          rows=None):
    mod = Module(api, name)
    type_id = mod.object_type(
        columns=["id", "status", "note"], rows=rows or ROWS, key="id", title="id",
    )
    action = make_action(api, mod, type_id, properties=properties, extra=extra)
    mod.type_id = type_id
    mod.action = action
    mod.define({
        "format": 2,
        "layout": layout({
            "tbl": {
                "resolvedName": "CanvasObjectTable",
                "props": {
                    "objectSetVariable": "v_all", "columns": "status,note",
                    "pageSize": 25, "activeVariable": None, "autoSelect": False,
                    "inlineEditAction": action["id"],
                    "inlineEditMapping": {"status": "status"},
                    **(table_props or {}),
                },
            },
            # The read-only mirror every value assertion goes through.
            "mirror": {
                "resolvedName": "CanvasObjectTable",
                "props": {
                    "objectSetVariable": "v_all", "columns": "status",
                    "pageSize": 25, "activeVariable": None, "autoSelect": False,
                },
            },
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All tickets",
                      "object_set": object_set(type_id)},
        },
        "events": {},
    })
    return mod


def cell(page, key: str, prop: str):
    return page.get_by_test_id(f"edit-{key}-{prop}").locator("input, select")


def mirror_values(page):
    """The second table's status column, which is what the objects say."""
    grid = page.locator(".canvas-block > .data-grid").nth(1)
    return grid.locator("tbody tr td:nth-child(2)").all_inner_texts()


def test_a_configured_table_offers_edit_mode(page, api) -> None:
    """p.242's button, "visible in the table footer"."""
    mod = build(api, "Inline enter")
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("inline-edit-toggle")).to_have_text("Edit table")
    # Nothing is editable until it is pressed: p.242 makes edit mode a mode.
    expect(page.get_by_test_id("edit-T1-status")).to_have_count(0)

    page.get_by_test_id("inline-edit-toggle").click()
    expect(cell(page, "T1", "status")).to_be_visible()


def test_only_a_mapped_column_becomes_editable(page, api) -> None:
    """p.242: "users can edit **any modifiable column mapped to an action
    parameter**".

    `note` is a column of this table and not a parameter of this action, so it
    stays a value — which is the difference between an editable table and a
    table of editable cells.
    """
    mod = build(api, "Inline mapped")
    open_module(page, mod)
    settled(page)
    page.get_by_test_id("inline-edit-toggle").click()

    expect(cell(page, "T1", "status")).to_be_visible()
    expect(page.get_by_test_id("edit-T1-note")).to_have_count(0)


def test_an_edit_reaches_the_object_only_when_it_is_submitted(page, api) -> None:
    """p.242's staging and p.243's Submit, as one claim.

    **The `stays` half is the point.** A cell that wrote through on every
    keystroke would pass an assertion that the object changed *after* Submit;
    what tells the two apart is that the object does **not** change before it.
    """
    mod = build(api, "Inline submit")
    open_module(page, mod)
    settled(page)
    page.get_by_test_id("inline-edit-toggle").click()

    cell(page, "T1", "status").fill("triaged")
    # **The control keeps what was typed.** Without this, a cell pinned to the
    # stored value passes every other check in this file - `staged` is updated
    # either way, so the count is right and the submission is right, and the
    # only thing wrong is that the reader watches their own text disappear.
    expect(cell(page, "T1", "status")).to_have_value("triaged")
    expect(page.get_by_test_id("inline-edit-count")).to_have_text("1 row edited")
    stays(lambda: mirror_values(page),
          lambda v: "triaged" not in v,
          what="the object unchanged while the edit is only staged")

    page.get_by_test_id("inline-edit-submit").click()
    page.get_by_test_id("inline-edit-confirm-submit").click()
    eventually(lambda: mirror_values(page), lambda v: "triaged" in v,
               what="the submitted value on the object")


def test_undo_takes_the_row_out_of_the_submission(page, api) -> None:
    """p.242: "Any staged edits can be undone with the Undo button (as seen in
    the left-most column of the table)."

    Two rows edited and one undone, because undoing the only staged row would
    pass against an implementation that cleared everything.
    """
    mod = build(api, "Inline undo")
    open_module(page, mod)
    settled(page)
    page.get_by_test_id("inline-edit-toggle").click()

    cell(page, "T1", "status").fill("kept")
    cell(page, "T2", "status").fill("dropped")
    expect(page.get_by_test_id("inline-edit-count")).to_have_text("2 rows edited")

    page.get_by_test_id("undo-T2").click()
    expect(page.get_by_test_id("inline-edit-count")).to_have_text("1 row edited")
    # The undone row's control shows the object's value again, not the typed one.
    expect(cell(page, "T2", "status")).to_have_value("open")

    page.get_by_test_id("inline-edit-submit").click()
    page.get_by_test_id("inline-edit-confirm-submit").click()
    eventually(lambda: sorted(mirror_values(page)),
               lambda v: v == ["kept", "open", "open"],
               what="only the row that was not undone")


def test_undo_appears_only_for_a_row_that_was_edited(page, api) -> None:
    """A button on every row would say every row is staged, which is the one
    thing p.242's left-most column is for."""
    mod = build(api, "Inline undo shown")
    open_module(page, mod)
    settled(page)
    page.get_by_test_id("inline-edit-toggle").click()

    expect(page.get_by_test_id("undo-T1")).to_have_count(0)
    cell(page, "T1", "status").fill("x")
    expect(page.get_by_test_id("undo-T1")).to_be_visible()
    expect(page.get_by_test_id("undo-T2")).to_have_count(0)


def test_submit_asks_before_writing(page, api) -> None:
    """p.243's dialog, and that Cancel means it.

    Asserted through the object: a dialog that closed and submitted anyway
    would look identical on screen.
    """
    mod = build(api, "Inline confirm")
    open_module(page, mod)
    settled(page)
    page.get_by_test_id("inline-edit-toggle").click()
    cell(page, "T1", "status").fill("cancelled")

    page.get_by_test_id("inline-edit-submit").click()
    expect(page.get_by_test_id("inline-edit-confirm")).to_be_visible()
    page.get_by_role("button", name="Cancel").click()
    expect(page.get_by_test_id("inline-edit-confirm")).to_have_count(0)

    stays(lambda: mirror_values(page), lambda v: "cancelled" not in v,
          what="the object unchanged after the dialog was cancelled")
    # And the edit survives the cancellation - Cancel is not Undo.
    expect(page.get_by_test_id("inline-edit-count")).to_have_text("1 row edited")


def test_one_click_submit_skips_the_dialog(page, api) -> None:
    """p.243: "If you prefer to use a one-click submit option and would like to
    disable this confirmation dialog, you can enable the One-click submit
    toggle." """
    mod = build(api, "Inline one click",
                table_props={"inlineEditOneClick": True})
    open_module(page, mod)
    settled(page)
    page.get_by_test_id("inline-edit-toggle").click()
    cell(page, "T1", "status").fill("straight")

    page.get_by_test_id("inline-edit-submit").click()
    eventually(lambda: mirror_values(page), lambda v: "straight" in v,
               what="the value written without a dialog")


def test_submit_is_refused_until_something_is_edited(page, api) -> None:
    """An empty submission is a request the server refuses (§238), so offering
    it is offering a button that fails."""
    mod = build(api, "Inline empty")
    open_module(page, mod)
    settled(page)
    page.get_by_test_id("inline-edit-toggle").click()

    expect(page.get_by_test_id("inline-edit-submit")).to_be_disabled()
    cell(page, "T1", "status").fill("now")
    expect(page.get_by_test_id("inline-edit-submit")).to_be_enabled()


def test_the_table_can_open_in_edit_mode(page, api) -> None:
    """p.242: "You can also choose to have the table always be in inline editing
    mode by toggling on the Enable edit mode by default option."

    And the button still closes it, which is what `editing`'s three-state read
    exists for — a table that could only be opened would strand a reader who
    wanted to see their data plainly.
    """
    mod = build(api, "Inline default on",
                table_props={"inlineEditByDefault": True})
    open_module(page, mod)
    settled(page)

    expect(cell(page, "T1", "status")).to_be_visible()
    page.get_by_test_id("inline-edit-toggle").click()
    expect(page.get_by_test_id("edit-T1-status")).to_have_count(0)


def test_a_custom_button_text_is_used(page, api) -> None:
    """p.242's Custom button text."""
    mod = build(api, "Inline label",
                table_props={"inlineEditButtonText": "Correct these"})
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("inline-edit-toggle")).to_have_text("Correct these")


def test_an_action_the_server_refuses_draws_no_edit_mode(page, api) -> None:
    """§238's refusals, enforced where a builder can still be surprised by them.

    A table can be pointed at an action and the *action* changed afterwards —
    here it is created eligible and given a geopoint parameter, which p.241
    refuses. The submission would be refused either way; what this checks is
    that the table does not offer a mode whose Submit is going to fail.
    """
    mod = build(api, "Inline ineligible")
    api.call(
        "PUT",
        f"/workspaces/{mod.workspace_id}/action-types/{mod.action['id']}/definition",
        {
            "parameters": [
                {"api_name": "status", "display_name": "Status",
                 "data_type": "geopoint"},
            ],
            "rules": [
                {"kind": "modify_object",
                 "config": {"property": "status", "parameter": "status"}},
            ],
            "criteria": [],
        },
    )
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("inline-edit-footer")).to_have_count(0)


def test_a_refused_submission_says_so_and_keeps_the_edits(page, api) -> None:
    """p.138's all-or-nothing, as a reader experiences it.

    A criterion refuses one of the two staged rows. **Nothing is written** —
    including the row that would have passed — and the edits stay staged, since
    a submission that failed and cleared the form would lose work with nothing
    to show for it.
    """
    mod = build(api, "Inline refused")
    api.call(
        "PUT",
        f"/workspaces/{mod.workspace_id}/action-types/{mod.action['id']}/definition",
        {
            "parameters": [
                {"api_name": "status", "display_name": "Status", "data_type": "string"},
            ],
            "rules": [
                {"kind": "modify_object",
                 "config": {"property": "status", "parameter": "status"}},
            ],
            "criteria": [
                {"message": "that is not a status this workspace uses",
                 "config": {
                     "left": {"kind": "parameter", "parameter": "status"},
                     "operator": "is_included_in",
                     "right": {"kind": "value", "value": ["allowed"]},
                 }},
            ],
        },
    )
    open_module(page, mod)
    settled(page)
    page.get_by_test_id("inline-edit-toggle").click()
    cell(page, "T1", "status").fill("allowed")
    cell(page, "T2", "status").fill("refused")

    page.get_by_test_id("inline-edit-submit").click()
    page.get_by_test_id("inline-edit-confirm-submit").click()

    expect(page.get_by_test_id("inline-edit-error")).to_contain_text(
        "not a status this workspace uses"
    )
    expect(page.get_by_test_id("inline-edit-count")).to_have_text("2 rows edited")
    stays(lambda: mirror_values(page), lambda v: "allowed" not in v,
          what="the valid row unwritten because its neighbour was refused")


def test_leaving_edit_mode_discards_what_was_staged(page, api) -> None:
    """Edits behind a closed table are edits nobody can see or submit, so
    closing clears them — and the button says "Done" while open rather than the
    label that opened it, because pressing it is not entering edit mode."""
    mod = build(api, "Inline discard")
    open_module(page, mod)
    settled(page)
    page.get_by_test_id("inline-edit-toggle").click()
    expect(page.get_by_test_id("inline-edit-toggle")).to_have_text("Done")

    cell(page, "T1", "status").fill("gone")
    page.get_by_test_id("inline-edit-toggle").click()
    page.get_by_test_id("inline-edit-toggle").click()

    expect(page.get_by_test_id("inline-edit-count")).to_have_text("0 rows edited")
    expect(cell(page, "T1", "status")).to_have_value("open")


def test_the_builder_cannot_edit_rows(page, api) -> None:
    """Typing into a table on the canvas would edit somebody's objects while a
    module is being designed — §237's rule for the action form's file picker,
    one widget along."""
    mod = build(api, "Inline builder",
                table_props={"inlineEditByDefault": True})
    open_builder(page, mod)
    # **The anchor is a rendered row, not the block.** The footer is gated on
    # the rows having loaded, and `settled(page)` alone returns as soon as
    # `.canvas-block` is visible — so both assertions below passed against a
    # table that had not drawn yet, and a mutant deleting the `mode === "run"`
    # guard survived. `settled`'s own docstring names this trap: "every test
    # that asserts an absence waits for a presence first."
    settled(page, page.get_by_text("T1", exact=True).first)

    expect(page.get_by_test_id("inline-edit-footer")).to_have_count(0)
    expect(page.get_by_test_id("edit-T1-status")).to_have_count(0)


# ---- the panel (p.241) -------------------------------------------------------
def select_table(page):
    page.locator(".canvas-tree-row").filter(has_text="Object table").first.click()


def test_the_panel_offers_only_actions_the_server_accepts(page, api) -> None:
    """p.241's picker, and §214's rule about what a panel may offer.

    Two actions on one object type: one that edits a string property, and one
    that edits a geopoint — which p.241 refuses because a table cell cannot hold
    a struct. **The refused one is not in the list**, and the eligibility is the
    server's answer rather than a rule the panel re-derives.
    """
    mod = build(api, "Inline panel offers")
    refused = make_action(api, mod, mod.type_id, properties=["status"])
    api.call(
        "PUT",
        f"/workspaces/{mod.workspace_id}/action-types/{refused['id']}/definition",
        {
            "parameters": [
                {"api_name": "where", "display_name": "Where", "data_type": "geopoint"},
            ],
            "rules": [
                {"kind": "modify_object",
                 "config": {"property": "status", "parameter": "where"}},
            ],
            "criteria": [],
        },
    )
    open_builder(page, mod)
    settled(page)
    select_table(page)

    picker = page.get_by_test_id("inline-edit-action")
    expect(picker).to_be_visible()
    options = picker.locator("option").all_inner_texts()
    # "Off" plus the eligible action. The refused one shares its display name,
    # so the *count* is what tells them apart.
    assert len(options) == 2, options
    assert options[0] == "Off", options


def test_choosing_an_action_maps_the_matching_columns(page, api) -> None:
    """p.241: "action parameter IDs should match the property IDs displayed
    within the table. This will allow an automatic mapping."

    The mapping is seeded on choosing, not derived on every render — so this
    also proves a builder *could* change it, which a derived one would undo.
    """
    mod = build(api, "Inline panel map",
                table_props={"inlineEditAction": None, "inlineEditMapping": None})
    open_builder(page, mod)
    settled(page)
    select_table(page)

    expect(page.get_by_test_id("inline-edit-mapping")).to_have_count(0)
    page.get_by_test_id("inline-edit-action").select_option(mod.action["id"])

    mapped = page.get_by_test_id("inline-edit-mapping").locator(
        "[data-parameter='status']"
    )
    expect(mapped).to_have_value("status")


def test_a_type_with_no_usable_action_says_which_and_why(page, api) -> None:
    """"No actions" and "none that can do this" send a builder to two different
    places, so the block says which — and quotes the server's own sentence for
    the nearest miss rather than inventing one."""
    mod = build(api, "Inline panel none")
    api.call(
        "PUT",
        f"/workspaces/{mod.workspace_id}/action-types/{mod.action['id']}/definition",
        {
            "parameters": [
                {"api_name": "where", "display_name": "Where", "data_type": "geopoint"},
            ],
            "rules": [
                {"kind": "modify_object",
                 "config": {"property": "status", "parameter": "where"}},
            ],
            "criteria": [],
        },
    )
    open_builder(page, mod)
    settled(page)
    select_table(page)

    expect(page.get_by_test_id("inline-edit-none")).to_contain_text("geopoint")


def test_the_footer_settings_appear_only_once_an_action_is_chosen(page, api) -> None:
    """p.242's Custom button text and the two toggles configure a mode that does
    not exist until there is an action to run — §180's rule, that a control
    which cannot do anything must not be offered."""
    mod = build(api, "Inline panel footer",
                table_props={"inlineEditAction": None, "inlineEditMapping": None})
    open_builder(page, mod)
    settled(page)
    select_table(page)

    expect(page.get_by_text("Enable edit mode by default")).to_have_count(0)
    page.get_by_test_id("inline-edit-action").select_option(mod.action["id"])
    expect(page.get_by_text("Enable edit mode by default")).to_be_visible()
    expect(page.get_by_text("One-click submit")).to_be_visible()


def test_a_table_with_nothing_mapped_offers_no_edit_mode(page, api) -> None:
    """An action with no parameter pointed at a column is a mode with nothing in
    it: Edit table would open, and every cell would still be a value.

    **No fixture in this file reached this** until a mutant deleting the check
    survived — every other table here supplies a mapping, so "has an action" and
    "has an editable column" were the same condition throughout.
    """
    mod = build(api, "Inline unmapped",
                table_props={"inlineEditMapping": {}, "inlineEditByDefault": True})
    open_module(page, mod)
    settled(page, page.get_by_text("T1", exact=True).first)

    expect(page.get_by_test_id("inline-edit-footer")).to_have_count(0)
    # **And no undo column**, which is the half the footer's absence does not
    # cover: the footer is gated by its own expression, so a mutant deleting
    # this check from `inEditMode` left the footer hidden and put an empty
    # left-most column in every row. `inlineEditByDefault` is what makes the
    # mutant reachable at all - without it `editing` is false and the check
    # under test never decides anything.
    heads = page.locator(".canvas-block > .data-grid thead th")
    expect(heads.first).to_have_text("Key")


def test_typing_in_a_cell_does_not_change_the_active_row(page, api) -> None:
    """p.224's active object and p.242's editing, on one table.

    **A fixture that could not tell two implementations apart** until now: every
    other table in this file binds no `activeVariable` and wires no row events,
    so `rowsAreClickable` is false and there is no row handler for the cell's
    `stopPropagation` to stop — a mutant removing it changed nothing anywhere.
    Here the rows *are* clickable, so clicking into a cell to type would
    otherwise also select the row, and a reader correcting the third row would
    watch every widget downstream jump to it.
    """
    mod = Module(api, "Inline cell click")
    type_id = mod.object_type(
        columns=["id", "status", "note"], rows=ROWS, key="id", title="id",
    )
    action = make_action(api, mod, type_id)
    mod.define({
        "format": 2,
        "layout": layout({
            "tbl": {
                "resolvedName": "CanvasObjectTable",
                "props": {
                    "objectSetVariable": "v_all", "columns": "status,note",
                    "pageSize": 25, "activeVariable": "v_active",
                    "autoSelect": True,
                    "inlineEditAction": action["id"],
                    "inlineEditMapping": {"status": "status"},
                    "inlineEditByDefault": True,
                },
            },
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All",
                      "object_set": object_set(type_id)},
            "v_active": {"id": "v_active", "kind": "array", "label": "Active"},
        },
        "events": {},
    })
    open_module(page, mod)
    settled(page, page.get_by_text("T1", exact=True).first)

    # p.224's auto-selection puts the first row active; typing into the third
    # row's cell must leave it there.
    rows = page.locator("tbody tr")
    expect(rows.nth(0)).to_have_attribute("aria-current", "true")
    cell(page, "T3", "status").click()
    cell(page, "T3", "status").fill("typed")

    expect(page.get_by_test_id("inline-edit-count")).to_have_text("1 row edited")
    stays(lambda: rows.nth(0).get_attribute("aria-current"),
          lambda v: v == "true",
          what="the active row unchanged by typing in another row's cell")
