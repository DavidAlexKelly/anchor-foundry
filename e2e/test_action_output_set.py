"""p.513's **Output object set** on the Inline Action widget (parity
`workshop.md` §10).

> "Output object set: Specify the object set that will be created or modified
> when the Action is submitted." (p.513)

**The chain a unit test cannot reach**: an action writes, the executor reports
which objects it touched (§240), the widget turns that into clauses, a
`narrow_set` derivation turns those into a set, and a second widget shows it.
`action-output.test.ts` holds the browser's arithmetic and
`test_action_parameters.py` holds the executor's; this is the join.

Read through a **downstream table** rather than out of the form, because the
question is what the rest of the module receives — a form reporting its own
success is the form agreeing with itself.

    v_all      (object_set)  every ticket
    v_out      (array)       the clauses the form writes
    v_out_set  (object_set)  narrow_set(v_all, v_out) — what a reader sees
"""
from __future__ import annotations

import uuid

from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_module, settled

ROWS = [
    {"ticket_id": "T1", "status": "open"},
    {"ticket_id": "T2", "status": "open"},
    {"ticket_id": "T3", "status": "open"},
]


def build(api, name: str, *, bind_output: bool = True) -> Module:
    mod = Module(api, name)
    type_id = mod.object_type(
        columns=["ticket_id", "status"], rows=ROWS, key="ticket_id", title="ticket_id",
    )
    action = api.call(
        "POST",
        f"/workspaces/{mod.workspace_id}/action-types",
        {
            "object_type_id": type_id,
            "api_name": f"out_{uuid.uuid4().hex[:8]}",
            "display_name": "Set status",
            "editable_properties": ["status"],
        },
    )
    mod.type_id = type_id
    mod.action = action
    mod.define({
        "format": 2,
        "layout": layout({
            "form": {
                "resolvedName": "CanvasActionForm",
                "props": {
                    "actionTypeId": action["id"],
                    "subjectVariable": None,
                    "outputVariable": "v_out" if bind_output else None,
                },
            },
            # What the rest of the module receives.
            "out": {
                "resolvedName": "CanvasObjectTable",
                "props": {
                    "objectSetVariable": "v_out_set", "columns": "status",
                    "pageSize": 25, "activeVariable": None, "autoSelect": False,
                },
            },
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All tickets",
                      "object_set": object_set(type_id)},
            "v_out": {"id": "v_out", "kind": "array", "label": "Output clauses"},
            "v_out_set": {
                "id": "v_out_set", "kind": "object_set", "label": "What changed",
                "derivation": {"transform": "narrow_set", "inputs": ["v_all", "v_out"]},
            },
        },
        "events": {},
    })
    return mod


def downstream_keys(page):
    """The primary keys the output table is showing."""
    grid = page.locator(".canvas-block > .data-grid").nth(0)
    return grid.locator("tbody tr td:nth-child(1)").all_inner_texts()


def submit(page, key: str, status: str) -> None:
    page.locator("form select").select_option(label=key)
    page.get_by_label("New status").fill(status) if page.get_by_label(
        "New status"
    ).count() else page.locator('[data-parameter="status"] input').fill(status)
    page.get_by_role("button", name="Submit").click()
    expect(page.locator("text=Saved.")).to_be_visible()


def test_the_output_set_holds_the_object_the_submission_changed(page, api) -> None:
    """p.513's sentence, end to end.

    The set starts empty — nothing has been submitted — and holds exactly the
    edited ticket afterwards. **Three tickets, so "the one that changed" is a
    claim with something to be wrong about**: a widget writing every row, or the
    first row, passes a one-ticket fixture.
    """
    mod = build(api, "Output set")
    open_module(page, mod)
    settled(page)

    # **Empty rather than everything**, which is the rule the widget states on
    # load: no clauses would mean no narrowing, and a set describing "what
    # changed" must not start out holding every row.
    eventually(lambda: downstream_keys(page), lambda k: k == [],
               what="an empty output set before anything is submitted")

    submit(page, "T2", "triaged")
    eventually(lambda: downstream_keys(page), lambda k: k == ["T2"],
               what="only the submitted ticket in the output set")


def test_a_second_submission_replaces_the_first(page, api) -> None:
    """**The reason the widget writes even when it touched nothing**: an output
    set is what *this* submission produced, not everything the form has ever
    done. Leaving the previous clauses in place would have a reader acting on a
    row the last press of Submit did not touch.
    """
    mod = build(api, "Output replace")
    open_module(page, mod)
    settled(page)

    submit(page, "T1", "first")
    eventually(lambda: downstream_keys(page), lambda k: k == ["T1"],
               what="the first submission's object")

    submit(page, "T3", "second")
    eventually(lambda: downstream_keys(page), lambda k: k == ["T3"],
               what="the second submission's object, and only it")


def test_an_unbound_output_writes_nothing(page, api) -> None:
    """The setting is optional, and a form without it must not write to a
    variable it was never pointed at — the module's other widgets read that
    array too.

    **What "left alone" looks like is the whole point, and it is not empty.** A
    variable nothing has written holds no clauses, and no clauses means *no
    narrowing* — so the derived set is the base set, all three tickets. That is
    §207's rule, and it is why a *bound* form states the empty set on load
    rather than leaving the variable untouched: otherwise a module showing
    "what this submission changed" would show everything until the first
    submit.
    """
    mod = build(api, "Output unbound", bind_output=False)
    open_module(page, mod)
    settled(page)

    submit(page, "T1", "changed")
    eventually(lambda: sorted(downstream_keys(page)),
               lambda k: k == ["T1", "T2", "T3"],
               what="an unnarrowed set, because an unbound form wrote no clauses")


def test_the_panel_offers_the_array_variable(page, api) -> None:
    """§207's rule from the other side: what the widget writes is a clause list,
    so the variable to bind is the **array** in the middle. Offering the derived
    object set would invite binding the thing computed *from* this one and
    overwriting it on every submit.
    """
    from conftest import open_builder

    mod = build(api, "Output panel", bind_output=False)
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row").filter(has_text="Action form").first.click()

    picker = page.get_by_test_id("action-form-output")
    expect(picker).to_be_visible()
    options = picker.locator("option").all_inner_texts()
    assert "Output clauses" in options, options
    assert "What changed" not in options, options
