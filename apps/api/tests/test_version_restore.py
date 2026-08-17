"""A restore restores the whole definition (`docs/parity/ontology.md` §6;
Foundry `ontology-manager` TOC §7-8).

**This file exists because of a defect that shipped five times.**
`object_type_versions` recorded six fields per property. Every unit that added
a seventh - visibility (§42), value formatting (§157), conditional formatting
(§158), edit-only (§160), derived properties (§161) - added a column to
`object_type_properties` and did not notice the snapshot. The consequence was
silent and one-directional: rolling back to *any* earlier version erased the
lot, with no error and nothing in the history to say it had happened. Found
while adding `shared_property_id` (§164), which would have been the sixth.

So the claim under test is not "restore works" - `test_ontology_history.py`
already asserts that - but **"a restore puts back everything a property had"**,
and it is asserted one field at a time on purpose. There is no general test for
this: the failure is a *missing key*, and only a test that names the key can
see it missing. A new column on `object_type_properties` needs a new test here,
and `services/ontology._snapshot_version` says so.
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


def make_type(client: TestClient, fx: Fixture, properties: list[dict]) -> dict:
    tag = uuid.uuid4().hex[:6]
    r = client.post(
        f"{wbase(fx)}/object-types",
        headers=hdr(fx.editor_sub),
        json={
            "api_name": f"restorable_{tag}",
            "display_name": f"Restorable {tag}",
            "properties": properties,
            "title_property": properties[0]["api_name"],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def read_type(client: TestClient, fx: Fixture, type_id: str) -> dict:
    r = client.get(f"{wbase(fx)}/object-types/{type_id}", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return r.json()


def prop_of(detail: dict, api_name: str) -> dict:
    return next(p for p in detail["properties"] if p["api_name"] == api_name)


def save(client: TestClient, fx: Fixture, type_id: str, properties: list[dict], **over):
    """Replace the definition. The version that records it is appended by the
    save, which is what makes the *next* edit a thing to roll back from."""
    return client.patch(
        f"{wbase(fx)}/object-types/{type_id}",
        headers=hdr(fx.editor_sub),
        json={
            "display_name": "Restorable",
            "properties": properties,
            "title_property": properties[0]["api_name"],
            **over,
        },
    )


def restore(client: TestClient, fx: Fixture, type_id: str, version: int, **body):
    return client.post(
        f"{wbase(fx)}/object-types/{type_id}/versions/{version}/restore",
        headers=hdr(fx.editor_sub),
        json=body,
    )


def round_trip(
    client: TestClient,
    fx: Fixture,
    *,
    configured: dict,
    stripped: dict,
) -> dict:
    """Create a property with `configured`, save it stripped back to
    `stripped`, then roll back - and return the property as it comes out.

    The middle step matters: restoring onto a definition that already has the
    setting would pass even if the snapshot recorded nothing at all.
    """
    created = make_type(
        client, fx,
        [{"api_name": "subject", "data_type": "string"},
         {"api_name": "field", **configured}],
    )
    assert save(
        client, fx, created["id"],
        [{"api_name": "subject", "data_type": "string"},
         {"api_name": "field", **stripped}],
    ).status_code == 200
    # Gone, which is what makes the restore a real question.
    assert restore(client, fx, created["id"], 1).status_code == 200
    return prop_of(read_type(client, fx, created["id"]), "field")


# ---- one test per field, because the failure is a missing key ---------------
def test_a_restore_puts_back_visibility(client: TestClient, fx: Fixture) -> None:
    """§42's field, and the first one the snapshot silently dropped."""
    restored = round_trip(
        client, fx,
        configured={"data_type": "string", "visibility": "prominent"},
        stripped={"data_type": "string", "visibility": "normal"},
    )
    assert restored["visibility"] == "prominent"


def test_a_restore_puts_back_value_formatting(client: TestClient, fx: Fixture) -> None:
    """§157's, `object-link-types` p.94-101."""
    formatter = {"kind": "number", "style": "currency", "currency": "GBP"}
    restored = round_trip(
        client, fx,
        configured={"data_type": "integer", "value_format": formatter},
        stripped={"data_type": "integer", "value_format": None},
    )
    assert restored["value_format"] == formatter


def test_a_restore_puts_back_conditional_formatting(client: TestClient, fx: Fixture) -> None:
    """§158's, p.102-109."""
    rules = [{"kind": "standard", "property": "field", "comparison": "is_null",
              "colour": "#ff0000"}]
    restored = round_trip(
        client, fx,
        configured={"data_type": "string", "conditional_format": rules},
        stripped={"data_type": "string", "conditional_format": None},
    )
    assert restored["conditional_format"] == rules


def test_a_restore_puts_back_edit_only(client: TestClient, fx: Fixture) -> None:
    """§160's, p.113. The one whose loss is not merely cosmetic: an edit-only
    property that comes back as an ordinary one is a property the next sync
    will report as missing on every row, because nothing maps it."""
    restored = round_trip(
        client, fx,
        configured={"data_type": "string", "edit_only": True},
        stripped={"data_type": "string", "edit_only": False},
    )
    assert restored["edit_only"] is True


def test_a_restore_puts_back_required(client: TestClient, fx: Fixture) -> None:
    """§154's. Already in the snapshot before this unit - asserted anyway,
    because a test suite that only covers the fields somebody once forgot is a
    suite that will not notice the next one going missing."""
    restored = round_trip(
        client, fx,
        configured={"data_type": "string", "required": True},
        stripped={"data_type": "string", "required": False},
    )
    assert restored["required"] is True


def test_a_restore_puts_back_a_shared_property(client: TestClient, fx: Fixture) -> None:
    """§164's, p.187. The sixth, and the one that made the other five visible."""
    r = client.post(
        f"{wbase(fx)}/shared-properties",
        headers=hdr(fx.editor_sub),
        json={"api_name": f"restorable_{uuid.uuid4().hex[:6]}",
              "display_name": "Shared once", "data_type": "string"},
    )
    assert r.status_code == 201, r.text
    shared = r.json()
    restored = round_trip(
        client, fx,
        configured={"data_type": "string", "shared_property_id": shared["id"]},
        stripped={"data_type": "string", "shared_property_id": None},
    )
    assert restored["shared_property_id"] == shared["id"]
    # And the metadata comes back with it, since it is resolved from the
    # shared property rather than stored twice.
    assert restored["display_name"] == "Shared once"


def test_a_restore_puts_back_a_derivation(client: TestClient, fx: Fixture) -> None:
    """§161's, p.143. Needs a second object type and a link, because a
    derivation is only legal against links that exist."""
    tag = uuid.uuid4().hex[:6]
    far = make_type(client, fx, [{"api_name": "code", "data_type": "string"}])
    near = make_type(
        client, fx,
        [{"api_name": "subject", "data_type": "string"},
         {"api_name": "far_code", "data_type": "string"}],
    )
    r = client.post(
        f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"points_at_{tag}", "display_name": "Points at",
              "from_type_id": near["id"], "to_type_id": far["id"],
              "cardinality": "one_to_many",
              "from_property": "far_code", "to_property": "code"},
    )
    assert r.status_code == 201, r.text
    link = r.json()

    derivation = {"links": [{"link_type_id": link["id"], "far_type_id": far["id"]}],
                  "far_type_id": far["id"], "property": "code"}
    props = [{"api_name": "subject", "data_type": "string"},
             {"api_name": "far_code", "data_type": "string"},
             {"api_name": "borrowed", "data_type": "string", "derivation": derivation}]
    assert save(client, fx, near["id"], props).status_code == 200
    # v2 has it; v3 does not.
    assert save(client, fx, near["id"], [
        {"api_name": "subject", "data_type": "string"},
        {"api_name": "far_code", "data_type": "string"},
        {"api_name": "borrowed", "data_type": "string", "derivation": None},
    ]).status_code == 200
    assert prop_of(read_type(client, fx, near["id"]), "borrowed")["derivation"] is None

    assert restore(client, fx, near["id"], 2).status_code == 200
    restored = prop_of(read_type(client, fx, near["id"]), "borrowed")["derivation"]
    assert restored is not None
    assert restored["property"] == "code"
    assert [h["link_type_id"] for h in restored["links"]] == [link["id"]]


# ---- what a restore does when the thing it referred to is gone --------------
def test_a_restore_forgets_a_shared_property_that_was_deleted(
    client: TestClient, fx: Fixture
) -> None:
    """p.185 already decided this: deleting a shared property "reverts" its
    users to regular properties. A version that recorded an attachment to a
    since-deleted one therefore restores as a regular property rather than
    refusing - refusing would let a delete elsewhere block a rollback here
    over a decision the delete had already made."""
    r = client.post(
        f"{wbase(fx)}/shared-properties",
        headers=hdr(fx.editor_sub),
        json={"api_name": f"doomed_{uuid.uuid4().hex[:6]}",
              "display_name": "Doomed", "data_type": "string"},
    )
    shared = r.json()
    created = make_type(
        client, fx,
        [{"api_name": "subject", "data_type": "string"},
         {"api_name": "field", "data_type": "string",
          "shared_property_id": shared["id"]}],
    )
    assert save(client, fx, created["id"], [
        {"api_name": "subject", "data_type": "string"},
        {"api_name": "field", "data_type": "string", "shared_property_id": None},
    ]).status_code == 200
    assert client.delete(
        f"{wbase(fx)}/shared-properties/{shared['id']}", headers=hdr(fx.editor_sub)
    ).status_code == 204

    assert restore(client, fx, created["id"], 1).status_code == 200
    restored = prop_of(read_type(client, fx, created["id"]), "field")
    assert restored["shared_property_id"] is None
    # The property itself survives - the restore is not a delete.
    assert restored["api_name"] == "field"


def test_a_restore_refuses_a_derivation_whose_link_is_gone(
    client: TestClient, fx: Fixture
) -> None:
    """The other half of the asymmetry above, and the reason it is not
    inconsistent. Nothing documents what a derived property becomes when its
    chain stops joining up. Dropping it would put back a version that is not
    the version; keeping it would produce a column of blanks. So the restore
    refuses, and says which property it could not honour."""
    tag = uuid.uuid4().hex[:6]
    far = make_type(client, fx, [{"api_name": "code", "data_type": "string"}])
    near = make_type(
        client, fx,
        [{"api_name": "subject", "data_type": "string"},
         {"api_name": "far_code", "data_type": "string"}],
    )
    link = client.post(
        f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"points_at_{tag}", "display_name": "Points at",
              "from_type_id": near["id"], "to_type_id": far["id"],
              "cardinality": "one_to_many",
              "from_property": "far_code", "to_property": "code"},
    ).json()

    assert save(client, fx, near["id"], [
        {"api_name": "subject", "data_type": "string"},
        {"api_name": "far_code", "data_type": "string"},
        {"api_name": "borrowed", "data_type": "string",
         "derivation": {"links": [{"link_type_id": link["id"],
                                   "far_type_id": far["id"]}],
                        "far_type_id": far["id"], "property": "code"}},
    ]).status_code == 200
    assert save(client, fx, near["id"], [
        {"api_name": "subject", "data_type": "string"},
        {"api_name": "far_code", "data_type": "string"},
    ], acknowledge_breaking=True).status_code == 200
    assert client.delete(
        f"{wbase(fx)}/link-types/{link['id']}", headers=hdr(fx.editor_sub)
    ).status_code == 204

    r = restore(client, fx, near["id"], 2, acknowledge_breaking=True)
    assert r.status_code == 422, r.text
    assert "borrowed" in r.text


# ---- and the version record itself ------------------------------------------
def test_a_version_records_the_fields_it_restores(client: TestClient, fx: Fixture) -> None:
    """The listing carries them too, because a history that shows six of a
    property's twelve fields invites somebody to conclude the other six were
    never set."""
    created = make_type(
        client, fx,
        [{"api_name": "subject", "data_type": "string"},
         {"api_name": "field", "data_type": "integer", "visibility": "hidden",
          "edit_only": True,
          "value_format": {"kind": "number", "style": "percent"}}],
    )
    r = client.get(
        f"{wbase(fx)}/object-types/{created['id']}/versions", headers=hdr(fx.viewer_sub)
    )
    assert r.status_code == 200, r.text
    snapshot = next(
        p for p in r.json()[0]["properties"] if p["api_name"] == "field"
    )
    assert snapshot["visibility"] == "hidden"
    assert snapshot["edit_only"] is True
    assert snapshot["value_format"] == {"kind": "number", "style": "percent"}
    assert snapshot["derivation"] is None
    assert snapshot["shared_property_id"] is None
