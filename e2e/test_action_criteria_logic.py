"""p.56's logical operators in the action editor (§643).

> "A logical operator can be used to combine different conditions. Logical
> operators can also be nested to create even more complex logic and can
> require either all, any, or no conditions underneath it to be met to pass."
> (p.56)

A criterion typed in the dialog as "any of: status is open, or none of:
status is closed" is saved as a group holding a group, and the server's own
check (`/check`) then answers by it: a ticket being set to "open" or to
"triaged" may be, and one being set to "closed" is refused with the root's
message.
"""
from __future__ import annotations

from playwright.sync_api import expect

from test_action_definition_editor import build, definition, open_editor

MESSAGE = "Tickets are not closed from here."


def cond(value: str, operator: str = "is") -> dict:
    return {"left": {"kind": "parameter", "parameter": "status"}, "operator": operator,
            "right": {"kind": "value", "value": value}}


def check(api, mod, status: str) -> dict:
    return api.call(
        "POST",
        f"/workspaces/{mod.workspace_id}/projects/{mod.project_id}/actions/{mod.action['id']}/check",
        {"values": {"status": status}},
    )


def test_a_criterion_typed_as_nested_groups_saves_and_decides(page, api) -> None:
    mod = build(api, "Criteria logic")
    open_editor(page, mod)
    page.get_by_role("button", name="Add a criterion").click()
    page.get_by_label("Criterion 1 message").fill(MESSAGE)
    page.get_by_label("Criterion 1 parameter").select_option("status")
    page.get_by_label("Criterion 1 operator").select_option("is")
    page.get_by_label("Criterion 1 value").fill("open")

    # The lone condition becomes the first of a group, and the group an "any".
    page.get_by_label("Criterion 1 combine").click()
    expect(page.get_by_label("Criterion 1 combine")).to_have_count(0)
    page.get_by_label("Criterion 1 logic").select_option("any")
    expect(page.get_by_label("Criterion 1.1 value")).to_have_value("open")

    # A group inside it: none of "status is closed".
    page.get_by_label("Criterion 1 add group").click()
    page.get_by_label("Criterion 1.2 logic").select_option("none")
    page.get_by_label("Criterion 1.2.1 parameter").select_option("status")
    page.get_by_label("Criterion 1.2.1 operator").select_option("is")
    page.get_by_label("Criterion 1.2.1 value").fill("closed")

    # A third condition, added and then taken out again.
    page.get_by_label("Criterion 1 add condition").click()
    expect(page.get_by_label("Criterion 1.3 parameter")).to_be_visible()
    page.get_by_label("Remove Criterion 1.3").click()
    expect(page.get_by_label("Criterion 1.3 parameter")).to_have_count(0)

    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    [stored] = definition(api, mod)["criteria"]
    assert stored["message"] == MESSAGE
    assert stored["config"] == {"logic": "any", "conditions": [
        cond("open"), {"logic": "none", "conditions": [cond("closed")]},
    ]}
    assert check(api, mod, "open") == {"ok": True, "error": None}
    assert check(api, mod, "triaged") == {"ok": True, "error": None}
    assert check(api, mod, "closed") == {"ok": False, "error": MESSAGE}


def test_the_editor_reads_a_nested_criterion_back(page, api) -> None:
    mod = build(api, "Criteria logic read")
    stored = definition(api, mod)
    api.call("PUT", f"/workspaces/{mod.workspace_id}/action-types/{mod.action['id']}/definition", {
        "parameters": stored["parameters"], "rules": stored["rules"],
        "criteria": [{"message": MESSAGE, "config": {"logic": "all", "conditions": [
            cond("x", "is_not"), {"logic": "any", "conditions": [cond("a"), cond("b")]}]}}],
    })
    open_editor(page, mod)
    expect(page.get_by_label("Criterion 1 logic")).to_have_value("all")
    expect(page.get_by_label("Criterion 1.1 operator")).to_have_value("is_not")
    expect(page.get_by_label("Criterion 1.2 logic")).to_have_value("any")
    expect(page.get_by_label("Criterion 1.2.2 value")).to_have_value("b")


def test_a_renamed_parameter_is_renamed_inside_the_groups(page, api) -> None:
    """A condition deep in a group names the parameter as a flat one does, and
    a rename in the dialog reaches it; otherwise the save is refused over a
    condition the person never touched."""
    mod = build(api, "Criteria logic rename")
    stored = definition(api, mod)
    api.call("PUT", f"/workspaces/{mod.workspace_id}/action-types/{mod.action['id']}/definition", {
        "parameters": stored["parameters"], "rules": stored["rules"],
        "criteria": [{"message": MESSAGE, "config": {"logic": "all", "conditions": [
            {"logic": "none", "conditions": [cond("closed")]}]}}],
    })
    open_editor(page, mod)
    page.get_by_label("Parameter 1 name").fill("new_status")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    [criterion] = definition(api, mod)["criteria"]
    inner = criterion["config"]["conditions"][0]["conditions"][0]
    assert inner["left"] == {"kind": "parameter", "parameter": "new_status"}
