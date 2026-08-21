"""Groups in the Ontology Manager (parity `docs/parity/ontology.md` §1.3;
Foundry `object-link-types` p.261-263).

§172 built the classification and its refusals through the API. This is
somebody using it: p.261's groups menu, p.261's "Edit groups" from the object
type, and p.262's three appearances — search, the column, the filter.

**The claim that needs a browser is p.263's, twice.** A group is discoverable
whether or not its members are, and the cheapest case of getting that wrong is
a group with nothing in it. A listing built as a join to the membership table
would let somebody create a group and then show them nothing — which is not an
error message, it is an absence, and absences are what browser checks are for.

**The second is a write that must not happen.** Membership is its own resource,
so the edit dialog holds two writes; one that PUT the groups on every save
would silently un-group a type whenever two people had the page open. That is
the carry-through failure in a new place, and the test for it is the same
shape: set the value elsewhere, do an unrelated edit here, assert it survived.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE

ROWS = [
    {"id": "R1", "name": "Ada", "code": "A"},
    {"id": "R2", "name": "Grace", "code": "B"},
]


@pytest.fixture(scope="module")
def module(api):
    things = Module(api, "Groups")
    things.object_type(
        columns=["id", "name", "code"], rows=ROWS, key="id", title="name",
    )
    return things


@pytest.fixture
def group(api, module):
    """A fresh group per test, named uniquely so a filter can only match it."""
    tag = uuid.uuid4().hex[:6]
    return api.call(
        "POST", f"/workspaces/{module.workspace_id}/object-type-groups",
        {
            "api_name": f"logistics_{tag}",
            "display_name": f"Logistics {tag}",
            "description": "Everything that moves",
        },
    )


def open_objects(page, module) -> None:
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}/objects")
    # `exact=True` for the reason `test_value_types.py` spells out: the
    # fixture names its project after the section, `name=` matches by
    # substring, and the two headings now arrive together.
    expect(
        page.get_by_role("heading", name="Groups", exact=True)
    ).to_be_visible(timeout=30000)


def group_row(page, group):
    row = page.locator("tbody tr").filter(has_text=group["api_name"]).first
    expect(row).to_be_visible(timeout=30000)
    return row


def type_row(page, module):
    row = page.locator("tbody tr").filter(has_text=f"seed_{module.tag}").first
    expect(row).to_be_visible(timeout=30000)
    return row


def open_type_editor(page, module) -> None:
    type_row(page, module).get_by_role("button", name="Edit").click()
    expect(page.get_by_test_id("status-select")).to_be_visible(timeout=15000)


def test_a_new_group_is_listed_before_anything_is_in_it(page, module, api) -> None:
    """**p.263's rule, at the moment it first matters.**

    > "all groups will now be discoverable to any user that can view the
    > ontology" (p.263)

    Every group is empty for the few seconds after it is created, so a listing
    that joined the membership table would show nothing here — no error, just
    a group that appears not to have been created.

    **The workspace is emptied of groups first**, and that is the point rather
    than tidiness: this module reuses a workspace, so a leftover group with
    members from an earlier run is enough to keep a listing on screen that
    would otherwise have vanished. The claim is about a workspace whose only
    group is a new empty one, so the test has to build that workspace.
    """
    base = f"/workspaces/{module.workspace_id}/object-type-groups"
    for existing in api.call("GET", base):
        api.call("DELETE", f"{base}/{existing['id']}")

    open_objects(page, module)
    name = f"Perishables {uuid.uuid4().hex[:6]}"
    page.get_by_test_id("new-group").click()
    page.get_by_test_id("group-name").fill(name)
    page.get_by_test_id("group-save").click()

    row = page.locator("tbody tr").filter(has_text=name).first
    expect(row).to_be_visible(timeout=15000)
    # And it says nothing is in it, rather than saying nothing.
    expect(row).to_contain_text("0 object types")


def test_a_group_can_take_object_types_and_says_how_many(page, module, group) -> None:
    """p.261's groups menu: the membership edited from the group's own side."""
    open_objects(page, module)
    group_row(page, group).get_by_role(
        "button", name=f"Object types in {group['api_name']}"
    ).click()
    expect(page.get_by_test_id("group-member-picker")).to_be_visible(timeout=15000)
    page.get_by_test_id(f"group-member-seed_{module.tag}").check()
    page.get_by_test_id("group-members-save").click()

    expect(group_row(page, group)).to_contain_text("1 object type", timeout=15000)

    # **Reopening shows what is already in it.** A dialog that always opened
    # empty would look right while you were adding the first member and then
    # silently drop every existing one the next time somebody touched it -
    # the whole-membership PUT makes "opens unticked" and "empties the group"
    # the same bug.
    group_row(page, group).get_by_role(
        "button", name=f"Object types in {group['api_name']}"
    ).click()
    expect(
        page.get_by_test_id(f"group-member-seed_{module.tag}")
    ).to_be_checked(timeout=15000)


def test_the_object_type_row_shows_its_groups(page, module, group, api) -> None:
    """p.262: the table of object types "supports displaying … by group"."""
    api.call(
        "PUT",
        f"/workspaces/{module.workspace_id}/object-type-groups/{group['id']}/members",
        {"object_type_ids": [module.object_type_id]},
    )
    open_objects(page, module)
    expect(type_row(page, module)).to_contain_text(group["display_name"])


def test_the_filter_narrows_the_table(page, module, group, api) -> None:
    """p.262's other half: "…and filtering by group".

    Two-sided on purpose. A filter that quietly returned everything would pass
    a check that only looked for the member.
    """
    other = api.call(
        "POST", f"/workspaces/{module.workspace_id}/object-types",
        {
            "api_name": f"unfiled_{uuid.uuid4().hex[:6]}",
            "display_name": "Unfiled thing",
            "properties": [
                {"api_name": "id", "display_name": "Id", "data_type": "string"}
            ],
            "title_property": "id",
        },
    )
    api.call(
        "PUT",
        f"/workspaces/{module.workspace_id}/object-type-groups/{group['id']}/members",
        {"object_type_ids": [module.object_type_id]},
    )

    open_objects(page, module)
    expect(page.locator("tbody tr").filter(has_text=other["api_name"]).first).to_be_visible()

    page.get_by_test_id("group-filter").select_option(group["id"])
    expect(type_row(page, module)).to_be_visible(timeout=15000)
    expect(
        page.locator("tbody tr").filter(has_text=other["api_name"])
    ).to_have_count(0)


def test_an_empty_filter_result_does_not_claim_an_empty_ontology(
    page, module, group
) -> None:
    """**The wrong empty state is worse than none.**

    Falling through to "The ontology starts here" because a group happens to
    hold nothing would tell somebody with a full ontology that they have no
    object types, and offer them a Define button as the way out of a filter.
    """
    open_objects(page, module)
    page.get_by_test_id("group-filter").select_option(group["id"])

    empty = page.get_by_test_id("empty-group-filter")
    expect(empty).to_be_visible(timeout=15000)
    expect(page.get_by_role("heading", name="The ontology starts here")).to_have_count(0)

    page.get_by_test_id("clear-group-filter").click()
    expect(type_row(page, module)).to_be_visible(timeout=15000)


def test_groups_can_be_edited_from_the_object_type(page, module, group, api) -> None:
    """p.261: "Groups can also be added directly to object types by selecting
    Edit groups in the object type overview page." """
    groups_url = (
        f"/workspaces/{module.workspace_id}"
        f"/object-types/{module.object_type_id}/groups"
    )
    before = {g["id"] for g in api.call("GET", groups_url)}

    open_objects(page, module)
    open_type_editor(page, module)
    page.get_by_test_id(f"type-group-{group['api_name']}").check()
    with page.expect_response(
        lambda r: r.url.endswith("/groups") and r.request.method == "PUT"
    ) as saved:
        page.get_by_role("button", name="Save", exact=True).click()
    assert saved.value.ok, saved.value.text()

    # **Exactly one more**, not "at least one". The PUT sends the whole
    # membership, so a version that sent only the box just ticked would drop
    # every other group this type was in - which is the same clobber the
    # carry-through test below guards, reached by a different route.
    after = {g["id"] for g in api.call("GET", groups_url)}
    assert after == before | {group["id"]}, (before, after)


def test_an_unrelated_edit_does_not_touch_the_groups(page, module, group, api) -> None:
    """**The carry-through failure, for the eighth time** (§157, §160, §163,
    §164, §165, §169, §171, and here) — and the first one answered by *not
    writing* rather than by carrying the value more carefully.

    Membership is its own resource, so the dialog holds two writes. One that
    PUT the groups on every save would look correct in every test that opens
    the dialog and changes the groups; it fails only when somebody else
    changed them while the dialog was open. So the group is attached through
    the API *after* the dialog is showing, and then an unrelated field is
    saved.
    """
    groups_url = (
        f"/workspaces/{module.workspace_id}"
        f"/object-types/{module.object_type_id}/groups"
    )
    open_objects(page, module)
    open_type_editor(page, module)

    # **Wait for the dialog to have actually read the memberships.** Without
    # this the test is a race it loses: the groups query is still in flight
    # while the API call below lands, so its answer *includes* the colleague's
    # group and even a dialog that PUTs on every save sends the right value.
    # An unticked box for this group is the proof that the read finished and
    # finished without it.
    checkbox = page.get_by_test_id(f"type-group-{group['api_name']}")
    expect(checkbox).to_be_visible(timeout=15000)
    expect(checkbox).not_to_be_checked()

    # Attached behind the dialog's back: this is the colleague's edit, made
    # after this dialog read the memberships and therefore invisible to it.
    existing = [g["id"] for g in api.call("GET", groups_url)]
    api.call("PUT", groups_url, {"group_ids": [*existing, group["id"]]})

    page.get_by_role("textbox", name="Description", exact=False).fill("Edited")
    with page.expect_response(
        lambda r: "/object-types/" in r.url and r.request.method == "PATCH"
    ) as saved:
        page.get_by_role("button", name="Save", exact=True).click()
    assert saved.value.ok, saved.value.text()

    # **Wait for the dialog to close, not just for the PATCH.** The groups PUT
    # is a *second* request, awaited after the PATCH resolves - so a read taken
    # on the PATCH's response happens before a wrongly-issued PUT lands, and
    # sees the membership still intact. The dialog closes in `onSuccess`, which
    # runs only once both writes have finished, so its disappearance is the
    # signal that there is nothing more coming.
    expect(page.get_by_test_id("status-select")).to_have_count(0, timeout=15000)

    after = {g["id"] for g in api.call("GET", groups_url)}
    assert group["id"] in after, after


def test_a_group_is_findable_by_name(page, module, group) -> None:
    """p.262: "Groups are searchable in Ontology Manager's Search bar"."""
    open_objects(page, module)
    page.get_by_role("searchbox", name="Search the ontology").fill(group["api_name"])
    hit = page.locator('[data-kind="group"]').first
    expect(hit).to_be_visible(timeout=15000)
    expect(hit).to_contain_text(group["display_name"])
    # Zero is worth saying out loud here, for p.263's reason.
    expect(hit).to_contain_text("0 object types")

    # **And it goes somewhere.** A group is the second kind with no object
    # type to open, and the two ownerless kinds cannot share a destination: a
    # group id handed to the shared property panel matches nothing and opens
    # nothing, which is a dead hit rather than an error.
    hit.click()
    expect(page.get_by_test_id("group-member-picker")).to_be_visible(timeout=15000)


def test_deleting_a_group_keeps_the_object_types(page, module, group, api) -> None:
    """A group carries no schema, so this deletes the classification and
    nothing else. The button says so, because somebody expecting a cascade
    would not press it."""
    api.call(
        "PUT",
        f"/workspaces/{module.workspace_id}/object-type-groups/{group['id']}/members",
        {"object_type_ids": [module.object_type_id]},
    )
    open_objects(page, module)

    delete = group_row(page, group).get_by_role(
        "button", name=f"Delete {group['api_name']}"
    )
    assert "None is deleted" in (delete.get_attribute("title") or "")
    delete.click()

    expect(
        page.locator("tbody tr").filter(has_text=group["api_name"])
    ).to_have_count(0, timeout=15000)
    # The object type is still there, and no longer wearing the chip.
    row = type_row(page, module)
    expect(row).not_to_contain_text(group["display_name"])
