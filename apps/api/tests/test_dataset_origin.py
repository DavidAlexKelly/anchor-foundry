"""How a dataset's current version was made (§506; `dataset-preview` p.3).

> "About: Information including … any tools and input datasets used to create
> the data" (p.3)

Transforms, forks and rollbacks go through the API; the other producers are
written as their rows, since how each comes to write a version is its own
suite's subject.
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

ROWS = b"id,val\n1,a\n2,b\n"


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("origin-storage"))))
    with TestClient(create_app(), raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def base(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


def upload(client, fx, name: str, filename: str = "rows.csv") -> dict:
    r = client.post(f"{base(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
                    data={"name": name}, files={"file": (filename, io.BytesIO(ROWS), "text/csv")})
    assert r.status_code == 201, r.text
    return r.json()


def origin(client, fx, dataset_id: str, sub=None):
    return client.get(f"{base(fx)}/datasets/{dataset_id}/origin", headers=hdr(sub or fx.viewer_sub))


def resource_of(dataset_id: str) -> str:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        return str(conn.execute("SELECT resource_id FROM datasets WHERE id = %s",
                                (dataset_id,)).fetchone()[0])


def test_an_upload_says_its_file(client, fx) -> None:
    made = upload(client, fx, f"Uploaded {uuid.uuid4().hex[:6]}", "ledger.csv")
    got = origin(client, fx, made["id"]).json()
    assert (got["version_number"], got["kind"], got["tool"], got["inputs"]) == (1, "upload", None, [])
    assert got["note"] == "uploaded as ledger.csv"
    assert got["made_at"]


def transform(client, fx, inputs: list[dict], code: str) -> tuple[str, dict]:
    r = client.post(f"{base(fx)}/models", headers=hdr(fx.editor_sub), json={
        "name": f"Maker {uuid.uuid4().hex[:6]}", "code": code,
        "inputs": [{"dataset_id": d["id"], "input_alias": f"in{i}"} for i, d in enumerate(inputs)]})
    assert r.status_code in (200, 201), r.text
    mid = r.json()["id"]
    out = client.post(f"{base(fx)}/models/{mid}/run", headers=hdr(fx.editor_sub)).json()
    return mid, out["output_dataset"]


def test_a_transform_names_itself_and_what_its_run_read(client, fx) -> None:
    # Made in reverse name order, so an order that came from the table rather
    # than from the names would show.
    tag = uuid.uuid4().hex[:6]
    zeta, mu, kappa, alpha = (upload(client, fx, f"{n} {tag}")
                              for n in ("Zeta", "Mu", "Kappa", "Alpha"))
    mid, made = transform(client, fx, [zeta, mu, kappa, alpha],
                          " UNION ALL ".join(f"SELECT id FROM in{i}" for i in range(4)))
    got = origin(client, fx, made["id"]).json()
    assert got["kind"] == "model" and got["note"] is None
    assert got["tool"]["kind"] == "transform" and got["tool"]["resource_id"]
    # Named in order, and linkable.
    assert [d["name"] for d in got["inputs"]] == [
        alpha["name"], kappa["name"], mu["name"], zeta["name"]]
    assert got["inputs"][0]["resource_id"] == resource_of(alpha["id"])

    # The transform changes its inputs and has not run since: this version
    # was still made from what that run read.
    client.patch(f"{base(fx)}/models/{mid}", headers=hdr(fx.editor_sub), json={
        "code": "SELECT id FROM in0", "inputs": [{"dataset_id": zeta["id"], "input_alias": "in0"}]})
    assert [d["name"] for d in origin(client, fx, made["id"]).json()["inputs"]] \
        == [alpha["name"], kappa["name"], mu["name"], zeta["name"]]

    # With no recorded run behind the version, today's inputs stand in, and
    # the answer says so.
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE model_runs SET output_version = NULL WHERE model_id = %s", (mid,))
    got = origin(client, fx, made["id"]).json()
    assert [d["name"] for d in got["inputs"]] == [zeta["name"]]
    assert got["note"] == "the inputs are the transform's today; no recorded run wrote this version"


def test_a_fork_and_a_rollback_say_where_they_came_from(client, fx) -> None:
    source = upload(client, fx, f"Source {uuid.uuid4().hex[:6]}")
    mid, made = transform(client, fx, [source], "SELECT id, val FROM in0")
    client.patch(f"{base(fx)}/models/{mid}", headers=hdr(fx.editor_sub),
                 json={"code": "SELECT id FROM in0"})
    client.post(f"{base(fx)}/models/{mid}/run", headers=hdr(fx.editor_sub))
    r = client.post(f"{base(fx)}/datasets/{made['id']}/fork", headers=hdr(fx.editor_sub),
                    json={"name": f"Fork {uuid.uuid4().hex[:6]}", "version_number": 1})
    assert r.status_code == 201, r.text
    forked = origin(client, fx, r.json()["id"]).json()
    assert (forked["kind"], forked["note"]) == ("fork", "branched from version 1")
    assert [d["name"] for d in forked["inputs"]] == [made["name"]]

    r = client.post(f"{base(fx)}/datasets/{made['id']}/rollback", headers=hdr(fx.editor_sub),
                    json={"version_number": 1})
    assert r.status_code == 200, r.text
    got = origin(client, fx, made["id"]).json()
    assert (got["version_number"], got["kind"], got["note"]) == (3, "rollback", "rolled back to version 1")


def version(fx: Fixture, name: str, kind: str | None, producer: str | None) -> str:
    """A dataset whose one version names `producer` as `kind`."""
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        did = conn.execute(
            """INSERT INTO datasets (project_id, workspace_id, name, slug, origin, s3_location,
                                     table_schema, row_count, current_version)
               VALUES (%s, %s, %s, %s, 'sync', 'x', '[]'::jsonb, 0, 1) RETURNING id""",
            (fx.project, fx.workspace, name, f"v-{uuid.uuid4().hex[:10]}")).fetchone()[0]
        conn.execute(
            """INSERT INTO dataset_versions (dataset_id, version_number, s3_manifest_key,
                                             table_schema, row_count, produced_by_kind, produced_by_id)
               VALUES (%s, 1, 'x', '[]'::jsonb, 0, %s, %s)""", (did, kind, producer))
    return str(did)


def test_a_sync_names_its_connection(client, fx) -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        cid = conn.execute(
            """INSERT INTO connections (workspace_id, project_id, scope, name, source_type,
                                        config, created_by)
               VALUES (%s, %s, 'project', %s, 'postgres', '{}'::jsonb, %s) RETURNING id""",
            (fx.workspace, fx.project, f"Warehouse {uuid.uuid4().hex[:6]}", fx.owner)).fetchone()[0]
    synced = origin(client, fx, version(fx, "Synced", "sync", str(cid))).json()
    assert synced["tool"]["kind"] == "sync" and synced["tool"]["name"].startswith("Warehouse")
    assert synced["tool"]["resource_id"]


def test_an_action_and_a_batch_name_the_action_type(client, fx) -> None:
    r = client.post(f"/api/workspaces/{fx.workspace}/object-types", headers=hdr(fx.editor_sub),
                    json={"api_name": f"Thing{uuid.uuid4().hex[:6]}", "display_name": "Thing",
                          "properties": [{"api_name": "note", "data_type": "string"}]})
    assert r.status_code == 201, r.text
    r = client.post(f"/api/workspaces/{fx.workspace}/action-types", headers=hdr(fx.editor_sub),
                    json={"object_type_id": r.json()["id"], "api_name": f"act_{uuid.uuid4().hex[:6]}",
                          "display_name": "Retriage", "editable_properties": ["note"]})
    assert r.status_code == 201, r.text
    batch = uuid.uuid4()
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        run = conn.execute("INSERT INTO action_runs (action_type_id, batch_id) VALUES (%s, %s)"
                           " RETURNING id", (r.json()["id"], batch)).fetchone()[0]
    one = origin(client, fx, version(fx, "Acted", "action", str(run))).json()
    assert one["tool"] == {"kind": "action", "name": "Retriage", "resource_id": None}
    many = origin(client, fx, version(fx, "Batched", "action_batch", str(batch))).json()
    assert many["tool"] == {"kind": "action", "name": "Retriage", "resource_id": None}
    # The batch id is not a run id, and the run id is not a batch.
    assert origin(client, fx, version(fx, "Crossed", "action", str(batch))).json()["tool"] is None


def test_a_version_whose_producer_is_gone_says_only_its_kind(client, fx) -> None:
    got = origin(client, fx, version(fx, "Orphan", "model", str(uuid.uuid4()))).json()
    assert (got["kind"], got["tool"], got["inputs"]) == ("model", None, [])
    assert origin(client, fx, version(fx, "Lost", "sync", str(uuid.uuid4()))).json()["tool"] is None
    gone = origin(client, fx, version(fx, "Gone back", "rollback", str(uuid.uuid4()))).json()
    assert gone["note"] == "rolled back"
    # No producer recorded at all: nothing to name, and no fallback either.
    for kind in ("model", "fork", "sync", "action", "rollback"):
        got = origin(client, fx, version(fx, f"Anonymous {kind}", kind, None)).json()
        assert (got["kind"], got["tool"], got["inputs"]) == (kind, None, []), kind
        assert got["note"] == ("rolled back" if kind == "rollback" else None), kind


def test_the_origin_is_read_as_the_reader(client, fx) -> None:
    made = upload(client, fx, f"Private {uuid.uuid4().hex[:6]}")
    assert origin(client, fx, made["id"], sub=fx.outsider_sub).status_code in (403, 404)
    assert origin(client, fx, str(uuid.uuid4())).status_code == 404
    # A dataset the reader can see, in another project, is not this project's
    # to answer for: the path names a project, and the answer is scoped to it.
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        other = conn.execute(
            "INSERT INTO projects (workspace_id, name, slug, created_by)"
            " VALUES (%s, %s, %s, %s) RETURNING id",
            (fx.workspace, "Elsewhere", f"elsewhere-{uuid.uuid4().hex[:6]}", fx.owner)).fetchone()[0]
    elsewhere = version(fx, "Elsewhere", "upload", None)
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE datasets SET project_id = %s WHERE id = %s", (other, elsewhere))
    assert client.get(f"/api/workspaces/{fx.workspace}/projects/{other}/datasets/{elsewhere}/origin",
                      headers=hdr(fx.viewer_sub)).status_code == 200
    assert origin(client, fx, elsewhere).status_code == 404


def test_a_reparse_and_an_unrecorded_kind_read_as_their_upload(client, fx) -> None:
    reparsed = version(fx, "Reparsed", "reparse", None)
    older = version(fx, "Older", None, None)
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE datasets SET original_filename = 'raw.tsv' WHERE id = %s", (reparsed,))
    got = origin(client, fx, reparsed).json()
    assert (got["kind"], got["note"]) == ("reparse", "re-parsed from raw.tsv")
    # A version from before `produced_by_kind` was written is an upload, the
    # one thing that could make a dataset then; with no file name kept, there
    # is no note to give.
    got = origin(client, fx, older).json()
    assert (got["kind"], got["note"], got["tool"]) == ("upload", None, None)
