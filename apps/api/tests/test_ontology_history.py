"""Ontology change history and impact analysis (ROADMAP Objects item 5).

Before this, an object type could not be *changed* at all — create and delete
were the whole surface, and delete cascades a type's properties, mappings,
links, actions and instances away. So these tests cover two things at once:
that an edit exists and is recorded, and that it refuses to quietly break
what is already built on the definition it is changing.

The refusal is the part worth testing hardest, because every consumer of a
removed property degrades *silently* rather than raising: a dataset mapping
keeps writing a property nothing renders, an action's type check falls back
to "string", and a link traversal returns nothing forever. There is no
exception anywhere to catch, so the only protection is refusing the edit.
"""
from __future__ import annotations

import io
import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

PEOPLE = b"employee_id,full_name,department\n1,Ada,ENG\n2,Grace,RES\n"


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("ontology-history")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


def pbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


def _props(*specs: tuple[str, str]) -> list[dict]:
    return [{"api_name": n, "data_type": t} for n, t in specs]


@pytest.fixture()
def person(client: TestClient, fx: Fixture) -> dict:
    """A three-property type with nothing consuming it yet."""
    tag = uuid.uuid4().hex[:6]
    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"person_{tag}", "display_name": f"Person {tag}",
              "properties": _props(("full_name", "string"), ("department", "string"),
                                   ("grade", "integer")),
              "title_property": "full_name"},
    )
    assert r.status_code == 201, r.text
    return {"tag": tag, "id": r.json()["id"], "api_name": f"person_{tag}"}


def _patch(client: TestClient, fx: Fixture, type_id: str, props: list[dict], **extra):
    body = {"display_name": "Edited", "properties": props, **extra}
    return client.patch(f"{wbase(fx)}/object-types/{type_id}",
                        headers=hdr(fx.editor_sub), json=body)


def _versions(client: TestClient, fx: Fixture, type_id: str) -> list[dict]:
    r = client.get(f"{wbase(fx)}/object-types/{type_id}/versions", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return r.json()


def _map_dataset(client: TestClient, fx: Fixture, type_id: str, mappings: dict[str, str]) -> str:
    tag = uuid.uuid4().hex[:6]
    r = client.post(
        f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"People {tag}"},
        files={"file": ("people.csv", io.BytesIO(PEOPLE), "text/csv")},
    )
    assert r.status_code == 201, r.text
    r = client.post(
        f"{pbase(fx)}/object-type-sources", headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "dataset_id": r.json()["id"],
              "primary_key_column": "employee_id", "column_mappings": mappings},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---- the edit itself ---------------------------------------------------------
def test_creating_a_type_records_version_one(
    client: TestClient, fx: Fixture, person: dict
) -> None:
    versions = _versions(client, fx, person["id"])
    assert [v["version_number"] for v in versions] == [1]
    v1 = versions[0]
    assert [p["api_name"] for p in v1["properties"]] == ["full_name", "department", "grade"]
    # The snapshot names the title property, it does not point at its row -
    # property ids do not survive an edit.
    assert v1["title_property"] == "full_name"
    assert v1["restored_from"] is None
    assert v1["created_by_email"].startswith("editor-")


def test_editing_appends_a_version_and_leaves_api_name_alone(
    client: TestClient, fx: Fixture, person: dict
) -> None:
    r = _patch(
        client, fx, person["id"],
        _props(("full_name", "string"), ("department", "string"), ("grade", "integer"),
               ("start_date", "date")),
        title_property="full_name", description="now with a start date",
        api_name="renamed_by_a_hopeful_client",
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["api_name"] == person["api_name"], "api_name is immutable"
    assert body["display_name"] == "Edited"
    assert [p["api_name"] for p in body["properties"]] == [
        "full_name", "department", "grade", "start_date"
    ]
    # Property order follows the order sent, not insertion history.
    assert [p["sort_order"] for p in body["properties"]] == [0, 1, 2, 3]

    versions = _versions(client, fx, person["id"])
    assert [v["version_number"] for v in versions] == [2, 1]
    assert len(versions[0]["properties"]) == 4
    assert len(versions[1]["properties"]) == 3, "v1 is untouched by the edit"


def test_adding_a_property_breaks_nothing(
    client: TestClient, fx: Fixture, person: dict
) -> None:
    _map_dataset(client, fx, person["id"], {"full_name": "full_name"})
    r = client.post(
        f"{wbase(fx)}/object-types/{person['id']}/impact", headers=hdr(fx.viewer_sub),
        json={"display_name": "Edited",
              "properties": _props(("full_name", "string"), ("department", "string"),
                                   ("grade", "integer"), ("nickname", "string"))},
    )
    assert r.status_code == 200, r.text
    assert r.json() == [], "an addition disturbs nothing"


def test_an_edit_needs_at_least_one_property(
    client: TestClient, fx: Fixture, person: dict
) -> None:
    r = _patch(client, fx, person["id"], [])
    assert r.status_code == 422, r.text


# ---- impact analysis --------------------------------------------------------
def test_removing_a_mapped_property_is_refused_and_names_the_mapping(
    client: TestClient, fx: Fixture, person: dict
) -> None:
    _map_dataset(client, fx, person["id"],
                 {"full_name": "full_name", "department": "department"})
    dropped = _props(("full_name", "string"), ("grade", "integer"))

    r = _patch(client, fx, person["id"], dropped, title_property="full_name")
    assert r.status_code == 409, r.text
    body = r.json()
    assert "breaks existing consumers" in body["detail"]
    assert len(body["impacts"]) == 1
    impact = body["impacts"][0]
    assert impact["property"] == "department"
    assert impact["change"] == "removed"
    assert impact["consumer_kind"] == "dataset_mapping"
    assert impact["consumer_name"].startswith("People ")
    assert "'department' is mapped to it" in impact["detail"]
    assert impact["blocking"] is True

    # Refused means refused: nothing changed and no version was written.
    assert [v["version_number"] for v in _versions(client, fx, person["id"])] == [1]
    detail = client.get(f"{wbase(fx)}/object-types/{person['id']}",
                        headers=hdr(fx.viewer_sub)).json()
    assert len(detail["properties"]) == 3


def test_the_impact_endpoint_previews_the_refusal_without_changing_anything(
    client: TestClient, fx: Fixture, person: dict
) -> None:
    _map_dataset(client, fx, person["id"], {"department": "department"})
    r = client.post(
        f"{wbase(fx)}/object-types/{person['id']}/impact", headers=hdr(fx.viewer_sub),
        json={"display_name": "Edited",
              "properties": _props(("full_name", "string"), ("grade", "integer"))},
    )
    assert r.status_code == 200, r.text
    assert [i["property"] for i in r.json()] == ["department"]
    assert [v["version_number"] for v in _versions(client, fx, person["id"])] == [1]


def test_acknowledging_pushes_the_change_through(
    client: TestClient, fx: Fixture, person: dict
) -> None:
    _map_dataset(client, fx, person["id"], {"department": "department"})
    props = _props(("full_name", "string"), ("grade", "integer"))
    assert _patch(client, fx, person["id"], props,
                  title_property="full_name").status_code == 409

    r = _patch(client, fx, person["id"], props, title_property="full_name",
               acknowledge_breaking=True)
    assert r.status_code == 200, r.text
    assert [p["api_name"] for p in r.json()["properties"]] == ["full_name", "grade"]
    assert [v["version_number"] for v in _versions(client, fx, person["id"])] == [2, 1]

    import psycopg
    from test_api import ADMIN_DSN

    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        row = conn.execute(
            "SELECT metadata FROM audit_log WHERE resource_id = %s "
            "AND action = 'object_type.update' ORDER BY created_at DESC LIMIT 1",
            (person["id"],),
        ).fetchone()
    assert row is not None and row[0]["acknowledged_breaking"] is True, \
        "the audit trail records that somebody accepted the breakage"


def test_actions_and_link_joins_are_named_too(
    client: TestClient, fx: Fixture, person: dict
) -> None:
    _map_dataset(client, fx, person["id"], {"department": "department"})
    r = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": person["id"], "api_name": f"set_dept_{person['tag']}",
              "display_name": "Set department", "editable_properties": ["department"]},
    )
    assert r.status_code == 201, r.text

    dept = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"dept_{person['tag']}", "display_name": f"Dept {person['tag']}",
              "properties": _props(("label", "string"))},
    )
    assert dept.status_code == 201, dept.text
    link = client.post(
        f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"works_in_{person['tag']}", "display_name": "Works in",
              "from_type_id": person["id"], "to_type_id": dept.json()["id"],
              "cardinality": "one_to_many",
              "from_property": "department", "to_property": "$primary_key"},
    )
    assert link.status_code == 201, link.text

    r = _patch(client, fx, person["id"],
               _props(("full_name", "string"), ("grade", "integer")),
               title_property="full_name")
    assert r.status_code == 409, r.text
    kinds = {i["consumer_kind"] for i in r.json()["impacts"]}
    assert kinds == {"dataset_mapping", "action", "link"}
    action_impact = next(i for i in r.json()["impacts"] if i["consumer_kind"] == "action")
    assert action_impact["consumer_name"] == "Set department"
    link_impact = next(i for i in r.json()["impacts"] if i["consumer_kind"] == "link")
    assert "from end" in link_impact["detail"]


def test_retyping_a_link_join_is_reported_but_not_blocking(
    client: TestClient, fx: Fixture, person: dict
) -> None:
    """The join compares the *text* form of both values (join_key), so an
    integer that becomes a string still matches what it matched before. A
    removal is a different matter and stays blocking."""
    dept = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"dept_{person['tag']}", "display_name": f"Dept {person['tag']}",
              "properties": _props(("label", "string"))},
    ).json()
    r = client.post(
        f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"grade_of_{person['tag']}", "display_name": "Graded",
              "from_type_id": person["id"], "to_type_id": dept["id"],
              "cardinality": "one_to_many",
              "from_property": "grade", "to_property": "$primary_key"},
    )
    assert r.status_code == 201, r.text

    retyped = _props(("full_name", "string"), ("department", "string"), ("grade", "string"))
    impacts = client.post(
        f"{wbase(fx)}/object-types/{person['id']}/impact", headers=hdr(fx.viewer_sub),
        json={"display_name": "Edited", "properties": retyped},
    ).json()
    assert len(impacts) == 1
    assert impacts[0] == {**impacts[0], "change": "retyped", "blocking": False}

    # Reported, and allowed without acknowledgement.
    r = _patch(client, fx, person["id"], retyped, title_property="full_name")
    assert r.status_code == 200, r.text


def test_a_rename_is_a_removal_plus_an_addition(
    client: TestClient, fx: Fixture, person: dict
) -> None:
    """Nothing in the schema distinguishes a rename from a delete-and-add, and
    every consumer naming the old api_name breaks either way — so it is
    reported as the removal it is rather than waved through."""
    _map_dataset(client, fx, person["id"], {"department": "department"})
    r = client.post(
        f"{wbase(fx)}/object-types/{person['id']}/impact", headers=hdr(fx.viewer_sub),
        json={"display_name": "Edited",
              "properties": _props(("full_name", "string"), ("team", "string"),
                                   ("grade", "integer"))},
    )
    assert [(i["property"], i["change"]) for i in r.json()] == [("department", "removed")]


# ---- restore ----------------------------------------------------------------
def test_restore_appends_a_version_and_records_the_revert(
    client: TestClient, fx: Fixture, person: dict
) -> None:
    assert _patch(
        client, fx, person["id"],
        _props(("full_name", "string"), ("department", "string"), ("grade", "integer"),
               ("nickname", "string")),
        title_property="full_name",
    ).status_code == 200

    r = client.post(
        f"{wbase(fx)}/object-types/{person['id']}/versions/1/restore",
        headers=hdr(fx.editor_sub), json={},
    )
    assert r.status_code == 200, r.text
    assert [p["api_name"] for p in r.json()["properties"]] == [
        "full_name", "department", "grade"
    ]
    assert r.json()["display_name"].startswith("Person "), "v1's display name came back"

    versions = _versions(client, fx, person["id"])
    assert [v["version_number"] for v in versions] == [3, 2, 1]
    assert versions[0]["restored_from"] == 1, "history says it was a revert"
    assert versions[1]["restored_from"] is None


def test_restoring_is_still_a_change_and_can_break_things(
    client: TestClient, fx: Fixture, person: dict
) -> None:
    """"It used to be like this" is not evidence that going back is safe: the
    consumers built since are the ones that break."""
    assert _patch(
        client, fx, person["id"],
        _props(("full_name", "string"), ("department", "string"), ("grade", "integer"),
               ("nickname", "string")),
        title_property="full_name",
    ).status_code == 200
    _map_dataset(client, fx, person["id"], {"full_name": "nickname"})

    restore = f"{wbase(fx)}/object-types/{person['id']}/versions/1/restore"
    r = client.post(restore, headers=hdr(fx.editor_sub), json={})
    assert r.status_code == 409, r.text
    assert [i["property"] for i in r.json()["impacts"]] == ["nickname"]

    r = client.post(restore, headers=hdr(fx.editor_sub),
                    json={"acknowledge_breaking": True})
    assert r.status_code == 200, r.text
    assert len(r.json()["properties"]) == 3


def test_an_unknown_version_is_a_404(client: TestClient, fx: Fixture, person: dict) -> None:
    r = client.post(f"{wbase(fx)}/object-types/{person['id']}/versions/99/restore",
                    headers=hdr(fx.editor_sub), json={})
    assert r.status_code == 404


# ---- roles and visibility ---------------------------------------------------
def test_roles_and_cross_tenant_visibility(
    client: TestClient, fx: Fixture, person: dict
) -> None:
    props = _props(("full_name", "string"))
    body = {"display_name": "Nope", "properties": props}
    url = f"{wbase(fx)}/object-types/{person['id']}"

    assert client.patch(url, headers=hdr(fx.viewer_sub), json=body).status_code == 403
    assert client.patch(url, headers=hdr(fx.outsider_sub), json=body).status_code == 404
    assert client.get(f"{url}/versions", headers=hdr(fx.outsider_sub)).status_code == 404
    assert client.post(f"{url}/impact", headers=hdr(fx.outsider_sub),
                       json=body).status_code == 404
    # Reading history is a viewer-level read, like every other ontology read.
    assert client.get(f"{url}/versions", headers=hdr(fx.viewer_sub)).status_code == 200
