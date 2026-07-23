"""Models layer tests. Two uploaded datasets feed a join transform; the run
creates a model_output dataset, a re-run versions it, and lineage walks the
whole graph. Failure paths must leave truthful run records."""
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

ORDERS = b"order_id,customer_id,total_pence\n1,10,1200\n2,11,80\n3,10,455\n4,12,3100\n"
CUSTOMERS = b"customer_id,region\n10,north\n11,south\n12,north\n"


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("models-storage")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def dbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets"


def mbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/models"


@pytest.fixture(scope="module")
def input_datasets(client: TestClient, fx: Fixture) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, filename, content in [
        (f"Orders M {fx.tag}", "orders.csv", ORDERS),
        (f"Customers M {fx.tag}", "customers.csv", CUSTOMERS),
    ]:
        r = client.post(
            f"{dbase(fx)}/upload",
            headers=hdr(fx.editor_sub),
            data={"name": name},
            files={"file": (filename, io.BytesIO(content), "text/csv")},
        )
        assert r.status_code == 201, r.text
        out[name] = r.json()["id"]
    return out


JOIN_SQL = """
SELECT c.region, count(*) AS orders, sum(o.total_pence) AS revenue_pence
  FROM orders o JOIN customers c USING (customer_id)
 GROUP BY c.region ORDER BY revenue_pence DESC
"""


@pytest.fixture(scope="module")
def model_id(client: TestClient, fx: Fixture, input_datasets: dict[str, str]) -> str:
    ids = list(input_datasets.values())
    r = client.post(
        mbase(fx),
        headers=hdr(fx.editor_sub),
        json={
            "name": f"Revenue By Region {fx.tag}",
            "code": JOIN_SQL,
            "inputs": [
                {"dataset_id": ids[0], "input_alias": "orders"},
                {"dataset_id": ids[1], "input_alias": "customers"},
            ],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert {i["input_alias"] for i in body["inputs"]} == {"orders", "customers"}
    return body["id"]


def test_python_model_run_is_queued_for_the_worker(
    client: TestClient, fx: Fixture, input_datasets: dict[str, str]
) -> None:
    ids = list(input_datasets.values())
    r = client.post(
        mbase(fx), headers=hdr(fx.editor_sub),
        json={
            "name": f"Py {fx.tag}", "language": "python", "code": "output = orders",
            "inputs": [{"dataset_id": ids[0], "input_alias": "orders"}],
        },
    )
    assert r.status_code == 201, r.text
    py_model_id = r.json()["id"]

    # Running it doesn't execute inline — a real process boundary is needed
    # (services/models.py's docstring) — it's left queued for the worker.
    r = client.post(f"{mbase(fx)}/{py_model_id}/run", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "queued"
    assert body["output_dataset"] is None

    r = client.get(f"{mbase(fx)}/{py_model_id}/runs", headers=hdr(fx.viewer_sub))
    assert r.json()[0]["status"] == "queued"


def test_cron_schedule_sets_next_run_at(client: TestClient, fx: Fixture, model_id: str) -> None:
    r = client.patch(
        f"{mbase(fx)}/{model_id}", headers=hdr(fx.editor_sub),
        json={"trigger_mode": "cron", "cron_schedule": "*/15 * * * *"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["trigger_mode"] == "cron"
    assert body["cron_schedule"] == "*/15 * * * *"
    assert body["next_run_at"] is not None

    r = client.patch(
        f"{mbase(fx)}/{model_id}", headers=hdr(fx.editor_sub),
        json={"trigger_mode": "cron", "cron_schedule": "not a cron expression"},
    )
    assert r.status_code == 422

    # switching back to manual clears the schedule
    r = client.patch(
        f"{mbase(fx)}/{model_id}", headers=hdr(fx.editor_sub),
        json={"trigger_mode": "manual"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["trigger_mode"] == "manual"
    assert body["cron_schedule"] is None
    assert body["next_run_at"] is None


def test_viewer_cannot_create_or_run(client: TestClient, fx: Fixture, model_id: str) -> None:
    r = client.post(mbase(fx), headers=hdr(fx.viewer_sub), json={"name": "Nope"})
    assert r.status_code == 403
    assert client.post(f"{mbase(fx)}/{model_id}/run", headers=hdr(fx.viewer_sub)).status_code == 403


def test_run_creates_output_dataset(client: TestClient, fx: Fixture, model_id: str) -> None:
    r = client.post(f"{mbase(fx)}/{model_id}/run", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["rows_produced"] == 2
    out = body["output_dataset"]
    assert out["current_version"] == 1

    # Output is a first-class dataset: origin, preview, query.
    r = client.get(f"{dbase(fx)}/{out['id']}", headers=hdr(fx.viewer_sub))
    assert r.json()["origin"] == "model_output"
    r = client.post(
        f"{dbase(fx)}/{out['id']}/query", headers=hdr(fx.viewer_sub),
        json={"sql": "SELECT region, revenue_pence FROM dataset ORDER BY revenue_pence DESC"},
    )
    assert r.json()["rows"] == [["north", 4755], ["south", 80]]


def test_rerun_versions_output(client: TestClient, fx: Fixture, model_id: str) -> None:
    r = client.post(f"{mbase(fx)}/{model_id}/run", headers=hdr(fx.editor_sub))
    assert r.status_code == 200
    out = r.json()["output_dataset"]
    assert out["current_version"] == 2
    r = client.get(f"{dbase(fx)}/{out['id']}/versions", headers=hdr(fx.viewer_sub))
    versions = r.json()
    assert [v["version_number"] for v in versions] == [2, 1]
    assert {v["produced_by_kind"] for v in versions} == {"model"}


def test_failed_run_recorded_truthfully(client: TestClient, fx: Fixture, model_id: str) -> None:
    r = client.patch(
        f"{mbase(fx)}/{model_id}", headers=hdr(fx.editor_sub),
        json={"code": "SELECT missing_column FROM orders"},
    )
    assert r.status_code == 200
    r = client.post(f"{mbase(fx)}/{model_id}/run", headers=hdr(fx.editor_sub))
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False and "missing_column" in body["error"]

    r = client.get(f"{mbase(fx)}/{model_id}/runs", headers=hdr(fx.viewer_sub))
    runs = r.json()
    assert runs[0]["status"] == "failed" and "missing_column" in runs[0]["error_message"]
    assert runs[1]["status"] == "succeeded" and runs[1]["rows_produced"] == 2
    assert runs[1]["output_version"] is not None

    # restore working SQL for later tests
    client.patch(f"{mbase(fx)}/{model_id}", headers=hdr(fx.editor_sub), json={"code": JOIN_SQL})


def test_transform_sandbox_holds(client: TestClient, fx: Fixture, model_id: str) -> None:
    r = client.patch(
        f"{mbase(fx)}/{model_id}", headers=hdr(fx.editor_sub),
        json={"code": "SELECT * FROM read_csv_auto('/etc/passwd')"},
    )
    r = client.post(f"{mbase(fx)}/{model_id}/run", headers=hdr(fx.editor_sub))
    body = r.json()
    assert body["ok"] is False
    assert "root" not in r.text
    client.patch(f"{mbase(fx)}/{model_id}", headers=hdr(fx.editor_sub), json={"code": JOIN_SQL})


def test_bad_alias_rejected(client: TestClient, fx: Fixture, input_datasets: dict[str, str]) -> None:
    ids = list(input_datasets.values())
    r = client.post(
        mbase(fx), headers=hdr(fx.editor_sub),
        json={"name": f"BadAlias {fx.tag}", "code": "SELECT 1",
              "inputs": [{"dataset_id": ids[0], "input_alias": "drop table; x"}]},
    )
    assert r.status_code == 422


def test_cross_project_input_rejected(client: TestClient, fx: Fixture) -> None:
    import uuid

    r = client.post(
        mbase(fx), headers=hdr(fx.editor_sub),
        json={"name": f"Foreign {fx.tag}", "code": "SELECT 1",
              "inputs": [{"dataset_id": str(uuid.uuid4()), "input_alias": "x"}]},
    )
    assert r.status_code == 404  # unknown dataset looks the same as forbidden


def test_lineage_walks_both_directions(
    client: TestClient, fx: Fixture, model_id: str, input_datasets: dict[str, str]
) -> None:
    orders_id = input_datasets[f"Orders M {fx.tag}"]
    r = client.get(f"{dbase(fx)}/{orders_id}/lineage", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    graph = r.json()
    names = {d["name"] for d in graph["datasets"]}
    # From an input dataset the walk finds the model and its output.
    assert f"Orders M {fx.tag}" in names
    assert f"Customers M {fx.tag}" in names
    assert f"Revenue By Region {fx.tag}" in names  # output dataset carries model name
    assert any(m["name"] == f"Revenue By Region {fx.tag}" for m in graph["models"])
    assert graph["mermaid"].startswith("graph LR")
    assert "-->" in graph["mermaid"]


def test_delete_model_keeps_output_dataset(
    client: TestClient, fx: Fixture, model_id: str
) -> None:
    r = client.get(f"{mbase(fx)}/{model_id}", headers=hdr(fx.editor_sub))
    out_id = r.json()["output_dataset_id"]
    assert client.delete(f"{mbase(fx)}/{model_id}", headers=hdr(fx.editor_sub)).status_code == 204
    # Data outlives the transform that made it.
    r = client.get(f"{dbase(fx)}/{out_id}", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200


def test_model_actions_audited(client: TestClient, fx: Fixture) -> None:
    r = client.get("/api/org/audit?limit=200", headers=hdr(fx.admin_sub))
    actions = {e["action"] for e in r.json()}
    assert {"model.create", "model.run", "model.update", "model.delete"} <= actions
