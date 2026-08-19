"""Object type groups (parity `docs/parity/ontology.md` §1.3; Foundry
`object-link-types` p.261-263).

> "Object type groups are a classification primitive that help users better
> search and explore their ontology." (p.261)

**A group makes no claim about its members**, which is why most of what a
feature file usually contains is absent here: no validation about what may be
grouped with what, no refusal to delete a group in use, no cascade to worry
about. Grouping an object type does not change it, so the tests that would
guard those things would be guarding nothing.

What is left is the one rule p.263 spells out having *changed on purpose*:

> "Previously, if all object types inside a group were non-discoverable to a
> certain user … the group was also non-discoverable to the user … all groups
> will now be discoverable to any user that can view the ontology."

A group's visibility is a fact about the group. The natural implementation -
list the groups by joining the membership table - quietly reintroduces the old
behaviour, and the cheapest visible case of it is a group with no members,
which is the state every group is in for the few seconds after it is created.
There is a test named after that, and it is the one worth keeping.

The rest is the two directions p.261 offers (the groups menu and "Edit groups"
on the object type page) agreeing with each other, and p.262's three places a
group shows up: search, the filterable table, the column on each row.
"""
from __future__ import annotations

import os
import sys
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import ADMIN_DSN, Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def other_workspace(fx: Fixture) -> str:
    """A **second ontology the same people can see**.

    Every scoping bug in this file is invisible without one. The shared
    `Fixture` has a second *organisation*, which the permission middleware
    rejects before a query runs - so it proves the middleware and nothing about
    whether the SQL underneath it filters by workspace. A group read through
    the wrong workspace's URL by somebody who legitimately has both is the case
    that reaches the query, and it is the case a `WHERE id = :gid` with no
    workspace clause answers happily.
    """
    wid = uuid.uuid4()
    tag = uuid.uuid4().hex[:8]
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            """INSERT INTO workspaces (id, organisation_id, name, slug, s3_prefix,
                                       pg_schema, search_prefix, created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (wid, fx.org, f"WS2 {tag}", f"ws2-{tag}", f"workspaces/ws2-{tag}/",
             f"ws2_{wid.hex[:12]}", f"ws2-{wid.hex[:12]}-", fx.owner),
        )
        for user, role in ((fx.editor, "editor"), (fx.viewer, "viewer")):
            conn.execute(
                "INSERT INTO workspace_members (workspace_id, user_id, role)"
                " VALUES (%s,%s,%s)",
                (wid, user, role),
            )
    return str(wid)


@pytest.fixture(scope="module")
def client() -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


def make_group(client: TestClient, fx: Fixture, **over) -> dict:
    tag = uuid.uuid4().hex[:6]
    body = {
        "api_name": f"logistics_{tag}",
        "display_name": f"Logistics {tag}",
        "description": "Everything that moves",
        **over,
    }
    r = client.post(
        f"{wbase(fx)}/object-type-groups", headers=hdr(fx.editor_sub), json=body
    )
    assert r.status_code == 201, r.text
    return r.json()


def make_type(client: TestClient, fx: Fixture, **over) -> dict:
    tag = uuid.uuid4().hex[:6]
    body = {
        "api_name": f"shipment_{tag}",
        "display_name": f"Shipment {tag}",
        "properties": [
            {"api_name": "id", "display_name": "Id", "data_type": "string"},
        ],
        "title_property": "id",
        **over,
    }
    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub), json=body
    )
    assert r.status_code == 201, r.text
    return r.json()


def groups_of(client: TestClient, fx: Fixture, type_id: str) -> list[dict]:
    r = client.get(
        f"{wbase(fx)}/object-types/{type_id}/groups", headers=hdr(fx.viewer_sub)
    )
    assert r.status_code == 200, r.text
    return r.json()


def members_of(client: TestClient, fx: Fixture, group_id: str) -> list[dict]:
    r = client.get(
        f"{wbase(fx)}/object-type-groups/{group_id}/members",
        headers=hdr(fx.viewer_sub),
    )
    assert r.status_code == 200, r.text
    return r.json()


def set_members(client: TestClient, fx: Fixture, group_id: str, ids: list[str]):
    return client.put(
        f"{wbase(fx)}/object-type-groups/{group_id}/members",
        headers=hdr(fx.editor_sub),
        json={"object_type_ids": ids},
    )


def set_groups(client: TestClient, fx: Fixture, type_id: str, ids: list[str]):
    return client.put(
        f"{wbase(fx)}/object-types/{type_id}/groups",
        headers=hdr(fx.editor_sub),
        json={"group_ids": ids},
    )


# ---- p.263's rule, which is the reason this feature has any tests at all ----
def test_an_empty_group_still_lists(client: TestClient, fx: Fixture) -> None:
    """**The claim worth protecting.** p.263: "all groups will now be
    discoverable to any user that can view the ontology", where "previously,
    if all object types inside a group were non-discoverable … the group was
    also non-discoverable".

    A listing built as a join to the membership table implements the *old*
    behaviour, and the cheapest case of it is a group with nothing in it -
    which is the state every group is in for the few seconds after somebody
    creates one. That version of this feature lets you create a group and then
    shows you nothing, with no error to explain it.
    """
    group = make_group(client, fx)

    r = client.get(f"{wbase(fx)}/object-type-groups", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    listed = {g["id"]: g for g in r.json()}
    assert group["id"] in listed, "an empty group vanished from its own listing"
    assert listed[group["id"]]["member_count"] == 0


def test_a_group_survives_losing_its_last_member(
    client: TestClient, fx: Fixture
) -> None:
    """The same rule from the other side: emptying a group is not deleting it.

    Separate from the test above because they fail differently - one is a
    listing that never showed it, this is a listing that showed it and then
    stopped, which is what somebody sees after tidying up a group they meant
    to keep.
    """
    group = make_group(client, fx)
    kind = make_type(client, fx)
    assert set_members(client, fx, group["id"], [kind["id"]]).status_code == 200
    assert set_members(client, fx, group["id"], []).status_code == 200

    r = client.get(f"{wbase(fx)}/object-type-groups", headers=hdr(fx.viewer_sub))
    listed = {g["id"]: g for g in r.json()}
    assert group["id"] in listed
    assert listed[group["id"]]["member_count"] == 0


# ---- the two directions p.261 offers ---------------------------------------
def test_both_directions_write_the_same_membership(
    client: TestClient, fx: Fixture
) -> None:
    """p.261 offers a groups menu *and* "Edit groups in the object type
    overview page". Two screens, one fact - so a membership made from either
    is readable from the other, or the two pages disagree about the same
    ontology and whichever you looked at last is the one you believe.
    """
    group = make_group(client, fx)
    from_menu = make_type(client, fx)
    from_type_page = make_type(client, fx)

    assert set_members(client, fx, group["id"], [from_menu["id"]]).status_code == 200
    # Adding the second from the *other* direction must not remove the first:
    # they are different rows, and `set_groups_for_type` clears by object type.
    assert set_groups(client, fx, from_type_page["id"], [group["id"]]).status_code == 200

    member_ids = {m["id"] for m in members_of(client, fx, group["id"])}
    assert member_ids == {from_menu["id"], from_type_page["id"]}
    assert [g["id"] for g in groups_of(client, fx, from_menu["id"])] == [group["id"]]


def test_setting_members_replaces_rather_than_adds(
    client: TestClient, fx: Fixture
) -> None:
    """PUT means the body is the whole membership. A version that only ever
    inserted would make "remove one" impossible through the same endpoint that
    added it, and the symptom is a group that grows and never shrinks."""
    group = make_group(client, fx)
    first = make_type(client, fx)
    second = make_type(client, fx)

    assert set_members(client, fx, group["id"], [first["id"]]).status_code == 200
    assert set_members(client, fx, group["id"], [second["id"]]).status_code == 200
    assert [m["id"] for m in members_of(client, fx, group["id"])] == [second["id"]]


def test_setting_a_types_groups_replaces_rather_than_adds(
    client: TestClient, fx: Fixture
) -> None:
    """The same for the object type page's direction, and worth its own test:
    the two paths clear by different columns, so one can be right while the
    other appends forever."""
    kind = make_type(client, fx)
    first = make_group(client, fx)
    second = make_group(client, fx)

    assert set_groups(client, fx, kind["id"], [first["id"]]).status_code == 200
    assert set_groups(client, fx, kind["id"], [second["id"]]).status_code == 200
    assert [g["id"] for g in groups_of(client, fx, kind["id"])] == [second["id"]]


def test_an_object_type_can_be_in_several_groups(
    client: TestClient, fx: Fixture
) -> None:
    """p.261 says "Edit groups", plural. A classification that allowed one
    would be a column on the object type, not a table."""
    kind = make_type(client, fx)
    one = make_group(client, fx, display_name="Aaa group")
    two = make_group(client, fx, display_name="Bbb group")

    assert set_groups(client, fx, kind["id"], [one["id"], two["id"]]).status_code == 200
    assert [g["id"] for g in groups_of(client, fx, kind["id"])] == [
        one["id"], two["id"]
    ]


def test_naming_the_same_member_twice_is_not_an_error(
    client: TestClient, fx: Fixture
) -> None:
    """The requested state is unambiguous, so a duplicate in the list is a
    client bug rather than a conflict - and answering it with a 409 would make
    a harmless payload fail while changing nothing about what was asked for."""
    group = make_group(client, fx)
    kind = make_type(client, fx)
    r = set_members(client, fx, group["id"], [kind["id"], kind["id"]])
    assert r.status_code == 200, r.text
    assert [m["id"] for m in r.json()] == [kind["id"]]


# ---- p.262's three places a group shows up ---------------------------------
def test_the_object_type_listing_carries_its_groups(
    client: TestClient, fx: Fixture
) -> None:
    """p.262: "The table of object types in Ontology Manager supports
    displaying and filtering by group." Displaying is this half."""
    group = make_group(client, fx)
    kind = make_type(client, fx)
    assert set_members(client, fx, group["id"], [kind["id"]]).status_code == 200

    r = client.get(f"{wbase(fx)}/object-types", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    row = next(t for t in r.json() if t["id"] == kind["id"])
    assert [g["display_name"] for g in row["groups"]] == [group["display_name"]]


def test_the_object_type_listing_filters_by_group(
    client: TestClient, fx: Fixture
) -> None:
    """And filtering is this half. The assertion is two-sided on purpose: a
    filter that returned everything would pass a test that only checked the
    member was present."""
    group = make_group(client, fx)
    inside = make_type(client, fx)
    outside = make_type(client, fx)
    assert set_members(client, fx, group["id"], [inside["id"]]).status_code == 200

    r = client.get(
        f"{wbase(fx)}/object-types?group_id={group['id']}", headers=hdr(fx.viewer_sub)
    )
    assert r.status_code == 200, r.text
    ids = {t["id"] for t in r.json()}
    assert inside["id"] in ids
    assert outside["id"] not in ids


def test_a_group_is_findable_by_name(client: TestClient, fx: Fixture) -> None:
    """p.262: "Groups are searchable in Ontology Manager's Search bar and
    Search bar dialog." A classification nobody can find classifies nothing."""
    tag = uuid.uuid4().hex[:6]
    group = make_group(
        client, fx, api_name=f"perishables_{tag}", display_name=f"Perishables {tag}"
    )
    kind = make_type(client, fx)
    assert set_members(client, fx, group["id"], [kind["id"]]).status_code == 200

    r = client.get(
        f"{wbase(fx)}/ontology-search?q=perishables_{tag}", headers=hdr(fx.viewer_sub)
    )
    assert r.status_code == 200, r.text
    hits = [h for h in r.json() if h["kind"] == "group"]
    assert [h["id"] for h in hits] == [group["id"]]
    # No owner to name, so the member count takes that slot - the same shape a
    # shared property's hit has, and for the same reason (p.178, p.261).
    assert hits[0]["object_type_id"] is None
    assert hits[0]["usage_count"] == 1


def test_an_empty_group_is_findable_too(client: TestClient, fx: Fixture) -> None:
    """p.263 again, in the place it is easiest to get wrong twice: a search
    that joined the membership table would drop exactly the group somebody is
    searching for in order to put something in it."""
    tag = uuid.uuid4().hex[:6]
    group = make_group(client, fx, api_name=f"unused_{tag}", display_name=f"Unused {tag}")

    r = client.get(
        f"{wbase(fx)}/ontology-search?q=unused_{tag}", headers=hdr(fx.viewer_sub)
    )
    hits = [h for h in r.json() if h["kind"] == "group"]
    assert [h["id"] for h in hits] == [group["id"]]
    assert hits[0]["usage_count"] == 0


# ---- editing and deleting --------------------------------------------------
def test_a_group_can_be_renamed_without_losing_its_members(
    client: TestClient, fx: Fixture
) -> None:
    group = make_group(client, fx)
    kind = make_type(client, fx)
    assert set_members(client, fx, group["id"], [kind["id"]]).status_code == 200

    r = client.patch(
        f"{wbase(fx)}/object-type-groups/{group['id']}",
        headers=hdr(fx.editor_sub),
        json={"display_name": "Renamed", "description": "Still the same group"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["display_name"] == "Renamed"
    assert r.json()["member_count"] == 1
    assert [m["id"] for m in members_of(client, fx, group["id"])] == [kind["id"]]


def test_the_api_name_cannot_be_renamed(client: TestClient, fx: Fixture) -> None:
    """It is the stable machine name and what p.262's search matches on, so a
    rename would move a group out from under a saved query. Sending one is
    ignored rather than refused, the same as every other update body in this
    API that omits a field it does not own."""
    group = make_group(client, fx)
    r = client.patch(
        f"{wbase(fx)}/object-type-groups/{group['id']}",
        headers=hdr(fx.editor_sub),
        json={"display_name": "X", "description": "", "api_name": "something_else"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["api_name"] == group["api_name"]


def test_deleting_a_group_keeps_its_object_types(
    client: TestClient, fx: Fixture
) -> None:
    """**The cascade that must not happen.** A group carries no configuration
    its members depend on, so deleting the classification deletes exactly the
    classification. The version of this that gets it wrong takes object types
    out of an ontology as a side effect of tidying up a label.
    """
    group = make_group(client, fx)
    kind = make_type(client, fx)
    assert set_members(client, fx, group["id"], [kind["id"]]).status_code == 200

    r = client.delete(
        f"{wbase(fx)}/object-type-groups/{group['id']}", headers=hdr(fx.editor_sub)
    )
    assert r.status_code == 204, r.text

    still = client.get(
        f"{wbase(fx)}/object-types/{kind['id']}", headers=hdr(fx.viewer_sub)
    )
    assert still.status_code == 200, still.text
    assert groups_of(client, fx, kind["id"]) == []


def test_deleting_an_object_type_removes_it_from_its_groups(
    client: TestClient, fx: Fixture
) -> None:
    """The other cascade, and the one that has to happen: a membership naming
    a deleted object type would make the group's own listing 500 or, worse,
    quietly count a member nobody can open."""
    group = make_group(client, fx)
    kind = make_type(client, fx)
    assert set_members(client, fx, group["id"], [kind["id"]]).status_code == 200

    r = client.delete(
        f"{wbase(fx)}/object-types/{kind['id']}", headers=hdr(fx.editor_sub)
    )
    assert r.status_code == 204, r.text

    assert members_of(client, fx, group["id"]) == []
    listing = client.get(
        f"{wbase(fx)}/object-type-groups", headers=hdr(fx.viewer_sub)
    ).json()
    assert next(g for g in listing if g["id"] == group["id"])["member_count"] == 0


# ---- names, roles and boundaries -------------------------------------------
def test_a_duplicate_api_name_is_refused(client: TestClient, fx: Fixture) -> None:
    group = make_group(client, fx)
    r = client.post(
        f"{wbase(fx)}/object-type-groups",
        headers=hdr(fx.editor_sub),
        json={"api_name": group["api_name"], "display_name": "Clash"},
    )
    assert r.status_code == 409, r.text


def test_an_invalid_api_name_is_refused(client: TestClient, fx: Fixture) -> None:
    r = client.post(
        f"{wbase(fx)}/object-type-groups",
        headers=hdr(fx.editor_sub),
        json={"api_name": "Not A Name", "display_name": "Nope"},
    )
    assert r.status_code == 422, r.text


def test_a_viewer_can_read_but_not_write(client: TestClient, fx: Fixture) -> None:
    """p.261: groups are managed "generally by ontology owners and editors",
    and p.263 puts *viewing* at viewer permission. Both halves, because a
    feature that only tested the refusal could be refusing everybody."""
    group = make_group(client, fx)
    kind = make_type(client, fx)

    ok = client.get(f"{wbase(fx)}/object-type-groups", headers=hdr(fx.viewer_sub))
    assert ok.status_code == 200, ok.text

    denied = client.post(
        f"{wbase(fx)}/object-type-groups",
        headers=hdr(fx.viewer_sub),
        json={"api_name": "viewer_made_this", "display_name": "Nope"},
    )
    assert denied.status_code == 403, denied.text

    denied_members = client.put(
        f"{wbase(fx)}/object-type-groups/{group['id']}/members",
        headers=hdr(fx.viewer_sub),
        json={"object_type_ids": [kind["id"]]},
    )
    assert denied_members.status_code == 403, denied_members.text


def test_another_organisation_cannot_see_the_group(
    client: TestClient, fx: Fixture
) -> None:
    make_group(client, fx)
    r = client.get(f"{wbase(fx)}/object-type-groups", headers=hdr(fx.foreign_sub))
    assert r.status_code in (403, 404), r.text


def test_an_unknown_object_type_is_a_404_not_an_integrity_error(
    client: TestClient, fx: Fixture
) -> None:
    """db 0056's composite foreign key already makes a cross-workspace
    membership impossible. This is about the *message*: a constraint violation
    names a constraint, and whoever sent the id needs to be told it was the id.
    """
    group = make_group(client, fx)
    r = set_members(client, fx, group["id"], [str(uuid.uuid4())])
    assert r.status_code == 404, r.text


def test_an_unknown_group_is_a_404(client: TestClient, fx: Fixture) -> None:
    kind = make_type(client, fx)
    r = set_groups(client, fx, kind["id"], [str(uuid.uuid4())])
    assert r.status_code == 404, r.text

    missing = client.get(
        f"{wbase(fx)}/object-type-groups/{uuid.uuid4()}/members",
        headers=hdr(fx.viewer_sub),
    )
    assert missing.status_code == 404, missing.text


def test_an_unknown_object_type_cannot_be_given_groups(
    client: TestClient, fx: Fixture
) -> None:
    """The object type page's direction has its own check, and a missing one
    fails differently from the group direction's: `_replace` clears by object
    type, finds nothing to clear, and then hits the foreign key - a 500 naming
    a constraint instead of a 404 naming the id somebody sent."""
    group = make_group(client, fx)
    r = set_groups(client, fx, str(uuid.uuid4()), [group["id"]])
    assert r.status_code == 404, r.text


def test_setting_members_of_an_unknown_group_is_a_404(
    client: TestClient, fx: Fixture
) -> None:
    """Same shape as the write above, from the groups menu instead."""
    kind = make_type(client, fx)
    r = set_members(client, fx, str(uuid.uuid4()), [kind["id"]])
    assert r.status_code == 404, r.text


def test_deleting_an_unknown_group_is_a_404(client: TestClient, fx: Fixture) -> None:
    """A delete that reports success for something that was never there is a
    delete you cannot use to find out whether you deleted the right thing."""
    r = client.delete(
        f"{wbase(fx)}/object-type-groups/{uuid.uuid4()}", headers=hdr(fx.editor_sub)
    )
    assert r.status_code == 404, r.text


def test_the_delete_service_refuses_on_its_own(fx: Fixture) -> None:
    """**The one check the HTTP suite cannot reach.**

    The route reads the group before deleting it, because the audit record
    says how many object types stopped being classified - so removing
    `delete_group`'s own existence check changes nothing anybody can observe
    through the API, and a mutation that removes it survives a suite made
    entirely of requests.

    That is a gap in the tests rather than redundant code: the guard belongs
    to the service, which is where the rule lives, and the route's read is
    there for the audit metadata. So this one test goes in through the
    service, and the delete route keeps a reason to exist that does not depend
    on it.
    """
    import asyncio

    from src.lib.db import user_connection
    from src.services import object_type_groups as service
    from src.lib.errors import NotFoundError

    async def run() -> None:
        async with user_connection(fx.editor) as conn:
            with pytest.raises(NotFoundError):
                await service.delete_group(
                    conn, uuid.UUID(str(fx.workspace)), uuid.uuid4()
                )

    asyncio.run(run())


def test_the_write_reports_the_state_it_just_wrote(
    client: TestClient, fx: Fixture
) -> None:
    """Both PUTs answer with the resulting membership, and both are asserted
    on the **response** rather than on a follow-up read.

    A response that came back empty while the database was correct would look
    fine to every test that re-reads, and would show somebody an emptied group
    the moment they saved one - fixed only by a refresh they have no reason to
    do.
    """
    group = make_group(client, fx)
    kind = make_type(client, fx)

    from_menu = set_members(client, fx, group["id"], [kind["id"]])
    assert from_menu.status_code == 200, from_menu.text
    assert [m["id"] for m in from_menu.json()] == [kind["id"]]

    from_type_page = set_groups(client, fx, kind["id"], [group["id"]])
    assert from_type_page.status_code == 200, from_type_page.text
    assert [g["id"] for g in from_type_page.json()] == [group["id"]]


# ---- the workspace boundary, which permissions alone do not prove ----------
def test_a_group_is_invisible_through_another_workspaces_url(
    client: TestClient, fx: Fixture, other_workspace: str
) -> None:
    """**The scoping bug permissions cannot catch.** The workspace comes from
    the path, and the person holds both - so the middleware lets the request
    through and the only thing standing between a group and the wrong ontology
    is the `workspace_id` clause in the query itself.

    A workspace is this platform's ontology (db 0003), so a group reachable
    from a second one is a classification leaking across the boundary p.192
    draws for every other ontology primitive.
    """
    group = make_group(client, fx)
    kind = make_type(client, fx)
    assert set_members(client, fx, group["id"], [kind["id"]]).status_code == 200

    other = f"/api/workspaces/{other_workspace}"
    seen = client.get(f"{other}/object-type-groups", headers=hdr(fx.viewer_sub))
    assert seen.status_code == 200, seen.text
    assert group["id"] not in {g["id"] for g in seen.json()}

    members = client.get(
        f"{other}/object-type-groups/{group['id']}/members", headers=hdr(fx.viewer_sub)
    )
    assert members.status_code == 404, members.text

    renamed = client.patch(
        f"{other}/object-type-groups/{group['id']}",
        headers=hdr(fx.editor_sub),
        json={"display_name": "Stolen", "description": ""},
    )
    assert renamed.status_code == 404, renamed.text

    removed = client.delete(
        f"{other}/object-type-groups/{group['id']}", headers=hdr(fx.editor_sub)
    )
    assert removed.status_code == 404, removed.text


def test_a_group_cannot_take_another_workspaces_object_type(
    client: TestClient, fx: Fixture, other_workspace: str
) -> None:
    """db 0056's composite foreign key makes this impossible to store; the
    check exists so the answer is a 404 naming the object type rather than an
    integrity error naming a constraint - and so a group cannot be used to
    smuggle a reference across the boundary at all."""
    group = make_group(client, fx)
    r = client.post(
        f"/api/workspaces/{other_workspace}/object-types",
        headers=hdr(fx.editor_sub),
        json={
            "api_name": f"elsewhere_{uuid.uuid4().hex[:6]}",
            "display_name": "Elsewhere",
            "properties": [
                {"api_name": "id", "display_name": "Id", "data_type": "string"}
            ],
            "title_property": "id",
        },
    )
    assert r.status_code == 201, r.text

    denied = set_members(client, fx, group["id"], [r.json()["id"]])
    assert denied.status_code == 404, denied.text
    assert members_of(client, fx, group["id"]) == []


def test_two_workspaces_can_use_the_same_group_name(
    client: TestClient, fx: Fixture, other_workspace: str
) -> None:
    """The uniqueness is per workspace (db 0056), because a workspace is an
    ontology - and a global one would mean the first team to name a group
    `logistics` takes the word away from everybody else in the organisation."""
    group = make_group(client, fx)
    r = client.post(
        f"/api/workspaces/{other_workspace}/object-type-groups",
        headers=hdr(fx.editor_sub),
        json={"api_name": group["api_name"], "display_name": "Same name, elsewhere"},
    )
    assert r.status_code == 201, r.text
