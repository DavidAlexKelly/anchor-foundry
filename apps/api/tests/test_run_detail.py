"""A job's detail: progress, specification, files and resulting schema (§507;
`dataset-preview` p.3).

> "Upon selection, a detailed Job view appears on the right showing detailed
> job information, including progress, specification, build logs, files and
> the resulting schema." (p.3)

The build log is §358's and has its own suite.
"""
from __future__ import annotations

import io
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
from src.routes import datasets as ds_routes  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

ROWS = b"id,val\n1,a\n2,b\n3,c\n"


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def storage(tmp_path_factory: pytest.TempPathFactory) -> LocalStorageGateway:
    return LocalStorageGateway(str(tmp_path_factory.mktemp("run-detail-storage")))


@pytest.fixture(scope="module")
def client(storage: LocalStorageGateway) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(storage)
    with TestClient(create_app(), raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def base(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


def upload(client: TestClient, fx: Fixture, name: str) -> dict:
    r = client.post(f"{base(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
                    data={"name": name}, files={"file": ("rows.csv", io.BytesIO(ROWS), "text/csv")})
    assert r.status_code == 201, r.text
    return r.json()


def model(client: TestClient, fx: Fixture, source: dict, code: str) -> str:
    r = client.post(f"{base(fx)}/models", headers=hdr(fx.editor_sub), json={
        "name": f"Detail {uuid.uuid4().hex[:6]}", "code": code,
        "inputs": [{"dataset_id": source["id"], "input_alias": "raw"}]})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def runs(client: TestClient, fx: Fixture, model_id: str) -> list[dict]:
    return client.get(f"{base(fx)}/models/{model_id}/runs", headers=hdr(fx.viewer_sub)).json()


def detail(client: TestClient, fx: Fixture, model_id: str, run_id: str, sub=None):
    return client.get(f"{base(fx)}/models/{model_id}/runs/{run_id}/detail",
                      headers=hdr(sub or fx.viewer_sub))


def test_a_run_s_detail_is_what_it_ran_and_what_it_wrote(client, fx, storage) -> None:
    source = upload(client, fx, f"Source {uuid.uuid4().hex[:6]}")
    mid = model(client, fx, source, "SELECT id, val FROM raw")
    client.post(f"{base(fx)}/models/{mid}/run", headers=hdr(fx.editor_sub))
    [run] = runs(client, fx, mid)
    r = detail(client, fx, mid, run["id"])
    assert r.status_code == 200, r.text
    got = r.json()

    progress = got["progress"]
    assert progress["status"] == "succeeded"
    assert progress["waited_ms"] >= 0 and progress["ran_ms"] >= 0
    assert progress["started_at"] and progress["finished_at"]

    spec = got["specification"]
    assert (spec["version_number"], spec["language"], spec["code"]) \
        == (1, "sql", "SELECT id, val FROM raw")
    assert spec["inputs"] == [{"alias": "raw", "dataset_id": source["id"],
                               "dataset_name": source["name"]}]

    output = got["output"]
    assert (output["version_number"], output["row_count"]) == (1, 3)
    assert [c["name"] for c in output["schema"]] == ["id", "val"]
    [written] = output["files"]
    assert written["name"] == "data.parquet" and written["size_bytes"] > 0
    assert "/" not in written["name"]


def test_the_specification_is_the_run_s_not_today_s(client, fx) -> None:
    """A model edited after a run: the run's detail shows the code it ran,
    and the next run's the new code and schema."""
    source = upload(client, fx, f"Source {uuid.uuid4().hex[:6]}")
    mid = model(client, fx, source, "SELECT id, val FROM raw")
    client.post(f"{base(fx)}/models/{mid}/run", headers=hdr(fx.editor_sub))
    client.patch(f"{base(fx)}/models/{mid}", headers=hdr(fx.editor_sub),
                 json={"code": "SELECT id FROM raw WHERE id > 1"})
    client.post(f"{base(fx)}/models/{mid}/run", headers=hdr(fx.editor_sub))
    newer, older = runs(client, fx, mid)
    first = detail(client, fx, mid, older["id"]).json()
    second = detail(client, fx, mid, newer["id"]).json()
    assert first["specification"]["code"] == "SELECT id, val FROM raw"
    assert second["specification"]["code"] == "SELECT id FROM raw WHERE id > 1"
    assert second["specification"]["version_number"] == 2
    assert [c["name"] for c in first["output"]["schema"]] == ["id", "val"]
    assert [c["name"] for c in second["output"]["schema"]] == ["id"]
    assert (second["output"]["version_number"], second["output"]["row_count"]) == (2, 2)


def test_a_failed_run_wrote_nothing_and_says_so(client, fx) -> None:
    source = upload(client, fx, f"Source {uuid.uuid4().hex[:6]}")
    mid = model(client, fx, source, "SELECT nope FROM raw")
    client.post(f"{base(fx)}/models/{mid}/run", headers=hdr(fx.editor_sub))
    [run] = runs(client, fx, mid)
    got = detail(client, fx, mid, run["id"]).json()
    assert got["progress"]["status"] == "failed"
    assert got["output"] is None
    assert got["specification"]["code"] == "SELECT nope FROM raw"


def test_a_run_with_no_recorded_version_and_a_deleted_input(client, fx, storage) -> None:
    """A run from before db 0024 has no version, and says so rather than
    showing today's model. A deleted input keeps its alias and loses its
    name; a file gone from storage keeps its name and loses its size."""
    source = upload(client, fx, f"Source {uuid.uuid4().hex[:6]}")
    mid = model(client, fx, source, "SELECT id, val FROM raw")
    client.post(f"{base(fx)}/models/{mid}/run", headers=hdr(fx.editor_sub))
    [run] = runs(client, fx, mid)
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        key = conn.execute(
            "SELECT v.s3_manifest_key FROM dataset_versions v JOIN model_runs r"
            " ON r.output_version = v.id WHERE r.id = %s", (run["id"],)).fetchone()[0]
    os.remove(storage.local_path(key))
    assert detail(client, fx, mid, run["id"]).json()["output"]["files"][0]["size_bytes"] is None
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("DELETE FROM model_inputs WHERE dataset_id = %s", (source["id"],))
        conn.execute("DELETE FROM datasets WHERE id = %s", (source["id"],))
    spec = detail(client, fx, mid, run["id"]).json()["specification"]
    assert spec["inputs"] == [{"alias": "raw", "dataset_id": source["id"], "dataset_name": None}]
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE model_runs SET model_version = NULL WHERE id = %s", (run["id"],))
    assert detail(client, fx, mid, run["id"]).json()["specification"] is None


def test_a_run_is_read_through_its_own_model(client, fx) -> None:
    source = upload(client, fx, f"Source {uuid.uuid4().hex[:6]}")
    first = model(client, fx, source, "SELECT id FROM raw")
    other = model(client, fx, source, "SELECT val FROM raw")
    client.post(f"{base(fx)}/models/{first}/run", headers=hdr(fx.editor_sub))
    [run] = runs(client, fx, first)
    assert detail(client, fx, other, run["id"]).status_code == 404
    assert detail(client, fx, first, str(uuid.uuid4())).status_code == 404
    assert detail(client, fx, first, run["id"], sub=fx.outsider_sub).status_code in (403, 404)
    # A model the reader can see in another project is not this project's:
    # the path names a project, and the model has to be in it.
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        other = conn.execute(
            "INSERT INTO projects (workspace_id, name, slug, created_by)"
            " VALUES (%s, %s, %s, %s) RETURNING id",
            (fx.workspace, "Elsewhere", f"elsewhere-{uuid.uuid4().hex[:6]}", fx.owner)).fetchone()[0]
        conn.execute("UPDATE models SET project_id = %s WHERE id = %s", (other, first))
    elsewhere = f"/api/workspaces/{fx.workspace}/projects/{other}/models/{first}/runs/{run['id']}/detail"
    assert client.get(elsewhere, headers=hdr(fx.viewer_sub)).status_code == 200
    assert detail(client, fx, first, run["id"]).status_code == 404


def test_progress_is_how_long_it_waited_and_how_long_it_ran(client, fx) -> None:
    source = upload(client, fx, f"Source {uuid.uuid4().hex[:6]}")
    mid = model(client, fx, source, "SELECT id FROM raw")
    client.post(f"{base(fx)}/models/{mid}/run", headers=hdr(fx.editor_sub))
    [run] = runs(client, fx, mid)
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "UPDATE model_runs SET queued_at = '2026-09-26T10:00:00Z',"
            " started_at = '2026-09-26T10:00:02Z', finished_at = '2026-09-26T10:00:07.5Z'"
            " WHERE id = %s", (run["id"],))
        queued = conn.execute(
            "INSERT INTO model_runs (model_id, status) VALUES (%s, 'queued') RETURNING id",
            (mid,)).fetchone()[0]
    progress = detail(client, fx, mid, run["id"]).json()["progress"]
    assert (progress["waited_ms"], progress["ran_ms"]) == (2000, 5500)
    waiting = detail(client, fx, mid, str(queued)).json()
    assert waiting["progress"]["status"] == "queued"
    assert (waiting["progress"]["waited_ms"], waiting["progress"]["ran_ms"]) == (None, None)
    assert (waiting["specification"], waiting["output"]) == (None, None)
