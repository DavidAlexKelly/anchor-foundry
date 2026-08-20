"""Action type statuses (parity `docs/parity/ontology.md` §1.3; Foundry
`object-link-types` p.253-259).

> "Every object type, property, link type, **action**, or interface in the
> Ontology has a status that indicates developmental state." (p.253)

§170 built statuses for the other three kinds and left the `action_types`
column with nothing enforcing it. This closes that, and the interesting part is
not the column - it is a hole the column made visible.

**The cascade walks around p.256.** `action_types.object_type_id` is
`ON DELETE CASCADE` (db 0013), so deleting an object type deletes its actions
whatever their status. p.256 says an `active` resource cannot be deleted; a
cascade deletes one without ever demoting it, and without anything on screen
saying an action somebody relied on has gone. Link types are safe from the same
hole for a reason that does not apply here: §170 caps a link at the weakest
status of its two object types (p.257), so an `active` link on an experimental
object type is a state the ontology cannot hold. **Actions are not capped** -
p.257's table is about link types and says nothing about actions - so the
protection has to be a refusal instead.

That asymmetry is deliberate and is the thing most worth a test: no cap, and
therefore an explicit check.
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


def make_type(client: TestClient, fx: Fixture) -> dict:
    tag = uuid.uuid4().hex[:6]
    r = client.post(
        f"{wbase(fx)}/object-types",
        headers=hdr(fx.editor_sub),
        json={
            "api_name": f"ticket_{tag}",
            "display_name": f"Ticket {tag}",
            "properties": [
                {"api_name": "id", "display_name": "Id", "data_type": "string"},
                {"api_name": "state", "display_name": "State", "data_type": "string"},
            ],
            "title_property": "id",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def make_action(client: TestClient, fx: Fixture, type_id: str, **over) -> dict:
    body = {
        "object_type_id": type_id,
        "api_name": f"close_{uuid.uuid4().hex[:6]}",
        "display_name": "Close it",
        "editable_properties": ["state"],
        **over,
    }
    r = client.post(f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub), json=body)
    assert r.status_code == 201, r.text
    return r.json()


def set_status(client: TestClient, fx: Fixture, action_id: str, **body):
    return client.patch(
        f"{wbase(fx)}/action-types/{action_id}",
        headers=hdr(fx.editor_sub),
        json=body,
    )


def read_action(client: TestClient, fx: Fixture, action_id: str) -> dict:
    r = client.get(f"{wbase(fx)}/action-types/{action_id}", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return r.json()


# ---- p.253's claim, applied to the kind that had a column and no rules -----
def test_a_new_action_is_experimental(client: TestClient, fx: Fixture) -> None:
    """p.256: "By default, any new ontological resource will be given the
    `experimental` status." An action is one of p.253's five kinds."""
    kind = make_type(client, fx)
    assert make_action(client, fx, kind["id"])["status"] == "experimental"


def test_a_status_can_be_set_and_read_back(client: TestClient, fx: Fixture) -> None:
    kind = make_type(client, fx)
    action = make_action(client, fx, kind["id"])

    r = set_status(client, fx, action["id"], status="active")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "active"
    assert read_action(client, fx, action["id"])["status"] == "active"


def test_promoted_is_refused_on_an_action(client: TestClient, fx: Fixture) -> None:
    """p.255: `promoted` "applies only to object types. It is not available for
    properties, link types, **action types** or interfaces." Named explicitly
    in the source, so this is the spec rather than an inference."""
    kind = make_type(client, fx)
    action = make_action(client, fx, kind["id"])

    r = set_status(client, fx, action["id"], status="promoted")
    assert r.status_code == 422, r.text
    assert "object types" in r.text

    created = client.post(
        f"{wbase(fx)}/action-types",
        headers=hdr(fx.editor_sub),
        json={
            "object_type_id": kind["id"],
            "api_name": "born_promoted",
            "display_name": "Nope",
            "editable_properties": ["state"],
            "status": "promoted",
        },
    )
    assert created.status_code == 422, created.text


def test_an_omitted_status_means_unchanged(client: TestClient, fx: Fixture) -> None:
    """**§170's compatibility rule, and it bites harder here.** This is the
    only endpoint that writes an action's status, so a missing field treated as
    the documented default for a *new* resource would demote an action every
    time a client predating statuses touched it."""
    kind = make_type(client, fx)
    action = make_action(client, fx, kind["id"])
    assert set_status(client, fx, action["id"], status="active").status_code == 200

    r = client.patch(
        f"{wbase(fx)}/action-types/{action['id']}",
        headers=hdr(fx.editor_sub),
        json={},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "active"


# ---- p.256's refusals -------------------------------------------------------
def test_an_active_action_cannot_be_deleted(client: TestClient, fx: Fixture) -> None:
    """p.256: "A resource's status must be `experimental` or `deprecated`
    before it can be deleted." The refusal names the way through."""
    kind = make_type(client, fx)
    action = make_action(client, fx, kind["id"])
    assert set_status(client, fx, action["id"], status="active").status_code == 200

    r = client.delete(
        f"{wbase(fx)}/action-types/{action['id']}", headers=hdr(fx.editor_sub)
    )
    assert r.status_code == 422, r.text
    assert "mark it deprecated" in r.text

    # And it comes back when the status allows it.
    assert set_status(client, fx, action["id"], status="deprecated").status_code == 200
    assert client.delete(
        f"{wbase(fx)}/action-types/{action['id']}", headers=hdr(fx.editor_sub)
    ).status_code == 204


def test_a_deprecation_note_is_kept_and_then_cleared(
    client: TestClient, fx: Fixture
) -> None:
    """p.254's why/by-when, refused anywhere but a deprecated resource and
    cleared when one stops being deprecated."""
    kind = make_type(client, fx)
    action = make_action(client, fx, kind["id"])

    r = set_status(
        client, fx, action["id"],
        status="deprecated",
        deprecation={"reason": "Replaced by close_v2", "deadline": "2026-12-31"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["deprecation"]["reason"] == "Replaced by close_v2"

    moved = set_status(client, fx, action["id"], status="experimental")
    assert moved.status_code == 200, moved.text
    assert moved.json()["deprecation"] is None


def test_a_note_on_a_live_action_is_refused(client: TestClient, fx: Fixture) -> None:
    kind = make_type(client, fx)
    action = make_action(client, fx, kind["id"])
    r = set_status(
        client, fx, action["id"], status="active", deprecation={"reason": "no"},
    )
    assert r.status_code == 422, r.text


# ---- the hole the column made visible --------------------------------------
def test_deleting_an_object_type_will_not_take_an_active_action_with_it(
    client: TestClient, fx: Fixture
) -> None:
    """**The cascade that walks around p.256.**

    `action_types.object_type_id` is ON DELETE CASCADE (db 0013), so without a
    check an `active` action is deleted by deleting the *experimental* object
    type it belongs to - p.256's protection bypassed without ever demoting the
    thing it protects, and nothing anywhere saying an action somebody relied on
    has gone.

    The object type here is `experimental` throughout, so it is deletable on
    its own terms; the only thing in the way is what the delete would take.
    """
    kind = make_type(client, fx)
    action = make_action(client, fx, kind["id"])
    assert set_status(client, fx, action["id"], status="active").status_code == 200

    r = client.delete(
        f"{wbase(fx)}/object-types/{kind['id']}", headers=hdr(fx.editor_sub)
    )
    assert r.status_code == 422, r.text
    assert action["api_name"] in r.text
    # Still there, both of them.
    assert read_action(client, fx, action["id"])["status"] == "active"

    # Demote it and the delete goes through, taking the action with it - which
    # is now a deletion somebody chose rather than one they did not see.
    assert set_status(client, fx, action["id"], status="deprecated").status_code == 200
    assert client.delete(
        f"{wbase(fx)}/object-types/{kind['id']}", headers=hdr(fx.editor_sub)
    ).status_code == 204


def test_an_experimental_action_does_not_block_the_delete(
    client: TestClient, fx: Fixture
) -> None:
    """The other half, and the one that stops the check from being a wall: an
    ordinary half-built action is exactly what p.256 says may be deleted."""
    kind = make_type(client, fx)
    make_action(client, fx, kind["id"])
    r = client.delete(
        f"{wbase(fx)}/object-types/{kind['id']}", headers=hdr(fx.editor_sub)
    )
    assert r.status_code == 204, r.text


def test_the_refusal_names_every_action_in_the_way(
    client: TestClient, fx: Fixture
) -> None:
    """One name is a hint; all of them is a list somebody can work through."""
    kind = make_type(client, fx)
    first = make_action(client, fx, kind["id"])
    second = make_action(client, fx, kind["id"])
    for action in (first, second):
        assert set_status(client, fx, action["id"], status="active").status_code == 200

    r = client.delete(
        f"{wbase(fx)}/object-types/{kind['id']}", headers=hdr(fx.editor_sub)
    )
    assert r.status_code == 422, r.text
    assert first["api_name"] in r.text and second["api_name"] in r.text


def test_an_action_is_not_capped_by_its_object_type(
    client: TestClient, fx: Fixture
) -> None:
    """**A deliberate divergence from what a reader might expect**, and the
    reason the check above has to exist.

    p.257 caps a *link type* at the weakest status of its two object types, and
    §170 implements that. It says nothing about actions, and its own
    explanation is specific to links - a foreign key may be in production
    "while the link type and its backing datasource are still in development".
    Extending the cap to actions would be inventing a rule and would silently
    demote actions nobody asked to demote, so it is not extended.
    """
    kind = make_type(client, fx)
    action = make_action(client, fx, kind["id"])
    assert set_status(client, fx, action["id"], status="active").status_code == 200

    # The object type is still experimental, and the action stays active.
    assert read_action(client, fx, action["id"])["status"] == "active"
    listed = client.get(
        f"{wbase(fx)}/object-types/{kind['id']}", headers=hdr(fx.viewer_sub)
    ).json()
    assert listed["status"] == "experimental"


# ---- roles ------------------------------------------------------------------
def test_a_viewer_cannot_change_a_status(client: TestClient, fx: Fixture) -> None:
    kind = make_type(client, fx)
    action = make_action(client, fx, kind["id"])
    r = client.patch(
        f"{wbase(fx)}/action-types/{action['id']}",
        headers=hdr(fx.viewer_sub),
        json={"status": "active"},
    )
    assert r.status_code == 403, r.text


def test_an_unknown_action_is_a_404(client: TestClient, fx: Fixture) -> None:
    r = set_status(client, fx, str(uuid.uuid4()), status="active")
    assert r.status_code == 404, r.text
