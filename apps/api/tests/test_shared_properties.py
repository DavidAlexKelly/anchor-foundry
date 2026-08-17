"""Shared properties (parity `docs/parity/ontology.md` §1.2; Foundry
`object-link-types` p.178-191).

> "A shared property is a property that can be used on multiple object types in
> your ontology… While property metadata is shared across objects, the
> underlying object data is not." (p.178)

Two claims are worth more than the rest and most of this file is about them.

**Editing in one place actually reaches the other place** (p.178). A copy taken
at attach time would pass a test that only ever reads back what it wrote, so
the test that matters attaches *two* object types, edits the shared property,
and asks both.

**Deleting reverts rather than destroys** (p.185): "all object types using this
shared property will revert to regular properties". The failure mode being
guarded against is a cascade - a tidy-up of an ontology taking two object
types' properties, and their instances' values with them out of every
application that reads them.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.services import shared_properties as sp_service  # noqa: E402


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


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


def make_shared(client: TestClient, fx: Fixture, **over) -> dict:
    body = {
        "api_name": f"start_date_{uuid.uuid4().hex[:6]}",
        "display_name": "Start date",
        "description": "The day the employee or contractor began working",
        "data_type": "date",
        "visibility": "normal",
        **over,
    }
    r = client.post(
        f"{wbase(fx)}/shared-properties", headers=hdr(fx.editor_sub), json=body
    )
    assert r.status_code == 201, r.text
    return r.json()


def make_type(client: TestClient, fx: Fixture, properties: list[dict]) -> dict:
    tag = uuid.uuid4().hex[:6]
    r = client.post(
        f"{wbase(fx)}/object-types",
        headers=hdr(fx.editor_sub),
        json={
            "api_name": f"employee_{tag}",
            "display_name": f"Employee {tag}",
            "properties": properties,
            "title_property": properties[0]["api_name"],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def read_type(client: TestClient, fx: Fixture, type_id: str) -> dict:
    r = client.get(
        f"{wbase(fx)}/object-types/{type_id}", headers=hdr(fx.viewer_sub)
    )
    assert r.status_code == 200, r.text
    return r.json()


def prop_of(detail: dict, api_name: str) -> dict:
    return next(p for p in detail["properties"] if p["api_name"] == api_name)


def save_type(client: TestClient, fx: Fixture, detail: dict, **over):
    """Read-modify-write the way the editor does: send back the properties the
    read returned. **The one thing this proves on its own** is that the API can
    accept its own output - §163 shipped a version that could not."""
    body = {
        "display_name": detail["display_name"],
        "description": detail.get("description", ""),
        "properties": [
            {k: v for k, v in p.items() if k not in ("id", "sort_order",
                                                     "shared_property_api_name")}
            for p in detail["properties"]
        ],
        "title_property": detail["properties"][0]["api_name"],
        **over,
    }
    return client.patch(
        f"{wbase(fx)}/object-types/{detail['id']}",
        headers=hdr(fx.editor_sub),
        json=body,
    )


# ---- the definition itself (p.180-182) --------------------------------------
def test_a_shared_property_is_created_and_listed(client: TestClient, fx: Fixture) -> None:
    shared = make_shared(client, fx)
    assert shared["usage_count"] == 0
    r = client.get(f"{wbase(fx)}/shared-properties", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    assert shared["id"] in [s["id"] for s in r.json()]


def test_two_shared_properties_cannot_share_a_name(client: TestClient, fx: Fixture) -> None:
    shared = make_shared(client, fx)
    r = client.post(
        f"{wbase(fx)}/shared-properties",
        headers=hdr(fx.editor_sub),
        json={
            "api_name": shared["api_name"],
            "display_name": "Something else",
            "data_type": "string",
        },
    )
    assert r.status_code == 409, r.text


def test_a_formatter_that_does_not_fit_the_base_type_is_refused(
    client: TestClient, fx: Fixture
) -> None:
    """p.181 lists value formatting among shared metadata, so it goes through
    `services/value_format` - the same refusals a local formatter gets, and
    not a second copy of them."""
    r = client.post(
        f"{wbase(fx)}/shared-properties",
        headers=hdr(fx.editor_sub),
        json={
            "api_name": f"salary_{uuid.uuid4().hex[:6]}",
            "display_name": "Salary",
            "data_type": "string",
            "value_format": {"kind": "number", "style": "currency", "currency": "GBP"},
        },
    )
    assert r.status_code == 422, r.text


def test_a_viewer_cannot_create_one(client: TestClient, fx: Fixture) -> None:
    r = client.post(
        f"{wbase(fx)}/shared-properties",
        headers=hdr(fx.viewer_sub),
        json={"api_name": "nope", "display_name": "Nope", "data_type": "string"},
    )
    assert r.status_code == 403, r.text


# ---- using one on an object type (p.187-188) --------------------------------
def test_an_attached_property_takes_the_shared_metadata(
    client: TestClient, fx: Fixture
) -> None:
    """p.187: choosing a shared property *is* choosing its metadata. The
    request here deliberately declares a different display name and no
    description, and the read comes back with the shared property's."""
    shared = make_shared(client, fx)
    created = make_type(
        client,
        fx,
        [
            {"api_name": "name", "data_type": "string"},
            {
                "api_name": "began_on",
                "display_name": "Whatever this client called it",
                "data_type": "date",
                "shared_property_id": shared["id"],
            },
        ],
    )
    prop = prop_of(read_type(client, fx, created["id"]), "began_on")
    assert prop["display_name"] == "Start date"
    assert prop["description"] == shared["description"]
    assert prop["shared_property_id"] == shared["id"]
    # p.188: the property keeps its own api_name so downstream consumers
    # holding it keep working. This is the assertion that would fail if
    # attaching were implemented as "become the shared property".
    assert prop["api_name"] == "began_on"
    # p.178's globe needs a name, not just an id.
    assert prop["shared_property_api_name"] == shared["api_name"]


def test_a_base_type_that_does_not_match_is_refused(
    client: TestClient, fx: Fixture
) -> None:
    """p.181: "Base types … must match the column type in order to be applied
    on an object type." A date shared property over a string column is a
    formatter that never fires, discovered on a screen rather than on a save."""
    shared = make_shared(client, fx)
    tag = uuid.uuid4().hex[:6]
    r = client.post(
        f"{wbase(fx)}/object-types",
        headers=hdr(fx.editor_sub),
        json={
            "api_name": f"employee_{tag}",
            "display_name": "Employee",
            "properties": [
                {"api_name": "name", "data_type": "string"},
                {
                    "api_name": "began_on",
                    "data_type": "string",
                    "shared_property_id": shared["id"],
                },
            ],
        },
    )
    assert r.status_code == 422, r.text
    assert "base type" in r.text


def test_a_shared_property_from_another_workspace_is_refused(
    client: TestClient, fx: Fixture
) -> None:
    """The reference is workspace-scoped like the object types it joins, so an
    id from elsewhere is not found rather than quietly attached."""
    tag = uuid.uuid4().hex[:6]
    r = client.post(
        f"{wbase(fx)}/object-types",
        headers=hdr(fx.editor_sub),
        json={
            "api_name": f"employee_{tag}",
            "display_name": "Employee",
            "properties": [
                {
                    "api_name": "name",
                    "data_type": "string",
                    "shared_property_id": str(uuid.uuid4()),
                }
            ],
        },
    )
    assert r.status_code == 422, r.text
    assert "no shared property" in r.text


def test_editing_inherited_metadata_on_an_attached_property_is_refused(
    client: TestClient, fx: Fixture
) -> None:
    """p.188: "While associated with a shared property, direct edits to
    property metadata that is inherited from the shared property will be
    disabled."

    Disabled in a form has to be a refusal on the wire. The alternative -
    accepting the request and keeping the shared value - is somebody's edit
    vanishing with nothing to explain it, which is the bug this repo has now
    fixed four times in other places.
    """
    shared = make_shared(client, fx)
    created = make_type(
        client,
        fx,
        [
            {"api_name": "name", "data_type": "string"},
            {"api_name": "began_on", "data_type": "date",
             "shared_property_id": shared["id"]},
        ],
    )
    detail = read_type(client, fx, created["id"])
    prop_of(detail, "began_on")["display_name"] = "My own name for it"
    r = save_type(client, fx, detail)
    assert r.status_code == 422, r.text
    assert "cannot be set here" in r.text


def test_the_type_editor_can_save_back_what_it_read(
    client: TestClient, fx: Fixture
) -> None:
    """The read-modify-write round trip, which is the shape every editor uses.
    An API whose refusals reject its own output is one nobody can drive."""
    shared = make_shared(client, fx)
    created = make_type(
        client,
        fx,
        [
            {"api_name": "name", "data_type": "string"},
            {"api_name": "began_on", "data_type": "date",
             "shared_property_id": shared["id"]},
        ],
    )
    detail = read_type(client, fx, created["id"])
    r = save_type(client, fx, detail, display_name="Edited")
    assert r.status_code == 200, r.text
    after = prop_of(read_type(client, fx, created["id"]), "began_on")
    assert after["shared_property_id"] == shared["id"]
    assert after["display_name"] == "Start date"


def test_an_unrelated_edit_does_not_detach_the_property(
    client: TestClient, fx: Fixture
) -> None:
    """**The fifth time this repo has recorded this failure** (§157, §160, §163
    and the browser test beside it). An edit rewrites every property row, so
    any field the save path forgets to carry is silently reset by somebody
    changing a description."""
    shared = make_shared(client, fx)
    created = make_type(
        client,
        fx,
        [
            {"api_name": "name", "data_type": "string"},
            {"api_name": "began_on", "data_type": "date",
             "shared_property_id": shared["id"]},
        ],
    )
    detail = read_type(client, fx, created["id"])
    r = save_type(client, fx, detail, description="Some new description")
    assert r.status_code == 200, r.text
    assert prop_of(read_type(client, fx, created["id"]), "began_on")[
        "shared_property_id"
    ] == shared["id"]


def test_detaching_leaves_the_property_and_its_metadata(
    client: TestClient, fx: Fixture
) -> None:
    """p.188's Detach: "remove the association between the property and the
    shared property". The property stays, with what it had - detaching is not
    a way to lose a display name."""
    shared = make_shared(client, fx)
    created = make_type(
        client,
        fx,
        [
            {"api_name": "name", "data_type": "string"},
            {"api_name": "began_on", "data_type": "date",
             "shared_property_id": shared["id"]},
        ],
    )
    detail = read_type(client, fx, created["id"])
    prop_of(detail, "began_on")["shared_property_id"] = None
    assert save_type(client, fx, detail).status_code == 200
    after = prop_of(read_type(client, fx, created["id"]), "began_on")
    assert after["shared_property_id"] is None
    assert after["display_name"] == "Start date"
    # And now the local edit p.188 was disabling is allowed again.
    detail = read_type(client, fx, created["id"])
    prop_of(detail, "began_on")["display_name"] = "My own name for it"
    assert save_type(client, fx, detail).status_code == 200
    assert prop_of(read_type(client, fx, created["id"]), "began_on")[
        "display_name"
    ] == "My own name for it"


# ---- one place, several object types (p.178) --------------------------------
def test_editing_the_shared_property_reaches_every_object_type(
    client: TestClient, fx: Fixture
) -> None:
    """p.178's whole reason to exist: "update start date metadata in one place
    instead of on each object type".

    Two types, because one would pass against an implementation that copied the
    metadata at attach time and never looked at the shared property again.
    """
    shared = make_shared(client, fx)
    employee = make_type(
        client, fx,
        [{"api_name": "name", "data_type": "string"},
         {"api_name": "began_on", "data_type": "date",
          "shared_property_id": shared["id"]}],
    )
    contractor = make_type(
        client, fx,
        [{"api_name": "name", "data_type": "string"},
         {"api_name": "start_date", "data_type": "date",
          "shared_property_id": shared["id"]}],
    )
    r = client.patch(
        f"{wbase(fx)}/shared-properties/{shared['id']}",
        headers=hdr(fx.editor_sub),
        json={
            "display_name": "Started on",
            "description": "Renamed once, everywhere",
            "data_type": "date",
            "visibility": "prominent",
        },
    )
    assert r.status_code == 200, r.text
    for type_id, prop_name in ((employee["id"], "began_on"),
                               (contractor["id"], "start_date")):
        prop = prop_of(read_type(client, fx, type_id), prop_name)
        assert prop["display_name"] == "Started on"
        assert prop["description"] == "Renamed once, everywhere"
        assert prop["visibility"] == "prominent"


def test_usage_names_both_the_object_type_and_the_property(
    client: TestClient, fx: Fixture
) -> None:
    """p.191's Usage. The property's own api_name is in the row because p.188
    lets it differ - `began_on` here and `start_date` there are the same shared
    property, and a list that hid that would answer a different question."""
    shared = make_shared(client, fx)
    employee = make_type(
        client, fx,
        [{"api_name": "name", "data_type": "string"},
         {"api_name": "began_on", "data_type": "date",
          "shared_property_id": shared["id"]}],
    )
    r = client.get(
        f"{wbase(fx)}/shared-properties/{shared['id']}/usage",
        headers=hdr(fx.viewer_sub),
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    assert [(row["object_type_id"], row["property_api_name"]) for row in rows] == [
        (employee["id"], "began_on")
    ]
    r = client.get(
        f"{wbase(fx)}/shared-properties", headers=hdr(fx.viewer_sub)
    )
    listed = next(s for s in r.json() if s["id"] == shared["id"])
    assert listed["usage_count"] == 1


def test_changing_the_base_type_while_in_use_is_refused(
    client: TestClient, fx: Fixture
) -> None:
    """Foundry lists base type as editable and does not say what happens to the
    object types using it. Cascading would retype every attached property
    silently, which is the exact change `type_impact` exists to make somebody
    acknowledge - so this refuses and names who is in the way. Recorded as a
    divergence in `docs/parity/ontology.md`."""
    shared = make_shared(client, fx)
    employee = make_type(
        client, fx,
        [{"api_name": "name", "data_type": "string"},
         {"api_name": "began_on", "data_type": "date",
          "shared_property_id": shared["id"]}],
    )
    r = client.patch(
        f"{wbase(fx)}/shared-properties/{shared['id']}",
        headers=hdr(fx.editor_sub),
        json={"display_name": "Start date", "description": "",
              "data_type": "string", "visibility": "normal"},
    )
    assert r.status_code == 422, r.text
    assert employee["api_name"] in r.text
    # And it is still a date, rather than half-changed.
    r = client.get(
        f"{wbase(fx)}/shared-properties", headers=hdr(fx.viewer_sub)
    )
    assert next(s for s in r.json() if s["id"] == shared["id"])["data_type"] == "date"


def test_the_base_type_can_change_when_nothing_uses_it(
    client: TestClient, fx: Fixture
) -> None:
    """The refusal above is about consequences, not about base types being
    frozen - an unused definition is somebody still drafting it."""
    shared = make_shared(client, fx)
    r = client.patch(
        f"{wbase(fx)}/shared-properties/{shared['id']}",
        headers=hdr(fx.editor_sub),
        json={"display_name": "Start date", "description": "",
              "data_type": "string", "visibility": "normal"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data_type"] == "string"


# ---- deleting reverts (p.185) -----------------------------------------------
def test_deleting_a_shared_property_reverts_its_users(
    client: TestClient, fx: Fixture
) -> None:
    """p.185: "When a shared property is deleted, all object types using this
    shared property will revert to regular properties."

    **Not a cascade.** The properties survive with their metadata - a delete
    that took them would take their instances' values out of every application
    that reads them, as a side effect of tidying up an ontology.
    """
    shared = make_shared(client, fx)
    employee = make_type(
        client, fx,
        [{"api_name": "name", "data_type": "string"},
         {"api_name": "began_on", "data_type": "date",
          "shared_property_id": shared["id"]}],
    )
    r = client.delete(
        f"{wbase(fx)}/shared-properties/{shared['id']}", headers=hdr(fx.editor_sub)
    )
    assert r.status_code == 204, r.text

    detail = read_type(client, fx, employee["id"])
    assert {p["api_name"] for p in detail["properties"]} == {"name", "began_on"}
    prop = prop_of(detail, "began_on")
    assert prop["shared_property_id"] is None
    assert prop["shared_property_api_name"] is None
    # The last inherited metadata is what it reverts *to*, because the columns
    # were written at save time (db 0053). Reverting to a blank would make a
    # delete somewhere else erase a display name here.
    assert prop["display_name"] == "Start date"
    assert prop["data_type"] == "date"
    # And the property is editable again.
    detail = read_type(client, fx, employee["id"])
    prop_of(detail, "began_on")["display_name"] = "Mine now"
    assert save_type(client, fx, detail).status_code == 200


def test_deleting_one_that_nothing_uses_is_the_same_call(
    client: TestClient, fx: Fixture
) -> None:
    shared = make_shared(client, fx)
    r = client.delete(
        f"{wbase(fx)}/shared-properties/{shared['id']}", headers=hdr(fx.editor_sub)
    )
    assert r.status_code == 204, r.text
    assert client.get(
        f"{wbase(fx)}/shared-properties/{shared['id']}/usage",
        headers=hdr(fx.viewer_sub),
    ).status_code == 404


def test_a_viewer_cannot_delete_one(client: TestClient, fx: Fixture) -> None:
    shared = make_shared(client, fx)
    r = client.delete(
        f"{wbase(fx)}/shared-properties/{shared['id']}", headers=hdr(fx.viewer_sub)
    )
    assert r.status_code == 403, r.text


# ---- the resolve rule, without a database -----------------------------------
SHARED = {
    "api_name": "start_date",
    "display_name": "Start date",
    "description": "When they began",
    "data_type": "date",
    "visibility": "prominent",
    "value_format": {"kind": "datetime", "style": "date"},
}


def test_resolve_overlays_only_the_inherited_fields() -> None:
    prop = {
        "api_name": "began_on",
        "display_name": "Began on",
        "description": "",
        "data_type": "date",
        "visibility": "normal",
        "value_format": None,
        "required": True,
        "edit_only": True,
        "conditional_format": [{"comparison": "is_null"}],
    }
    out = sp_service.resolve(dict(prop), SHARED)
    assert out["display_name"] == "Start date"
    assert out["description"] == "When they began"
    assert out["visibility"] == "prominent"
    assert out["value_format"] == SHARED["value_format"]
    # p.188: the api_name is the property's own, and the three local settings
    # are not on p.181/p.184/p.190's list of shared metadata.
    assert out["api_name"] == "began_on"
    assert out["required"] is True
    assert out["edit_only"] is True
    assert out["conditional_format"] == prop["conditional_format"]


def test_resolve_leaves_an_unattached_property_alone() -> None:
    prop = {"api_name": "began_on", "display_name": "Began on"}
    assert sp_service.resolve(prop, None) == prop


def test_a_blank_description_is_not_an_edit() -> None:
    """Every inherited field has a value that cannot be confused with absence
    except this one: a client that never had a description sends `""`, and
    treating that as "set the description to empty" would refuse a request
    nobody meant to make."""
    sp_service.check_attachment(
        {"api_name": "began_on", "data_type": "date", "description": ""}, SHARED
    )
    with pytest.raises(sp_service.SharedPropertyError, match="description"):
        sp_service.check_attachment(
            {"api_name": "began_on", "data_type": "date",
             "description": "something of my own"},
            SHARED,
        )


def test_a_field_that_is_absent_is_not_an_edit() -> None:
    """A client sending only the fields it cares about is not contradicting
    anything."""
    sp_service.check_attachment({"api_name": "began_on", "data_type": "date"}, SHARED)
