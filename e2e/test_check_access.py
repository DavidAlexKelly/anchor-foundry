"""The Check access panel, on the screen (§412; `workshop` p.92).

> "You can use the Check access panel in the sidebar to easily check a user's
> access on a Workshop module. This will show if they meet the access
> requirement on the Workshop module, as well as additional data requirements
> to see object types, link types, action types, and functions." (p.92)

`apps/api/tests/test_check_access.py` decides who may do what and
`check-access.test.ts` decides what the words mean. What needs a browser is
the seam and one thing neither can reach: **that the two halves appear
together.** p.92's warning — "the ability to open or edit a Workshop module is
separate from the ability to access the data, actions, or functions" — is only
useful as a pairing on one screen, and a panel that showed the module verdict
and left the requirements a click away would be read as a verdict.

The state the pairing exists for is reachable in the dev workspace as it
stands: Vi Viewer opens this module and cannot run its action.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import eventually, open_builder

#: A well-formed id naming nothing, in a widget of its own. §210's third state
#: on the screen: not a permission problem, and not a pass either.
NOWHERE = "00000000-0000-4000-8000-0000000000ff"


@pytest.fixture(scope="module")
def module_with_action(api):
    """A module that reads a type, runs an action, and points one widget at
    nothing at all."""
    mod = Module(api, "Check access")
    type_id = mod.object_type(
        columns=["id", "state"],
        rows=[{"id": f"T{i}", "state": "open"} for i in range(1, 3)],
        key="id", title="id",
    )
    action = api.call(
        "POST",
        f"/workspaces/{mod.workspace_id}/action-types",
        {
            "object_type_id": type_id,
            "api_name": f"ship_{uuid.uuid4().hex[:8]}",
            "display_name": "Ship the order",
            "editable_properties": ["state"],
        },
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "table": {"resolvedName": "CanvasObjectTable",
                      "props": {"objectTypeId": type_id}},
            "form": {"resolvedName": "CanvasActionForm",
                     "props": {"actionTypeId": action["id"], "title": "Ship"}},
            "gone": {"resolvedName": "CanvasObjectTable",
                     "props": {"objectTypeId": NOWHERE}},
        }),
        "variables": {},
        "events": {},
    })
    return mod, action


def open_access(page, mod):
    open_builder(page, mod)
    page.get_by_role("button", name="Check access", exact=True).click()
    expect(page.get_by_test_id("access-panel")).to_be_visible()


def pick(page, label: str):
    select = page.get_by_test_id("access-user")
    eventually(
        lambda: page.eval_on_selector_all(
            "[data-testid='access-user'] option", "els => els.length"),
        lambda n: n > 1,
        what="the directory",
    )
    select.select_option(label=label)
    expect(page.get_by_test_id("access-module")).to_be_visible(timeout=30000)


def row(page, status: str):
    return page.locator(f"[data-testid='access-rows'] li[data-status='{status}']")


def test_the_panel_asks_about_nobody_until_somebody_is_named(page, module_with_action):
    """An access check is a question about a person. A panel that opened onto
    the first name in the directory would put an answer about a stranger under
    a heading nobody wrote — and a builder who glanced at it would take it for
    the person they had in mind."""
    mod, _ = module_with_action
    open_access(page, mod)
    expect(page.get_by_test_id("access-idle")).to_be_visible()
    expect(page.get_by_test_id("access-module")).to_have_count(0)
    expect(page.get_by_test_id("access-rows")).to_have_count(0)


def test_a_reader_can_open_the_module_and_cannot_run_its_action(
    page, module_with_action
):
    """p.92's warning, on one screen, about a real user of this workspace.

    Vi Viewer holds the workspace's viewer role, so the module opens and every
    type in it reads. Running an action is a project editor's right, so the
    form draws and the button refuses. Both facts are visible at once, which is
    the only arrangement in which either is worth having.
    """
    mod, _ = module_with_action
    open_access(page, mod)
    pick(page, "Vi Viewer (viewer@acme.dev.local)")

    verdict = page.get_by_test_id("access-module")
    expect(verdict).to_have_attribute("data-open", "yes")
    expect(verdict).to_have_attribute("data-edit", "no")
    expect(verdict).to_contain_text("Can open this module")

    unusable = row(page, "unusable")
    expect(unusable).to_have_count(1)
    expect(unusable).to_contain_text("Ship the order")
    expect(unusable).to_contain_text("Can see, cannot run")


def test_the_reason_names_the_role_rather_than_restating_the_verdict(
    page, module_with_action
):
    """The line a builder acts on. "No access" sends them nowhere; "viewer on
    this project" names the thing they would change."""
    mod, _ = module_with_action
    open_access(page, mod)
    pick(page, "Vi Viewer (viewer@acme.dev.local)")
    expect(page.get_by_test_id("access-reason")).to_contain_text("viewer on this project")


def test_an_editor_meets_every_requirement_the_reader_does_not(
    page, module_with_action
):
    """The same module and the same list, answered for somebody else — which is
    what makes the reader's answer above a fact about the reader rather than
    about the module."""
    mod, _ = module_with_action
    open_access(page, mod)
    pick(page, "Ed Editor (editor@acme.dev.local)")

    verdict = page.get_by_test_id("access-module")
    expect(verdict).to_have_attribute("data-edit", "yes")
    expect(row(page, "unusable")).to_have_count(0)
    expect(row(page, "visible")).to_have_count(2)
    # p.92 lists functions fourth and this platform has none. Said on the
    # screen rather than omitted: an absent row reads as a check that passed.
    expect(page.get_by_test_id("access-functions")).to_contain_text("this platform has none")


def test_a_widget_pointing_at_nothing_is_not_reported_as_a_permission_problem(
    page, module_with_action
):
    """§210. Nobody meets it, so it stays in the shortfall — but it is "Not
    found", not "No access", because a builder sent to ask an administrator for
    a grant would be sent for nothing."""
    mod, _ = module_with_action
    open_access(page, mod)
    pick(page, "Ed Editor (editor@acme.dev.local)")

    missing = row(page, "unknown")
    expect(missing).to_have_count(1)
    expect(missing).to_contain_text("Not found")
    expect(missing).to_contain_text(NOWHERE)
    expect(page.get_by_test_id("access-summary")).to_contain_text("1 of 3")


def test_switching_user_asks_again(page, module_with_action):
    """The picker is a control, not a label. An answer that stayed on the
    screen while the name above it changed would be the worst thing this panel
    could do."""
    mod, _ = module_with_action
    open_access(page, mod)
    pick(page, "Ed Editor (editor@acme.dev.local)")
    expect(page.get_by_test_id("access-module")).to_have_attribute("data-edit", "yes")
    pick(page, "Vi Viewer (viewer@acme.dev.local)")
    expect(page.get_by_test_id("access-module")).to_have_attribute("data-edit", "no")
