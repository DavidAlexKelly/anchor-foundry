"""Ontology layer tests: object types + properties (workspace-scoped), link
types (workspace-scoped), object type sources (project-scoped dataset →
object mapping), and the auto-suggestion endpoint. Mirrors test_models.py's
fixture/client shape.
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
        LocalStorageGateway(str(tmp_path_factory.mktemp("objects-storage")))
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


@pytest.fixture(scope="module")
def customers_dataset(client: TestClient, fx: Fixture) -> str:
    r = client.post(
        f"{dbase(fx)}/upload",
        headers=hdr(fx.editor_sub),
        data={"name": f"Customers {fx.tag}"},
        files={"file": ("customers.csv", io.BytesIO(CUSTOMERS), "text/csv")},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---- object types -------------------------------------------------------
def test_viewer_cannot_create_type(client: TestClient, fx: Fixture) -> None:
    r = client.post(
        f"{wbase(fx)}/object-types",
        headers=hdr(fx.viewer_sub),
        json={"api_name": "Nope", "display_name": "Nope"},
    )
    assert r.status_code == 403


def test_outsider_gets_404_not_403(client: TestClient, fx: Fixture) -> None:
    r = client.get(f"{wbase(fx)}/object-types", headers=hdr(fx.outsider_sub))
    assert r.status_code == 404


def _create_customer_type(client: TestClient, fx: Fixture) -> dict:
    r = client.post(
        f"{wbase(fx)}/object-types",
        headers=hdr(fx.editor_sub),
        json={
            "api_name": f"Customer{fx.tag}",
            "display_name": f"Customer {fx.tag}",
            "description": "A paying customer",
            "properties": [
                {"api_name": "customer_id", "data_type": "integer", "required": True},
                {"api_name": "name", "data_type": "string"},
                {"api_name": "email", "data_type": "string"},
            ],
            "title_property": "name",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture(scope="module")
def customer_type(client: TestClient, fx: Fixture) -> dict:
    return _create_customer_type(client, fx)


@pytest.fixture(scope="module")
def customer_type_id(customer_type: dict) -> str:
    return customer_type["id"]


def test_create_type_with_properties(customer_type: dict) -> None:
    assert len(customer_type["properties"]) == 3
    assert customer_type["title_property_id"] is not None
    assert customer_type["title_property_id"] == next(
        p["id"] for p in customer_type["properties"] if p["api_name"] == "name"
    )


def test_duplicate_type_name_conflicts(
    client: TestClient, fx: Fixture, customer_type_id: str
) -> None:
    r = client.post(
        f"{wbase(fx)}/object-types",
        headers=hdr(fx.editor_sub),
        json={"api_name": f"Customer{fx.tag}", "display_name": "Dup"},
    )
    assert r.status_code == 409


def test_invalid_property_type_rejected(client: TestClient, fx: Fixture) -> None:
    r = client.post(
        f"{wbase(fx)}/object-types",
        headers=hdr(fx.editor_sub),
        json={
            "api_name": f"Bad{fx.tag}",
            "display_name": "Bad",
            "properties": [{"api_name": "x", "data_type": "not_a_type"}],
        },
    )
    assert r.status_code == 422


def test_duplicate_property_name_rejected(client: TestClient, fx: Fixture) -> None:
    r = client.post(
        f"{wbase(fx)}/object-types",
        headers=hdr(fx.editor_sub),
        json={
            "api_name": f"Dupe{fx.tag}",
            "display_name": "Dupe",
            "properties": [
                {"api_name": "x", "data_type": "string"},
                {"api_name": "x", "data_type": "integer"},
            ],
        },
    )
    assert r.status_code == 422


def test_get_type_visible_to_viewer(
    client: TestClient, fx: Fixture, customer_type_id: str
) -> None:
    r = client.get(f"{wbase(fx)}/object-types/{customer_type_id}", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200
    assert r.json()["api_name"] == f"Customer{fx.tag}"


def test_type_list_shows_source_count(
    client: TestClient, fx: Fixture, customer_type_id: str
) -> None:
    r = client.get(f"{wbase(fx)}/object-types", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200
    row = next(t for t in r.json() if t["id"] == customer_type_id)
    assert row["source_count"] == 0


# ---- link types -----------------------------------------------------------
def test_create_second_type_and_link(client: TestClient, fx: Fixture, customer_type_id: str) -> None:
    r = client.post(
        f"{wbase(fx)}/object-types",
        headers=hdr(fx.editor_sub),
        json={
            "api_name": f"Order{fx.tag}",
            "display_name": f"Order {fx.tag}",
            "properties": [{"api_name": "order_id", "data_type": "integer"}],
        },
    )
    assert r.status_code == 201, r.text
    order_type_id = r.json()["id"]

    r = client.post(
        f"{wbase(fx)}/link-types",
        headers=hdr(fx.viewer_sub),
        json={
            "api_name": f"placed{fx.tag}",
            "display_name": "Placed",
            "from_type_id": customer_type_id,
            "to_type_id": order_type_id,
            "cardinality": "one_to_many",
        },
    )
    assert r.status_code == 403

    r = client.post(
        f"{wbase(fx)}/link-types",
        headers=hdr(fx.editor_sub),
        json={
            "api_name": f"placed{fx.tag}",
            "display_name": "Placed",
            "from_type_id": customer_type_id,
            "to_type_id": order_type_id,
            "cardinality": "one_to_many",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["from_display_name"] == f"Customer {fx.tag}"
    assert body["to_display_name"] == f"Order {fx.tag}"

    r = client.get(f"{wbase(fx)}/link-types", headers=hdr(fx.viewer_sub))
    assert any(lt["id"] == body["id"] for lt in r.json())

    assert client.delete(
        f"{wbase(fx)}/link-types/{body['id']}", headers=hdr(fx.editor_sub)
    ).status_code == 204
    assert client.delete(
        f"{wbase(fx)}/link-types/{body['id']}", headers=hdr(fx.editor_sub)
    ).status_code == 404

    # cleanup the order type so it doesn't leak into other assertions
    client.delete(f"{wbase(fx)}/object-types/{order_type_id}", headers=hdr(fx.editor_sub))


def test_link_type_rejects_foreign_endpoint(client: TestClient, fx: Fixture, customer_type_id: str) -> None:
    import uuid

    r = client.post(
        f"{wbase(fx)}/link-types",
        headers=hdr(fx.editor_sub),
        json={
            "api_name": f"bogus{fx.tag}",
            "display_name": "Bogus",
            "from_type_id": customer_type_id,
            "to_type_id": str(uuid.uuid4()),
            "cardinality": "one_to_one",
        },
    )
    assert r.status_code == 404


# ---- suggestion -------------------------------------------------------------
def test_suggest_from_dataset(client: TestClient, fx: Fixture, customers_dataset: str) -> None:
    r = client.post(
        f"{sbase(fx)}/suggest", headers=hdr(fx.viewer_sub), json={"dataset_id": customers_dataset}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["suggested_primary_key"] == "customer_id"
    assert body["suggested_title_property"] == "name"
    assert {p["api_name"] for p in body["properties"]} == {"customer_id", "name", "email", "region"}


def test_suggest_unknown_dataset_is_404(client: TestClient, fx: Fixture) -> None:
    import uuid

    r = client.post(
        f"{sbase(fx)}/suggest", headers=hdr(fx.viewer_sub), json={"dataset_id": str(uuid.uuid4())}
    )
    assert r.status_code == 404


# ---- object type sources ----------------------------------------------------
def test_viewer_cannot_create_source(
    client: TestClient, fx: Fixture, customer_type_id: str, customers_dataset: str
) -> None:
    r = client.post(
        sbase(fx),
        headers=hdr(fx.viewer_sub),
        json={
            "object_type_id": customer_type_id,
            "dataset_id": customers_dataset,
            "primary_key_column": "customer_id",
            "column_mappings": {"name": "name"},
        },
    )
    assert r.status_code == 403


def test_source_rejects_unknown_column(
    client: TestClient, fx: Fixture, customer_type_id: str, customers_dataset: str
) -> None:
    r = client.post(
        sbase(fx),
        headers=hdr(fx.editor_sub),
        json={
            "object_type_id": customer_type_id,
            "dataset_id": customers_dataset,
            "primary_key_column": "customer_id",
            "column_mappings": {"nonexistent_column": "name"},
        },
    )
    assert r.status_code == 422


def test_source_rejects_unknown_property(
    client: TestClient, fx: Fixture, customer_type_id: str, customers_dataset: str
) -> None:
    r = client.post(
        sbase(fx),
        headers=hdr(fx.editor_sub),
        json={
            "object_type_id": customer_type_id,
            "dataset_id": customers_dataset,
            "primary_key_column": "customer_id",
            "column_mappings": {"name": "not_a_real_property"},
        },
    )
    assert r.status_code == 422


def test_create_source_and_list(
    client: TestClient, fx: Fixture, customer_type_id: str, customers_dataset: str
) -> None:
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
    body = r.json()
    assert body["sync_status"] == "never_synced"
    assert body["object_type_name"] == f"Customer {fx.tag}"
    assert body["dataset_name"] == f"Customers {fx.tag}"
    assert body["column_mappings"] == {"name": "name", "email": "email"}

    # source_count on the type now reflects this mapping
    r = client.get(f"{wbase(fx)}/object-types", headers=hdr(fx.viewer_sub))
    row = next(t for t in r.json() if t["id"] == customer_type_id)
    assert row["source_count"] == 1

    r = client.get(sbase(fx), headers=hdr(fx.viewer_sub))
    assert any(s["id"] == body["id"] for s in r.json())


def test_duplicate_source_conflicts(
    client: TestClient, fx: Fixture, customer_type_id: str, customers_dataset: str
) -> None:
    r = client.post(
        sbase(fx),
        headers=hdr(fx.editor_sub),
        json={
            "object_type_id": customer_type_id,
            "dataset_id": customers_dataset,
            "primary_key_column": "customer_id",
            "column_mappings": {"name": "name"},
        },
    )
    assert r.status_code == 409


def test_delete_source(client: TestClient, fx: Fixture) -> None:
    r = client.get(sbase(fx), headers=hdr(fx.viewer_sub))
    source_id = r.json()[0]["id"]
    assert client.delete(
        f"{sbase(fx)}/{source_id}", headers=hdr(fx.editor_sub)
    ).status_code == 204
    assert client.delete(
        f"{sbase(fx)}/{source_id}", headers=hdr(fx.editor_sub)
    ).status_code == 404


# ---- delete cascades & audit -------------------------------------------------
def test_delete_type_cascades_and_is_audited(client: TestClient, fx: Fixture) -> None:
    r = client.post(
        f"{wbase(fx)}/object-types",
        headers=hdr(fx.editor_sub),
        json={
            "api_name": f"Ephemeral{fx.tag}",
            "display_name": "Ephemeral",
            "properties": [{"api_name": "id", "data_type": "integer"}],
        },
    )
    type_id = r.json()["id"]
    assert client.delete(
        f"{wbase(fx)}/object-types/{type_id}", headers=hdr(fx.editor_sub)
    ).status_code == 204
    assert client.get(
        f"{wbase(fx)}/object-types/{type_id}", headers=hdr(fx.viewer_sub)
    ).status_code == 404

    r = client.get("/api/org/audit?limit=200", headers=hdr(fx.admin_sub))
    actions = {e["action"] for e in r.json()}
    assert {
        "object_type.create", "object_type.delete", "link_type.create",
        "link_type.delete", "object_type_source.create", "object_type_source.delete",
    } <= actions


# ---- instance materialisation + sync -----------------------------------------
def ibase(fx: Fixture, type_id: str) -> str:
    return f"{wbase(fx)}/object-types/{type_id}/instances"


@pytest.fixture(scope="module")
def sync_type_id(client: TestClient, fx: Fixture) -> str:
    r = client.post(
        f"{wbase(fx)}/object-types",
        headers=hdr(fx.editor_sub),
        json={
            "api_name": f"SyncTarget{fx.tag}",
            "display_name": f"SyncTarget {fx.tag}",
            "properties": [
                {"api_name": "name", "data_type": "string"},
                {"api_name": "email", "data_type": "string"},
            ],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture(scope="module")
def sync_source_id(
    client: TestClient, fx: Fixture, sync_type_id: str, customers_dataset: str
) -> str:
    r = client.post(
        sbase(fx),
        headers=hdr(fx.editor_sub),
        json={
            "object_type_id": sync_type_id,
            "dataset_id": customers_dataset,
            "primary_key_column": "customer_id",
            "column_mappings": {"name": "name", "email": "email"},
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_viewer_cannot_sync(client: TestClient, fx: Fixture, sync_source_id: str) -> None:
    r = client.post(f"{sbase(fx)}/{sync_source_id}/sync", headers=hdr(fx.viewer_sub))
    assert r.status_code == 403


def test_sync_upserts_instances(
    client: TestClient, fx: Fixture, sync_source_id: str, sync_type_id: str
) -> None:
    r = client.post(f"{sbase(fx)}/{sync_source_id}/sync", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["upserted"] == 2  # two rows in CUSTOMERS
    assert body["removed"] == 0
    assert body["source"]["sync_status"] == "ok"
    assert body["source"]["last_synced_at"] is not None

    r = client.get(ibase(fx, sync_type_id), headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    page = r.json()
    assert page["total"] == 2
    by_name = {item["properties"]["name"]: item for item in page["items"]}
    assert set(by_name) == {"Ada Lovelace", "Grace Hopper"}
    assert by_name["Ada Lovelace"]["properties"]["email"] == "ada@example.com"
    assert by_name["Ada Lovelace"]["primary_key"] == "1"


def test_instance_detail_matches_list(
    client: TestClient, fx: Fixture, sync_type_id: str
) -> None:
    r = client.get(ibase(fx, sync_type_id), headers=hdr(fx.viewer_sub))
    instance_id = r.json()["items"][0]["id"]
    r = client.get(f"{ibase(fx, sync_type_id)}/{instance_id}", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    assert r.json()["id"] == instance_id


def test_resync_is_idempotent(
    client: TestClient, fx: Fixture, sync_source_id: str, sync_type_id: str
) -> None:
    r = client.post(f"{sbase(fx)}/{sync_source_id}/sync", headers=hdr(fx.editor_sub))
    assert r.status_code == 200
    body = r.json()
    assert body["upserted"] == 2 and body["removed"] == 0

    r = client.get(ibase(fx, sync_type_id), headers=hdr(fx.viewer_sub))
    assert r.json()["total"] == 2  # no duplicates from the re-sync


def test_unknown_instance_is_404(client: TestClient, fx: Fixture, sync_type_id: str) -> None:
    import uuid

    r = client.get(
        f"{ibase(fx, sync_type_id)}/{uuid.uuid4()}", headers=hdr(fx.viewer_sub)
    )
    assert r.status_code == 404


def test_delete_source_cascades_instances(
    client: TestClient, fx: Fixture, sync_source_id: str, sync_type_id: str
) -> None:
    assert client.delete(
        f"{sbase(fx)}/{sync_source_id}", headers=hdr(fx.editor_sub)
    ).status_code == 204
    r = client.get(ibase(fx, sync_type_id), headers=hdr(fx.viewer_sub))
    assert r.json()["total"] == 0


def test_sync_audited(client: TestClient, fx: Fixture) -> None:
    r = client.get("/api/org/audit?limit=200", headers=hdr(fx.admin_sub))
    actions = {e["action"] for e in r.json()}
    assert "object_type_source.sync" in actions
