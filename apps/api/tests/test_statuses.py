"""Statuses end to end (parity `docs/parity/ontology.md` §1.3; Foundry
`object-link-types` p.253-259).

`test_ontology_status.py` covers what the rules *say*, purely. This covers what
they *do*: the default a new resource gets, the delete p.256 refuses, and the
propagation p.256-257 performs when a type is demoted.

**The refusals are the feature.** p.253 says statuses exist so that somebody
editing the ontology knows which resources applications rely on - and knowing
is not the same as being stopped. A status column that let an `active` object
type be deleted would be the `required` flag before §154: displayed,
accepted, and enforcing nothing.
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


def make_type(client: TestClient, fx: Fixture, properties=None) -> dict:
    tag = uuid.uuid4().hex[:6]
    properties = properties or [{"api_name": "name", "data_type": "string"}]
    r = client.post(
        f"{wbase(fx)}/object-types",
        headers=hdr(fx.editor_sub),
        json={
            "api_name": f"thing_{tag}",
            "display_name": f"Thing {tag}",
            "properties": properties,
            # The first one given, rather than a hardcoded "name" - the link
            # test builds a type whose only property is `code`.
            "title_property": properties[0]["api_name"],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def read_type(client: TestClient, fx: Fixture, type_id: str) -> dict:
    r = client.get(f"{wbase(fx)}/object-types/{type_id}", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return r.json()


def save(client: TestClient, fx: Fixture, detail: dict, *, as_admin: bool = False, **over):
    """Save a whole definition the way the editor does.

    `as_admin` because p.255 restricts *applying* `promoted` to the ontology
    level (§175). Everything else in this file is an ordinary editor's edit,
    and saying which is which is part of what these tests assert.
    """
    body = {
        "display_name": detail["display_name"],
        "properties": [
            {k: v for k, v in p.items()
             if k in ("api_name", "data_type", "required", "description",
                      "visibility", "status", "deprecation")}
            for p in detail["properties"]
        ],
        "title_property": detail["properties"][0]["api_name"],
        **over,
    }
    return client.patch(
        f"{wbase(fx)}/object-types/{detail['id']}",
        headers=hdr(fx.admin_sub if as_admin else fx.editor_sub),
        json=body,
    )


# ---- the default (p.256) -----------------------------------------------------
def test_a_new_object_type_and_its_properties_are_experimental(
    client: TestClient, fx: Fixture
) -> None:
    """p.256: "By default, any new ontological resource will be given the
    `experimental` status." Both levels, because p.253 says *every* resource
    has one and a property that defaulted to `active` would be undeletable
    from the moment it was typed."""
    created = make_type(client, fx)
    detail = read_type(client, fx, created["id"])
    assert detail["status"] == "experimental"
    assert detail["properties"][0]["status"] == "experimental"


# ---- deletion (p.256) --------------------------------------------------------
def test_an_active_object_type_cannot_be_deleted(client: TestClient, fx: Fixture) -> None:
    """p.256: "A resource's status must be `experimental` or `deprecated`
    before it can be deleted." This is the refusal that makes the status mean
    something."""
    created = make_type(client, fx)
    assert save(client, fx, read_type(client, fx, created["id"]),
                status="active").status_code == 200

    r = client.delete(f"{wbase(fx)}/object-types/{created['id']}",
                      headers=hdr(fx.editor_sub))
    assert r.status_code == 422, r.text
    assert "mark it deprecated" in r.text
    # And it is still there.
    assert read_type(client, fx, created["id"])["status"] == "active"


def test_deprecating_it_makes_it_deletable_again(client: TestClient, fx: Fixture) -> None:
    """The refusal is a step, not a wall - which is why its message names the
    way through."""
    created = make_type(client, fx)
    detail = read_type(client, fx, created["id"])
    assert save(client, fx, detail, status="active").status_code == 200
    assert save(client, fx, read_type(client, fx, created["id"]),
                status="deprecated",
                deprecation={"reason": "Replaced", "deadline": "2026-12-31"},
                ).status_code == 200
    r = client.delete(f"{wbase(fx)}/object-types/{created['id']}",
                      headers=hdr(fx.editor_sub))
    assert r.status_code == 204, r.text


def test_an_experimental_object_type_deletes_without_ceremony(
    client: TestClient, fx: Fixture
) -> None:
    """The default state is the deletable one, so nothing about this feature
    gets in the way of somebody building."""
    created = make_type(client, fx)
    assert client.delete(f"{wbase(fx)}/object-types/{created['id']}",
                         headers=hdr(fx.editor_sub)).status_code == 204


def make_link(client: TestClient, fx: Fixture) -> tuple[dict, dict, dict]:
    tag = uuid.uuid4().hex[:6]
    a = make_type(client, fx, [{"api_name": "name", "data_type": "string"}])
    b = make_type(client, fx, [{"api_name": "code", "data_type": "string"}])
    r = client.post(
        f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"joins_{tag}", "display_name": "Joins",
              "from_type_id": a["id"], "to_type_id": b["id"],
              "cardinality": "one_to_many",
              "from_property": "name", "to_property": "code"},
    )
    assert r.status_code == 201, r.text
    return a, b, r.json()


def activate(client: TestClient, fx: Fixture, type_id: str) -> None:
    """Promote a type **and its properties**.

    Both are needed to get a link to `active`, and that is p.257 rather than
    ceremony: a link is capped by its object types *and* by the foreign key
    properties it joins on. Promoting the type alone leaves the join columns
    experimental - and p.258's asymmetry means promoting the type does not
    promote them for you.
    """
    detail = read_type(client, fx, type_id)
    for prop in detail["properties"]:
        prop["status"] = "active"
    assert save(client, fx, detail, status="active").status_code == 200


def set_link_status(client: TestClient, fx: Fixture, link: dict, status: str) -> dict:
    r = client.patch(
        f"{wbase(fx)}/link-types/{link['id']}", headers=hdr(fx.editor_sub),
        json={"from_property": link["from_property"],
              "to_property": link["to_property"], "status": status},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_a_link_cannot_be_more_ready_than_the_types_it_joins(
    client: TestClient, fx: Fixture
) -> None:
    """**p.257, and the cap rather than a warning.** Its troubleshooting
    section describes the invalid state as an *error somebody receives* -
    "an experimental object type cannot have an active link type". Storing the
    capped value instead makes that state unreachable, so there is nothing to
    troubleshoot.

    Both object types here are `experimental` (p.256's default), so asking for
    `active` gets `experimental`.
    """
    _, _, link = make_link(client, fx)
    assert link["status"] == "experimental", "p.256's default, here too"
    assert set_link_status(client, fx, link, "active")["status"] == "experimental"


def test_an_active_link_type_cannot_be_deleted(client: TestClient, fx: Fixture) -> None:
    """p.256 names link types among the resources a status protects - and
    getting one to `active` at all means promoting both its ends first, which
    is p.257 working."""
    a, b, link = make_link(client, fx)
    activate(client, fx, a["id"])
    activate(client, fx, b["id"])
    assert set_link_status(client, fx, link, "active")["status"] == "active"

    r = client.delete(f"{wbase(fx)}/link-types/{link['id']}", headers=hdr(fx.editor_sub))
    assert r.status_code == 422, r.text


def test_demoting_an_object_type_caps_its_link_on_the_next_save(
    client: TestClient, fx: Fixture
) -> None:
    """p.257: "If at least one object type in a link type is changed to
    `experimental`, the link type will automatically be changed to
    `experimental`." Here the cap is applied when the link is next written,
    which is the moment this platform has to enforce it."""
    a, b, link = make_link(client, fx)
    activate(client, fx, a["id"])
    activate(client, fx, b["id"])
    assert set_link_status(client, fx, link, "active")["status"] == "active"

    assert save(client, fx, read_type(client, fx, a["id"]),
                status="experimental").status_code == 200
    assert set_link_status(client, fx, link, "active")["status"] == "experimental"


# ---- propagation (p.256-258) -------------------------------------------------
def test_demoting_a_type_demotes_its_properties(client: TestClient, fx: Fixture) -> None:
    """p.256: "if an object type is changed from `active` to `experimental`,
    all of its properties will be marked `experimental` as well.\""""
    created = make_type(
        client, fx,
        [{"api_name": "name", "data_type": "string"},
         {"api_name": "code", "data_type": "string"}],
    )
    detail = read_type(client, fx, created["id"])
    for p in detail["properties"]:
        p["status"] = "active"
    assert save(client, fx, detail, status="active").status_code == 200
    after = read_type(client, fx, created["id"])
    assert {p["status"] for p in after["properties"]} == {"active"}

    assert save(client, fx, after, status="experimental").status_code == 200
    after = read_type(client, fx, created["id"])
    assert {p["status"] for p in after["properties"]} == {"experimental"}


def test_promoting_a_type_leaves_its_properties_alone(
    client: TestClient, fx: Fixture
) -> None:
    """**The asymmetry, and p.258 is explicit**: applying `active` to every
    property is "the option to also apply", not a consequence. A field still
    being built on an otherwise finished type stays experimental, rather than
    being declared production-ready by somebody finishing the type around it."""
    created = make_type(
        client, fx,
        [{"api_name": "name", "data_type": "string"},
         {"api_name": "half_built", "data_type": "string"}],
    )
    detail = read_type(client, fx, created["id"])
    assert save(client, fx, detail, status="active").status_code == 200
    after = read_type(client, fx, created["id"])
    assert {p["status"] for p in after["properties"]} == {"experimental"}
    assert after["status"] == "active"


def test_a_property_may_be_deprecated_on_an_active_type(
    client: TestClient, fx: Fixture
) -> None:
    """Propagation lowers and never raises, so a deprecated field on a live
    type keeps saying so."""
    created = make_type(
        client, fx,
        [{"api_name": "name", "data_type": "string"},
         {"api_name": "old_code", "data_type": "string"}],
    )
    detail = read_type(client, fx, created["id"])
    next(p for p in detail["properties"] if p["api_name"] == "old_code")["status"] = (
        "deprecated"
    )
    assert save(client, fx, detail, status="active").status_code == 200
    after = read_type(client, fx, created["id"])
    statuses = {p["api_name"]: p["status"] for p in after["properties"]}
    assert statuses["old_code"] == "deprecated"
    assert statuses["name"] == "experimental"


# ---- deprecation metadata (p.254) --------------------------------------------
def test_a_deprecated_type_records_why_and_by_when(client: TestClient, fx: Fixture) -> None:
    created = make_type(client, fx)
    assert save(
        client, fx, read_type(client, fx, created["id"]),
        status="deprecated",
        deprecation={"reason": "Replaced by Contact", "deadline": "2026-12-31"},
    ).status_code == 200
    after = read_type(client, fx, created["id"])
    assert after["deprecation"]["reason"] == "Replaced by Contact"
    assert after["deprecation"]["deadline"] == "2026-12-31"


def test_undeprecating_clears_the_note(client: TestClient, fx: Fixture) -> None:
    """A resource explaining why it was going to be deleted, after somebody
    decided not to, is worse than no note at all."""
    created = make_type(client, fx)
    assert save(client, fx, read_type(client, fx, created["id"]),
                status="deprecated", deprecation={"reason": "Going"},
                ).status_code == 200
    assert save(client, fx, read_type(client, fx, created["id"]),
                status="experimental").status_code == 200
    assert read_type(client, fx, created["id"])["deprecation"] is None


def test_deprecation_details_on_a_live_type_are_refused(
    client: TestClient, fx: Fixture
) -> None:
    created = make_type(client, fx)
    r = save(client, fx, read_type(client, fx, created["id"]),
             status="active", deprecation={"reason": "not really"})
    assert r.status_code == 422, r.text
    assert "only to a deprecated resource" in r.text


# ---- promoted is object types only (p.255) -----------------------------------
def test_a_property_cannot_be_promoted(client: TestClient, fx: Fixture) -> None:
    """p.255: `promoted` "applies only to object types"."""
    created = make_type(client, fx)
    detail = read_type(client, fx, created["id"])
    detail["properties"][0]["status"] = "promoted"
    r = save(client, fx, detail)
    assert r.status_code == 422, r.text
    assert "only to object types" in r.text


def test_an_object_type_can_be_promoted_and_then_not_deleted(
    client: TestClient, fx: Fixture
) -> None:
    """p.255: `promoted` "inherits similar operational protections of the
    active status, such as restrictions on deletion"."""
    created = make_type(client, fx)
    assert save(client, fx, read_type(client, fx, created["id"]),
                status="promoted", as_admin=True).status_code == 200
    assert client.delete(f"{wbase(fx)}/object-types/{created['id']}",
                         headers=hdr(fx.editor_sub)).status_code == 422


# ---- an old client keeps working ---------------------------------------------
def test_a_save_that_says_nothing_about_status_changes_nothing(
    client: TestClient, fx: Fixture
) -> None:
    """**The compatibility rule, and it is the one that could have gone wrong
    quietly.** The type editor sends the whole definition every time. If
    `status` defaulted to `experimental` on the way in rather than to
    *unchanged*, every save from a client that had never heard of statuses
    would silently demote a promoted object type - and demote its properties
    with it, by p.256's own propagation."""
    created = make_type(client, fx)
    assert save(client, fx, read_type(client, fx, created["id"]),
                status="active").status_code == 200

    r = client.patch(
        f"{wbase(fx)}/object-types/{created['id']}", headers=hdr(fx.editor_sub),
        json={"display_name": "Edited by an older client",
              "properties": [{"api_name": "name", "data_type": "string"}],
              "title_property": "name"},
    )
    assert r.status_code == 200, r.text
    assert read_type(client, fx, created["id"])["status"] == "active"


def test_a_link_is_capped_by_its_foreign_key_property_alone(
    client: TestClient, fx: Fixture
) -> None:
    """p.257: "The same requirements are true of foreign keys of a link type."

    Isolated from the object types' own statuses, which is the only way to
    know this rule is doing anything: both types are fully `active`, and the
    one thing holding the link back is the property it joins on. Reachable
    because propagation only ever *lowers* - an active type may carry a
    property somebody has deliberately left experimental.
    """
    a, b, link = make_link(client, fx)
    activate(client, fx, a["id"])
    activate(client, fx, b["id"])
    assert set_link_status(client, fx, link, "active")["status"] == "active"

    detail = read_type(client, fx, a["id"])
    next(p for p in detail["properties"] if p["api_name"] == "name")["status"] = (
        "experimental"
    )
    assert save(client, fx, detail, status="active").status_code == 200
    assert set_link_status(client, fx, link, "active")["status"] == "experimental"


def test_a_link_is_capped_by_an_object_type_with_no_join_property(
    client: TestClient, fx: Fixture
) -> None:
    """The other half of p.257, isolated - and it needs a link joining on
    `$primary_key` to isolate it at all.

    An object type's status and its properties' statuses cannot be pulled
    apart from *above*: propagation demotes the properties with the type. But
    `$primary_key` is a sentinel, not a property row (db 0027), so a link
    joining on it has no far-side property status to be capped by - leaving the
    object type's own status as the only thing that can hold it back.
    """
    tag = uuid.uuid4().hex[:6]
    a = make_type(client, fx, [{"api_name": "name", "data_type": "string"}])
    b = make_type(client, fx, [{"api_name": "code", "data_type": "string"}])
    r = client.post(
        f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"bykey_{tag}", "display_name": "By key",
              "from_type_id": a["id"], "to_type_id": b["id"],
              "cardinality": "one_to_many",
              "from_property": "name", "to_property": "$primary_key"},
    )
    assert r.status_code == 201, r.text
    link = r.json()

    activate(client, fx, a["id"])
    # `b` stays experimental, and has no join property of its own.
    assert set_link_status(client, fx, link, "active")["status"] == "experimental"

    activate(client, fx, b["id"])
    assert set_link_status(client, fx, link, "active")["status"] == "active"


def test_deprecation_details_on_a_live_property_are_refused(
    client: TestClient, fx: Fixture
) -> None:
    """p.254's metadata belongs to a deprecated resource, at both levels. A
    deadline on an active property is a date nothing will act on."""
    created = make_type(client, fx)
    detail = read_type(client, fx, created["id"])
    detail["properties"][0]["deprecation"] = {"reason": "not really"}
    r = save(client, fx, detail)
    assert r.status_code == 422, r.text
    assert "only to a deprecated resource" in r.text
