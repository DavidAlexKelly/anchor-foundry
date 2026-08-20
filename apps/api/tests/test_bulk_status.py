"""Bulk status editing (parity `docs/parity/ontology.md` §1.3; Foundry
`object-link-types` p.258).

p.258 gives three things §170 left out, and the third is the one with a
decision in it.

> "When changing an object type from `experimental` to `active`, there is the
> option to also apply the `active` status to all properties on the object
> type." (p.258)

**An option, not a consequence.** §170 made propagation lower-only on purpose -
a half-built property should not be declared production-ready by somebody
finishing the type around it. p.258's checkbox is the explicit way past that,
which is why it is a parameter rather than a rule.

> "Statuses across properties of an object type can also be edited in bulk from
> the Properties page… Statuses across object types can also be edited in bulk
> from the home page object view page." (p.258)

**A bulk edit is a way round every rule it forgets.** So both paths run the
same pure functions the single-type path does: p.255's promotion role, p.255's
visibility, p.256's propagation, p.257's link re-cap. The tests below are
mostly one per rule, asserting the bulk path did not become a back door.

**And properties are capped at their object type.** p.256's propagation runs on
every save of a type, so a bulk edit that raised a property above its type
would create a state the next unrelated save silently undoes - the
carry-through failure in a new place. Capping refuses to create it at all.
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


def make_type(client: TestClient, fx: Fixture, props=None) -> dict:
    tag = uuid.uuid4().hex[:6]
    props = props or [
        {"api_name": "name", "data_type": "string"},
        {"api_name": "code", "data_type": "string"},
    ]
    r = client.post(
        f"{wbase(fx)}/object-types",
        headers=hdr(fx.editor_sub),
        json={
            "api_name": f"thing_{tag}", "display_name": f"Thing {tag}",
            "properties": props, "title_property": props[0]["api_name"],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def read_type(client: TestClient, fx: Fixture, type_id: str) -> dict:
    r = client.get(f"{wbase(fx)}/object-types/{type_id}", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return r.json()


def bulk_types(client: TestClient, fx: Fixture, *, sub=None, **body):
    return client.post(
        f"{wbase(fx)}/object-types/bulk-status",
        headers=hdr(sub or fx.editor_sub), json=body,
    )


def bulk_props(client: TestClient, fx: Fixture, type_id: str, **body):
    return client.post(
        f"{wbase(fx)}/object-types/{type_id}/property-statuses",
        headers=hdr(fx.editor_sub), json=body,
    )


def statuses_of(detail: dict) -> dict[str, str]:
    return {p["api_name"]: p["status"] for p in detail["properties"]}


# ---- p.258's object type bulk edit ------------------------------------------
def test_several_types_change_together(client: TestClient, fx: Fixture) -> None:
    """p.258's Edit status button, over the checkboxes somebody ticked."""
    a, b = make_type(client, fx), make_type(client, fx)
    r = bulk_types(client, fx, object_type_ids=[a["id"], b["id"]], status="active")
    assert r.status_code == 200, r.text
    assert {t["status"] for t in r.json()} == {"active"}
    assert read_type(client, fx, a["id"])["status"] == "active"
    assert read_type(client, fx, b["id"])["status"] == "active"


def test_the_response_names_only_the_types_asked_for(
    client: TestClient, fx: Fixture
) -> None:
    """The workspace has other types; a bulk edit that answered with all of
    them would make the response useless for saying what changed."""
    a = make_type(client, fx)
    make_type(client, fx)  # untouched
    r = bulk_types(client, fx, object_type_ids=[a["id"]], status="example")
    assert [t["id"] for t in r.json()] == [a["id"]], r.json()


def test_a_bulk_demotion_still_propagates_to_properties(
    client: TestClient, fx: Fixture
) -> None:
    """p.256's propagation is not something the bulk path may skip - a rule a
    bulk edit forgets is a rule with a way round it."""
    a = make_type(client, fx)
    assert bulk_types(client, fx, object_type_ids=[a["id"]], status="active").status_code == 200
    assert bulk_props(
        client, fx, a["id"], api_names=["name", "code"], status="active"
    ).status_code == 200

    assert bulk_types(
        client, fx, object_type_ids=[a["id"]], status="experimental"
    ).status_code == 200
    assert statuses_of(read_type(client, fx, a["id"])) == {
        "name": "experimental", "code": "experimental",
    }


def test_a_bulk_demotion_still_caps_the_link_types(
    client: TestClient, fx: Fixture
) -> None:
    """p.257 and §176: the cap is an event on the object type. The bulk path
    is another way to cause that event."""
    a = make_type(client, fx, [{"api_name": "name", "data_type": "string"}])
    b = make_type(client, fx, [{"api_name": "code", "data_type": "string"}])
    link = client.post(
        f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"j_{uuid.uuid4().hex[:6]}", "display_name": "J",
              "from_type_id": a["id"], "to_type_id": b["id"],
              "cardinality": "one_to_many",
              "from_property": "name", "to_property": "code"},
    ).json()

    assert bulk_types(
        client, fx, object_type_ids=[a["id"], b["id"]], status="active",
        apply_to_properties=True,
    ).status_code == 200
    assert client.patch(
        f"{wbase(fx)}/link-types/{link['id']}", headers=hdr(fx.editor_sub),
        json={"from_property": "name", "to_property": "code", "status": "active"},
    ).json()["status"] == "active"

    assert bulk_types(
        client, fx, object_type_ids=[a["id"]], status="experimental"
    ).status_code == 200
    links = client.get(f"{wbase(fx)}/link-types", headers=hdr(fx.viewer_sub)).json()
    assert next(l for l in links if l["id"] == link["id"])["status"] == "experimental"


def test_a_bulk_promotion_needs_the_ontology_level(
    client: TestClient, fx: Fixture
) -> None:
    """p.255's role, which a bulk endpoint would otherwise be a way round."""
    a = make_type(client, fx)
    r = bulk_types(client, fx, object_type_ids=[a["id"]], status="promoted")
    assert r.status_code == 422, r.text
    assert read_type(client, fx, a["id"])["status"] == "experimental"

    ok = bulk_types(
        client, fx, object_type_ids=[a["id"]], status="promoted", sub=fx.admin_sub
    )
    assert ok.status_code == 200, ok.text
    # p.255's visibility rule reaches the bulk path too.
    assert read_type(client, fx, a["id"])["visibility"] == "prominent"


def test_one_refusal_changes_nothing(client: TestClient, fx: Fixture) -> None:
    """**All or nothing.** A half-applied bulk edit leaves somebody to work
    out which half - and the caller chose these types together."""
    a, b = make_type(client, fx), make_type(client, fx)
    r = client.post(
        f"{wbase(fx)}/object-types/bulk-status", headers=hdr(fx.editor_sub),
        json={"object_type_ids": [a["id"], str(uuid.uuid4()), b["id"]],
              "status": "active"},
    )
    assert r.status_code == 404, r.text
    assert read_type(client, fx, a["id"])["status"] == "experimental"
    assert read_type(client, fx, b["id"])["status"] == "experimental"


def test_an_invalid_status_is_refused(client: TestClient, fx: Fixture) -> None:
    a = make_type(client, fx)
    r = bulk_types(client, fx, object_type_ids=[a["id"]], status="retired")
    assert r.status_code == 422, r.text


def test_a_viewer_cannot_bulk_edit(client: TestClient, fx: Fixture) -> None:
    a = make_type(client, fx)
    r = bulk_types(
        client, fx, object_type_ids=[a["id"]], status="active", sub=fx.viewer_sub
    )
    assert r.status_code == 403, r.text


# ---- p.258's opt-in ----------------------------------------------------------
def test_the_option_applies_the_status_to_every_property(
    client: TestClient, fx: Fixture
) -> None:
    """p.258: "there is the option to also apply the `active` status to all
    properties on the object type". §170 made propagation lower-only; this is
    the explicit way past that, and it has to be asked for."""
    a = make_type(client, fx)
    assert bulk_types(
        client, fx, object_type_ids=[a["id"]], status="active",
        apply_to_properties=True,
    ).status_code == 200
    assert statuses_of(read_type(client, fx, a["id"])) == {
        "name": "active", "code": "active",
    }


def test_without_the_option_the_properties_stay_put(
    client: TestClient, fx: Fixture
) -> None:
    """**The half that makes the option an option.** A version that always
    raised would pass the test above and quietly undo §170's asymmetry."""
    a = make_type(client, fx)
    assert bulk_types(
        client, fx, object_type_ids=[a["id"]], status="active"
    ).status_code == 200
    assert statuses_of(read_type(client, fx, a["id"])) == {
        "name": "experimental", "code": "experimental",
    }


# ---- p.258's property bulk edit ---------------------------------------------
def test_properties_change_together(client: TestClient, fx: Fixture) -> None:
    a = make_type(client, fx)
    assert bulk_types(client, fx, object_type_ids=[a["id"]], status="active").status_code == 200

    r = bulk_props(client, fx, a["id"], api_names=["name", "code"], status="deprecated")
    assert r.status_code == 200, r.text
    assert statuses_of(read_type(client, fx, a["id"])) == {
        "name": "deprecated", "code": "deprecated",
    }


def test_only_the_named_properties_move(client: TestClient, fx: Fixture) -> None:
    a = make_type(client, fx)
    assert bulk_props(
        client, fx, a["id"], api_names=["name"], status="deprecated"
    ).status_code == 200
    assert statuses_of(read_type(client, fx, a["id"])) == {
        "name": "deprecated", "code": "experimental",
    }


def test_a_property_cannot_be_raised_above_its_object_type(
    client: TestClient, fx: Fixture
) -> None:
    """**The decision in this unit.** p.256's propagation runs on every save of
    the type, so a property raised above it would be silently demoted by the
    next unrelated edit - a change somebody made, gone later, with nothing to
    say why. Capping refuses to create that state rather than letting it exist
    until something tidies it away.
    """
    a = make_type(client, fx)  # experimental
    r = bulk_props(client, fx, a["id"], api_names=["name"], status="active")
    assert r.status_code == 200, r.text
    assert statuses_of(read_type(client, fx, a["id"]))["name"] == "experimental"


def test_promoted_is_refused_for_properties(client: TestClient, fx: Fixture) -> None:
    """p.255: `promoted` "is not available for properties"."""
    a = make_type(client, fx)
    r = bulk_props(client, fx, a["id"], api_names=["name"], status="promoted")
    assert r.status_code == 422, r.text


def test_an_unknown_property_is_a_404_naming_it(
    client: TestClient, fx: Fixture
) -> None:
    """And nothing moves: the check runs before the first write."""
    a = make_type(client, fx)
    r = bulk_props(
        client, fx, a["id"], api_names=["name", "nonesuch"], status="deprecated"
    )
    assert r.status_code == 404, r.text
    assert "nonesuch" in r.text
    assert statuses_of(read_type(client, fx, a["id"]))["name"] == "experimental"


def test_a_bulk_property_edit_caps_the_link_types(
    client: TestClient, fx: Fixture
) -> None:
    """p.257: "The same requirements are true of foreign keys of a link type."
    A join column moved, so the link is re-capped - the bulk path is not a way
    round §176's fix."""
    a = make_type(client, fx, [{"api_name": "name", "data_type": "string"}])
    b = make_type(client, fx, [{"api_name": "code", "data_type": "string"}])
    link = client.post(
        f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"j_{uuid.uuid4().hex[:6]}", "display_name": "J",
              "from_type_id": a["id"], "to_type_id": b["id"],
              "cardinality": "one_to_many",
              "from_property": "name", "to_property": "code"},
    ).json()
    assert bulk_types(
        client, fx, object_type_ids=[a["id"], b["id"]], status="active",
        apply_to_properties=True,
    ).status_code == 200
    assert client.patch(
        f"{wbase(fx)}/link-types/{link['id']}", headers=hdr(fx.editor_sub),
        json={"from_property": "name", "to_property": "code", "status": "active"},
    ).json()["status"] == "active"

    assert bulk_props(
        client, fx, a["id"], api_names=["name"], status="deprecated"
    ).status_code == 200
    links = client.get(f"{wbase(fx)}/link-types", headers=hdr(fx.viewer_sub)).json()
    assert next(l for l in links if l["id"] == link["id"])["status"] == "deprecated"


def test_a_bulk_edit_is_recorded_as_a_version(
    client: TestClient, fx: Fixture
) -> None:
    """A status change through the editor appends a version (db 0028), so one
    through a checkbox has to as well - otherwise the history says the
    ontology changed by itself."""
    a = make_type(client, fx)
    before = client.get(
        f"{wbase(fx)}/object-types/{a['id']}/versions", headers=hdr(fx.viewer_sub)
    ).json()
    assert bulk_types(client, fx, object_type_ids=[a["id"]], status="active").status_code == 200
    after = client.get(
        f"{wbase(fx)}/object-types/{a['id']}/versions", headers=hdr(fx.viewer_sub)
    ).json()
    assert len(after) == len(before) + 1, (len(before), len(after))
