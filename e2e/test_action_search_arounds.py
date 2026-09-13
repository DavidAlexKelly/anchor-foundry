"""Where an object dropdown's objects come from, on the screen (§333;
`action-types` p.34, p.36-37).

    "A Search Around would create a new set by traversing a link on every
     object in the current set. For example, `Github Issue of Current Employee`
     would take the `Employees` in the current set and create a resulting set
     of `Github Issues` linked to those `Employees`." (p.37)

The walk and its refusals are tested in
`apps/api/tests/test_action_search_arounds.py`, and the panel's wording in
`apps/web/src/lib/action-search-arounds.test.ts`. What needs a browser is
p.37's example being *used*:

**choose an employee in one box and the next box offers their issues.**

That is the whole of "of Current Employee", and it is the only place where the
form's narrowing, the server's walk and the submission's refusal have to agree
while somebody is filling a form in.
"""
from __future__ import annotations

import json
import uuid

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import WEB_BASE, open_module, settled

EMPLOYEES = [{"id": "E1", "name": "Ada"}, {"id": "E2", "name": "Grace"}]
# Two each, so "Ada's issues" and "every issue" are different lists — with one
# apiece a walk that ignored its starting object would look like it worked.
ISSUES = [
    {"id": "I1", "employee_id": "E1", "title": "Ada one"},
    {"id": "I2", "employee_id": "E1", "title": "Ada two"},
    {"id": "I3", "employee_id": "E2", "title": "Grace one"},
    {"id": "I4", "employee_id": "E2", "title": "Grace two"},
]


@pytest.fixture(scope="module")
def world(api):
    """p.37's example, on a canvas: an Assign form whose Issue dropdown walks
    from the Employee chosen above it."""
    mod = Module(api, "Search around")
    tag = uuid.uuid4().hex[:8]
    employee_type = mod.object_type(
        columns=["id", "name"], rows=EMPLOYEES, key="id", title="name",
        slug=f"emp_{tag}",
    )
    issue_type = mod.object_type(
        columns=["id", "employee_id", "title"], rows=ISSUES, key="id",
        title="title", slug=f"iss_{tag}",
    )
    ticket_type = mod.object_type(
        columns=["id", "note"], rows=[{"id": "T1", "note": ""}], key="id",
        title="id", slug=f"tkt_{tag}",
    )
    link = api.call(
        "POST", f"/workspaces/{mod.workspace_id}/link-types",
        {"api_name": f"raised_by_{tag}", "display_name": "Raised by",
         "from_type_id": issue_type, "to_type_id": employee_type,
         "cardinality": "one_to_many",
         "from_property": "employee_id", "to_property": "$primary_key"},
    )
    action = api.call(
        "POST", f"/workspaces/{mod.workspace_id}/action-types",
        {"object_type_id": ticket_type, "api_name": f"assign_{tag}",
         "display_name": "Assign ticket", "editable_properties": ["note"]},
    )
    api.call(
        "PUT",
        f"/workspaces/{mod.workspace_id}/action-types/{action['id']}/definition",
        {"parameters": [
             {"api_name": "who", "display_name": "Employee",
              "data_type": "object", "object_type_id": employee_type},
             {"api_name": "issue", "display_name": "Issue",
              "data_type": "object", "object_type_id": issue_type,
              "dropdown_search_around": {
                  "start": {"kind": "parameter",
                            "object_type_id": employee_type,
                            "parameter": "who"},
                  "hops": [{"link_type_id": link["id"]}]}},
         ],
         "rules": [{"kind": "modify_object",
                    "config": {"property": "note", "parameter": "issue"}}],
         "criteria": []},
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "txt": {"resolvedName": "CanvasText",
                    "props": {"tag": "p", "text": "WALKED FORM"}},
            "frm": {"resolvedName": "CanvasActionForm",
                    "props": {"actionTypeId": action["id"]}},
        }),
        "variables": {},
        "events": {},
    })
    mod.type_id = ticket_type
    mod.employee_type = employee_type
    mod.issue_type = issue_type
    mod.action = action
    mod.link = link
    return mod


def picker(page, name: str):
    return page.locator(f"[data-parameter='{name}'] select")


def options(page, name: str) -> list[str]:
    return [t.strip() for t in picker(page, name).locator("option").all_inner_texts()]


def choose_the_ticket(page) -> None:
    page.locator("form > label select").first.select_option(index=1)
    expect(picker(page, "who")).to_have_count(1)


def choose(page, name: str, label: str) -> None:
    picker(page, name).select_option(label=label)


def test_choosing_an_employee_offers_their_issues(page, world):
    """**p.37's example, end to end, which is why this file exists.**

    Both halves: Ada's issues are offered and Grace's are not. The first alone
    would pass for a dropdown that ignored the walk entirely.
    """
    open_module(page, world)
    choose_the_ticket(page)
    choose(page, "who", "Ada")
    expect(picker(page, "issue").locator("option")).to_contain_text(
        ["Choose", "Ada one", "Ada two"], timeout=30000
    )
    shown = options(page, "issue")
    assert not any("Grace" in o for o in shown), shown


def test_changing_the_employee_changes_the_issues(page, world):
    """A dropdown that walked once and then stopped listening passes the test
    above and fails this one."""
    open_module(page, world)
    choose_the_ticket(page)
    choose(page, "who", "Ada")
    expect(picker(page, "issue").locator("option")).to_contain_text(
        ["Choose", "Ada one", "Ada two"], timeout=30000
    )
    choose(page, "who", "Grace")
    expect(picker(page, "issue").locator("option")).to_contain_text(
        ["Choose", "Grace one", "Grace two"], timeout=30000
    )
    assert not any("Ada" in o for o in options(page, "issue"))


def test_before_an_employee_is_chosen_the_issues_say_which_box_comes_first(
    page, world
):
    """§214, and a sentence that would otherwise be simply false: "there are no
    Issues" when the truth is "you have not said whose"."""
    open_module(page, world)
    choose_the_ticket(page)
    expect(page.get_by_test_id("choices-waiting")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("choices-waiting")).to_contain_text("Employee")
    expect(page.get_by_test_id("choices-empty")).to_have_count(0)


def test_a_walked_submission_carries_the_object_that_was_offered(page, api, world):
    """p.34's two sentences agreeing while somebody submits. A form that
    offered Ada's issues and then sent something the server refuses would be
    the same defect from the other side."""
    sent: list[str] = []
    page.on("request", lambda r: sent.append(r.post_data or "")
            if "/execute" in r.url else None)
    open_module(page, world)
    choose_the_ticket(page)
    choose(page, "who", "Ada")
    expect(picker(page, "issue").locator("option")).to_contain_text(
        ["Choose", "Ada one"], timeout=30000
    )
    choose(page, "issue", "Ada one")
    page.get_by_role("button", name="Submit").click()
    expect(page.locator("form")).to_contain_text("Saved.")

    # And the object it sent is the one the walk reached, watched on the request
    # for the reason §330's docstring gives about the run log.
    assert len(sent) == 1, sent
    issues = api.call(
        "GET",
        f"/workspaces/{world.workspace_id}/object-types/{world.issue_type}/instances",
    )["items"]
    ada_one = next(i for i in issues if i["properties"]["title"] == "Ada one")
    assert json.loads(sent[0])["values"]["issue"] == ada_one["id"]


def test_the_walk_works_for_somebody_who_may_not_edit_the_action(viewer_page, world):
    """§332's rule with §333's second rule under it.

    The walk is redacted (p.40-41) and the parameter it reads is not, so a
    reader's form still knows to re-ask when the employee changes. Without the
    watch list this is the §331 defect again, in a feature written after it.
    """
    viewer_page.goto(f"{WEB_BASE}{world.url}")
    settled(viewer_page)
    choose_the_ticket(viewer_page)
    choose(viewer_page, "who", "Grace")
    expect(picker(viewer_page, "issue").locator("option")).to_contain_text(
        ["Choose", "Grace one", "Grace two"], timeout=30000
    )
    assert not any("Ada" in o for o in options(viewer_page, "issue"))


# ---- the editor's panel ---------------------------------------------------------
def open_editor(page, mod: Module) -> None:
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/objects")
    row = page.locator("tr", has_text=mod.action["api_name"])
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Parameters").click()
    expect(page.get_by_role("dialog")).to_be_visible()


def test_the_panel_says_where_the_dropdown_starts(page, world):
    """The sentence rather than the shape: somebody checking their own work
    should not have to read a link id out of a select."""
    open_editor(page, world)
    panel = page.locator(f"[data-parameter-search-around='issue']")
    expect(panel.get_by_test_id("search-around-summary")).to_contain_text(
        "Employee chosen above"
    )
    expect(panel.get_by_test_id("search-around-summary")).to_contain_text("Raised by")


def test_opening_and_saving_the_dialog_keeps_the_walk_it_did_not_touch(page, api, world):
    """**The sixth instance of the pattern `STATUS.md` names, and it caught a
    real one.**

    The dialog saves the parameters whole, so a document it does not *read* is
    one it overwrites with nothing the moment somebody opens it to fix a label.
    §329 found this with its override blocks and §331 with its filters; this
    unit reused the pattern, did not reuse the test, and shipped the same defect
    into a first draft — the panel showed "Every object of this type" over a
    saved walk, and saving would have made that true.
    """
    open_editor(page, world)
    # An edit with nothing to do with the walk.
    page.get_by_label("Parameter 1 label").fill("Employee now")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    saved = api.call(
        "GET", f"/workspaces/{world.workspace_id}/action-types/{world.action['id']}"
    )
    who = next(p for p in saved["parameters"] if p["api_name"] == "who")
    assert who["display_name"] == "Employee now"
    issue = next(p for p in saved["parameters"] if p["api_name"] == "issue")
    assert issue["dropdown_search_around"] == {
        "start": {"kind": "parameter", "object_type_id": world.employee_type,
                  "parameter": "who"},
        "hops": [{"link_type_id": world.link["id"],
                  "far_type_id": world.issue_type}],
    }


def test_the_panel_will_not_offer_a_link_that_does_not_join_up(page, world):
    """Only the links that touch where the walk has reached. Offering one that
    cannot be added to *this* walk is a control that looks like it works, and
    the server refuses it a save later."""
    open_editor(page, world)
    panel = page.locator(f"[data-parameter-search-around='issue']")
    hop = panel.locator("[data-hop-row='0'] select")
    expect(hop).to_have_count(1)
    # From an Employee there is exactly one link to follow in this workspace.
    assert [t.strip() for t in hop.locator("option").all_inner_texts()] == ["Raised by"]


def test_removing_the_hop_says_the_walk_no_longer_lands_where_it_should(
    page, api, world
):
    """The panel says so rather than letting Save produce a 422 several fields
    later — and it names **both** ends, because "this is wrong" without them
    leaves somebody comparing type names by eye."""
    def name_of(type_id: str) -> str:
        return api.call(
            "GET", f"/workspaces/{world.workspace_id}/object-types/{type_id}"
        )["display_name"]

    open_editor(page, world)
    panel = page.locator(f"[data-parameter-search-around='issue']")
    panel.get_by_role("button", name="Remove link 1 from issue").click()
    note = panel.get_by_test_id("search-around-landing")
    expect(note).to_be_visible()
    # Where it now lands, and where it should: a note naming one of them is a
    # note somebody has to work the other half out from.
    expect(note).to_contain_text(name_of(world.employee_type))
    expect(note).to_contain_text(name_of(world.issue_type))


def test_turning_the_walk_off_returns_to_p36s_default(page, world):
    """The checkbox clears the document rather than leaving an empty one: "every
    object of this type" is a state the column says, not a shape to interpret."""
    open_editor(page, world)
    panel = page.locator(f"[data-parameter-search-around='issue']")
    panel.get_by_role("checkbox").uncheck()
    expect(panel.get_by_test_id("search-around-summary")).to_contain_text(
        "Every object of this type"
    )
    expect(panel.locator("[data-hop-row='0']")).to_have_count(0)


def test_a_walk_written_in_the_panel_narrows_the_form(page, api):
    """**The panel and the form, in one test.** A panel that saved something the
    form does not honour, or a form narrowed by something no panel can write,
    would each pass every other test in this file."""
    mod = Module(api, "Search around panel")
    tag = uuid.uuid4().hex[:8]
    employee_type = mod.object_type(
        columns=["id", "name"], rows=EMPLOYEES, key="id", title="name",
        slug=f"pemp_{tag}",
    )
    issue_type = mod.object_type(
        columns=["id", "employee_id", "title"], rows=ISSUES, key="id",
        title="title", slug=f"piss_{tag}",
    )
    ticket_type = mod.object_type(
        columns=["id", "note"], rows=[{"id": "T1", "note": ""}], key="id",
        title="id", slug=f"ptkt_{tag}",
    )
    api.call(
        "POST", f"/workspaces/{mod.workspace_id}/link-types",
        {"api_name": f"praised_by_{tag}", "display_name": "Raised by",
         "from_type_id": issue_type, "to_type_id": employee_type,
         "cardinality": "one_to_many",
         "from_property": "employee_id", "to_property": "$primary_key"},
    )
    action = api.call(
        "POST", f"/workspaces/{mod.workspace_id}/action-types",
        {"object_type_id": ticket_type, "api_name": f"passign_{tag}",
         "display_name": "Assign ticket", "editable_properties": ["note"]},
    )
    api.call(
        "PUT",
        f"/workspaces/{mod.workspace_id}/action-types/{action['id']}/definition",
        {"parameters": [
             {"api_name": "who", "display_name": "Employee",
              "data_type": "object", "object_type_id": employee_type},
             {"api_name": "issue", "display_name": "Issue",
              "data_type": "object", "object_type_id": issue_type},
         ],
         "rules": [{"kind": "modify_object",
                    "config": {"property": "note", "parameter": "issue"}}],
         "criteria": []},
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "txt": {"resolvedName": "CanvasText",
                    "props": {"tag": "p", "text": "PANEL FORM"}},
            "frm": {"resolvedName": "CanvasActionForm",
                    "props": {"actionTypeId": action["id"]}},
        }),
        "variables": {},
        "events": {},
    })
    mod.type_id = ticket_type
    mod.action = action

    # Before: every issue, because the parameter has no walk.
    open_module(page, mod)
    choose_the_ticket(page)
    expect(picker(page, "issue").locator("option")).to_contain_text(
        ["Choose", "Ada one"], timeout=30000
    )
    assert any("Grace" in o for o in options(page, "issue"))

    open_editor(page, mod)
    panel = page.locator("[data-parameter-search-around='issue']")
    panel.get_by_role("checkbox").check()
    panel.get_by_label("Walk to issue starts from").select_option("parameter")
    panel.get_by_role("button", name="Follow another link from issue").click()
    expect(panel.get_by_test_id("search-around-landing")).to_have_count(0)
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    # After: only Ada's.
    open_module(page, mod)
    choose_the_ticket(page)
    choose(page, "who", "Ada")
    expect(picker(page, "issue").locator("option")).to_contain_text(
        ["Choose", "Ada one", "Ada two"], timeout=30000
    )
    assert not any("Grace" in o for o in options(page, "issue"))
