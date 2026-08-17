"""Actions (write-back) tests: action_type CRUD (workspace-scoped), execute
happy path (instance + mapped dataset both updated, new dataset version
created), and validation failures (unknown/non-editable/unmapped property,
wrong value type). Mirrors test_objects.py's fixture/client shape.
"""
from __future__ import annotations

import io
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

CUSTOMERS = b"customer_id,name,email,region\n1,Ada Lovelace,ada@example.com,north\n2,Grace Hopper,grace@example.com,south\n"


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("actions-storage")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


def dbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets"


def sbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/object-type-sources"


def abase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/actions"


@pytest.fixture(scope="module")
def customers_dataset(client: TestClient, fx: Fixture) -> str:
    r = client.post(
        f"{dbase(fx)}/upload",
        headers=hdr(fx.editor_sub),
        data={"name": f"ActionCustomers {fx.tag}"},
        files={"file": ("customers.csv", io.BytesIO(CUSTOMERS), "text/csv")},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture(scope="module")
def customer_type_id(client: TestClient, fx: Fixture) -> str:
    r = client.post(
        f"{wbase(fx)}/object-types",
        headers=hdr(fx.editor_sub),
        json={
            "api_name": f"ActionCustomer{fx.tag}",
            "display_name": f"ActionCustomer {fx.tag}",
            "properties": [
                {"api_name": "name", "data_type": "string"},
                {"api_name": "email", "data_type": "string"},
                # deliberately never mapped by the source below, so we can
                # exercise the "no dataset column mapped" rejection.
                {"api_name": "vip_note", "data_type": "string"},
            ],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture(scope="module")
def source_id(
    client: TestClient, fx: Fixture, customer_type_id: str, customers_dataset: str
) -> str:
    r = client.post(
        sbase(fx),
        headers=hdr(fx.editor_sub),
        json={
            "object_type_id": customer_type_id,
            "dataset_id": customers_dataset,
            "primary_key_column": "customer_id",
            "column_mappings": {"name": "name", "email": "email"},
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture(scope="module")
def instance_id(client: TestClient, fx: Fixture, source_id: str, customer_type_id: str) -> str:
    r = client.post(f"{sbase(fx)}/{source_id}/sync", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    r = client.get(f"{wbase(fx)}/object-types/{customer_type_id}/instances", headers=hdr(fx.viewer_sub))
    ada = next(i for i in r.json()["items"] if i["properties"]["name"] == "Ada Lovelace")
    return ada["id"]


def test_viewer_cannot_create_action_type(client: TestClient, fx: Fixture, customer_type_id: str) -> None:
    r = client.post(
        f"{wbase(fx)}/action-types",
        headers=hdr(fx.viewer_sub),
        json={
            "object_type_id": customer_type_id, "api_name": "nope",
            "display_name": "Nope", "editable_properties": ["name"],
        },
    )
    assert r.status_code == 403


def test_create_action_type_rejects_unknown_property(
    client: TestClient, fx: Fixture, customer_type_id: str
) -> None:
    r = client.post(
        f"{wbase(fx)}/action-types",
        headers=hdr(fx.editor_sub),
        json={
            "object_type_id": customer_type_id, "api_name": "bad_props",
            "display_name": "Bad", "editable_properties": ["not_a_real_property"],
        },
    )
    assert r.status_code == 422


@pytest.fixture(scope="module")
def action_type_id(client: TestClient, fx: Fixture, customer_type_id: str) -> str:
    r = client.post(
        f"{wbase(fx)}/action-types",
        headers=hdr(fx.editor_sub),
        json={
            "object_type_id": customer_type_id,
            "api_name": "update_contact",
            "display_name": "Update contact",
            "description": "Correct a customer's name or email",
            "editable_properties": ["name", "email", "vip_note"],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["object_type_name"] == f"ActionCustomer {fx.tag}"
    assert set(body["editable_properties"]) == {"name", "email", "vip_note"}
    return body["id"]


def test_duplicate_action_type_conflicts(
    client: TestClient, fx: Fixture, customer_type_id: str, action_type_id: str
) -> None:
    r = client.post(
        f"{wbase(fx)}/action-types",
        headers=hdr(fx.editor_sub),
        json={
            "object_type_id": customer_type_id, "api_name": "update_contact",
            "display_name": "Dup", "editable_properties": ["name"],
        },
    )
    assert r.status_code == 409


def test_get_and_list_action_types(
    client: TestClient, fx: Fixture, action_type_id: str, customer_type_id: str
) -> None:
    r = client.get(f"{wbase(fx)}/action-types/{action_type_id}", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200
    r = client.get(
        f"{wbase(fx)}/action-types?object_type_id={customer_type_id}", headers=hdr(fx.viewer_sub)
    )
    assert any(a["id"] == action_type_id for a in r.json())


# ---- execute ------------------------------------------------------------------
def test_viewer_cannot_execute(
    client: TestClient, fx: Fixture, action_type_id: str, instance_id: str
) -> None:
    r = client.post(
        f"{abase(fx)}/{action_type_id}/execute",
        headers=hdr(fx.viewer_sub),
        json={"instance_id": instance_id, "values": {"name": "Nope"}},
    )
    assert r.status_code == 403


def test_execute_rejects_non_editable_property(
    client: TestClient, fx: Fixture, action_type_id: str, instance_id: str
) -> None:
    r = client.post(
        f"{abase(fx)}/{action_type_id}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id, "values": {"customer_id": "9"}},
    )
    assert r.status_code == 422


def test_execute_rejects_unmapped_property(
    client: TestClient, fx: Fixture, action_type_id: str, instance_id: str
) -> None:
    # vip_note is editable on the action but never mapped to a dataset
    # column by the source - there's no write-back target for it.
    r = client.post(
        f"{abase(fx)}/{action_type_id}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id, "values": {"vip_note": "loyal"}},
    )
    assert r.status_code == 422


def test_execute_rejects_wrong_type(
    client: TestClient, fx: Fixture, action_type_id: str, instance_id: str
) -> None:
    # 'name' is a string property; a bool value is rejected before anything
    # is written.
    r = client.post(
        f"{abase(fx)}/{action_type_id}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id, "values": {"name": True}},
    )
    assert r.status_code == 422


def test_execute_writes_back_instance_and_dataset(
    client: TestClient, fx: Fixture, action_type_id: str, instance_id: str,
    customer_type_id: str, customers_dataset: str,
) -> None:
    r = client.get(f"{dbase(fx)}/{customers_dataset}", headers=hdr(fx.viewer_sub))
    version_before = r.json()["current_version"]

    r = client.post(
        f"{abase(fx)}/{action_type_id}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id, "values": {"email": "ada.new@example.com"}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["instance"]["properties"]["email"] == "ada.new@example.com"
    assert body["instance"]["properties"]["name"] == "Ada Lovelace"  # untouched
    assert body["dataset_version"] == version_before + 1

    # The instance browser reflects it too.
    r = client.get(f"{wbase(fx)}/object-types/{customer_type_id}/instances/{instance_id}", headers=hdr(fx.viewer_sub))
    assert r.json()["properties"]["email"] == "ada.new@example.com"

    # The dataset itself was versioned, and the new version has the edit -
    # while the other row is untouched.
    r = client.get(f"{dbase(fx)}/{customers_dataset}", headers=hdr(fx.viewer_sub))
    assert r.json()["current_version"] == version_before + 1
    r = client.post(
        f"{dbase(fx)}/{customers_dataset}/query", headers=hdr(fx.viewer_sub),
        json={"sql": "SELECT customer_id, email FROM dataset ORDER BY customer_id"},
    )
    rows = {row[0]: row[1] for row in r.json()["rows"]}
    assert rows[1] == "ada.new@example.com"
    assert rows[2] == "grace@example.com"


def test_delete_action_type(client: TestClient, fx: Fixture, customer_type_id: str) -> None:
    r = client.post(
        f"{wbase(fx)}/action-types",
        headers=hdr(fx.editor_sub),
        json={
            "object_type_id": customer_type_id, "api_name": "temp_action",
            "display_name": "Temp", "editable_properties": ["name"],
        },
    )
    temp_id = r.json()["id"]
    assert client.delete(f"{wbase(fx)}/action-types/{temp_id}", headers=hdr(fx.editor_sub)).status_code == 204
    assert client.get(f"{wbase(fx)}/action-types/{temp_id}", headers=hdr(fx.viewer_sub)).status_code == 404


def test_actions_audited(client: TestClient, fx: Fixture) -> None:
    r = client.get("/api/org/audit?limit=200", headers=hdr(fx.admin_sub))
    actions = {e["action"] for e in r.json()}
    assert {"action_type.create", "action_type.delete", "action.execute"} <= actions


# ---- edit-only properties (ontology.md §1.2; object-link-types p.113-115) ----
# `vip_note` above is the *other* case and is why the flag has to be stored:
# it is unmapped because nobody mapped it, and an action writing it is still
# refused. These cover the property that is unmapped **on purpose**.
@pytest.fixture(scope="module")
def edit_only_setup(client: TestClient, fx: Fixture, customers_dataset: str) -> dict:
    """An object type whose `triage_note` has no column, its source, and an
    action that writes it."""
    tid = client.post(
        f"{wbase(fx)}/object-types",
        headers=hdr(fx.editor_sub),
        json={
            "api_name": f"EditOnly{fx.tag}", "display_name": f"EditOnly {fx.tag}",
            "properties": [
                {"api_name": "name", "data_type": "string"},
                {"api_name": "triage_note", "data_type": "string", "edit_only": True},
            ],
        },
    )
    assert tid.status_code == 201, tid.text
    type_id = tid.json()["id"]

    src = client.post(
        sbase(fx), headers=hdr(fx.editor_sub),
        json={
            "object_type_id": type_id, "dataset_id": customers_dataset,
            "primary_key_column": "customer_id",
            "column_mappings": {"name": "name"},
        },
    )
    assert src.status_code == 201, src.text
    source_id = src.json()["id"]

    action = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={
            "object_type_id": type_id,
            "api_name": "triage", "display_name": "Triage",
            "editable_properties": ["triage_note"],
        },
    )
    assert action.status_code == 201, action.text
    return {"type_id": type_id, "source_id": source_id,
            "action_id": action.json()["id"]}


def _sync(client: TestClient, fx: Fixture, setup: dict) -> None:
    r = client.post(f"{sbase(fx)}/{setup['source_id']}/sync", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text


def _ada(client: TestClient, fx: Fixture, setup: dict) -> dict:
    r = client.get(
        f"{wbase(fx)}/object-types/{setup['type_id']}/instances", headers=hdr(fx.viewer_sub)
    )
    return next(i for i in r.json()["items"] if i["properties"]["name"] == "Ada Lovelace")


def test_mapping_an_edit_only_property_is_refused(
    client: TestClient, fx: Fixture, edit_only_setup: dict, customers_dataset: str
) -> None:
    """p.113-114. Accepting the mapping would make the flag a lie the sync then
    acts on: the upsert preserves edit-only keys, so a mapped one would have
    its dataset value ignored on every sync with nothing saying why."""
    r = client.post(
        sbase(fx), headers=hdr(fx.editor_sub),
        json={
            "object_type_id": edit_only_setup["type_id"],
            "dataset_id": customers_dataset,
            "primary_key_column": "customer_id",
            "column_mappings": {"name": "name", "email": "triage_note"},
        },
    )
    assert r.status_code == 422, r.text
    assert "edit-only" in r.json()["detail"]


def test_an_action_writes_an_edit_only_property_and_a_resync_keeps_it(
    client: TestClient, fx: Fixture, edit_only_setup: dict
) -> None:
    """**The claim the whole feature rests on** (p.113). The value has no column
    to come back from, so if the sync did not preserve it there would be nowhere
    left for it to exist - and until this unit the Postgres upsert wrote
    `properties = EXCLUDED.properties` and deleted it every time."""
    _sync(client, fx, edit_only_setup)
    ada = _ada(client, fx, edit_only_setup)
    assert "triage_note" not in ada["properties"], (
        "the dataset has no such column, so a sync must not invent one"
    )

    run = client.post(
        f"{abase(fx)}/{edit_only_setup['action_id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": ada["id"], "values": {"triage_note": "call the owner"}},
    )
    assert run.status_code == 200, run.text
    assert run.json()["ok"] is True, run.json()
    assert _ada(client, fx, edit_only_setup)["properties"]["triage_note"] == "call the owner"

    # The sync is authoritative over what it owns, and over nothing else.
    _sync(client, fx, edit_only_setup)
    after = _ada(client, fx, edit_only_setup)
    assert after["properties"]["triage_note"] == "call the owner"
    assert after["properties"]["name"] == "Ada Lovelace"


def test_an_action_still_refuses_a_property_that_is_merely_unmapped(
    client: TestClient, fx: Fixture, customer_type_id: str, instance_id: str
) -> None:
    """The distinction the stored flag exists to keep. `vip_note` is unmapped
    and *not* edit-only - a column somebody has not mapped yet - and writing it
    would produce a value that survives until the next sync and then vanishes.
    Still refused, so the exception is exactly as narrow as it claims."""
    action = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={
            "object_type_id": customer_type_id,
            "api_name": "vip_only", "display_name": "VIP",
            "editable_properties": ["vip_note"],
        },
    )
    assert action.status_code == 201, action.text
    run = client.post(
        f"{abase(fx)}/{action.json()['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id, "values": {"vip_note": "x"}},
    )
    assert run.status_code == 422, run.text
    assert "no dataset column mapped" in run.json()["detail"]
