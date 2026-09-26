"""The schedules that will update a dataset (§508; `dataset-preview` p.3).

> "Schedules: Information about any configured build schedules that will run
> to update the dataset." (p.3)
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
        LocalStorageGateway(str(tmp_path_factory.mktemp("schedules-storage"))))
    with TestClient(create_app(), raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def base(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


def upload(client, fx, name: str) -> dict:
    r = client.post(f"{base(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
                    data={"name": name}, files={"file": ("rows.csv", io.BytesIO(ROWS), "text/csv")})
    assert r.status_code == 201, r.text
    return r.json()


def schedules(client, fx, dataset_id: str, sub=None):
    return client.get(f"{base(fx)}/datasets/{dataset_id}/schedules",
                      headers=hdr(sub or fx.viewer_sub))


def transform(client, fx, name: str, inputs: list[dict], **extra) -> tuple[str, dict]:
    r = client.post(f"{base(fx)}/models", headers=hdr(fx.editor_sub), json={
        "name": name, "code": "SELECT id FROM in0",
        "inputs": [{"dataset_id": d["id"], "input_alias": f"in{i}"} for i, d in enumerate(inputs)]})
    assert r.status_code in (200, 201), r.text
    mid = r.json()["id"]
    if extra:
        # The trigger is an edit, not a create field.
        r = client.patch(f"{base(fx)}/models/{mid}", headers=hdr(fx.editor_sub), json=extra)
        assert r.status_code == 200, r.text
    out = client.post(f"{base(fx)}/models/{mid}/run", headers=hdr(fx.editor_sub)).json()
    return mid, out["output_dataset"]


def test_a_dataset_nothing_schedules_has_no_schedules(client, fx) -> None:
    made = upload(client, fx, f"Plain {uuid.uuid4().hex[:6]}")
    assert schedules(client, fx, made["id"]).json() == []
    # A transform on `manual` will not run on its own, so it is not one.
    _, out = transform(client, fx, f"Manual {uuid.uuid4().hex[:6]}", [made])
    assert schedules(client, fx, out["id"]).json() == []


def test_a_cron_transform_says_its_expression_and_next_run(client, fx) -> None:
    source = upload(client, fx, f"Src {uuid.uuid4().hex[:6]}")
    name = f"Nightly {uuid.uuid4().hex[:6]}"
    mid, out = transform(client, fx, name, [source],
                         trigger_mode="cron", cron_schedule="0 3 * * *")
    [got] = schedules(client, fx, out["id"]).json()
    assert {k: got[k] for k in ("kind", "name", "trigger", "cron", "watches", "mode")} == {
        "kind": "transform", "name": name, "trigger": "cron", "cron": "0 3 * * *",
        "watches": [], "mode": None}
    assert got["resource_id"]
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        stored = conn.execute("SELECT next_run_at FROM models WHERE id = %s", (mid,)).fetchone()[0]
        assert stored is not None
        assert got["next_run_at"].replace("Z", "+00:00") == stored.isoformat()
        # Never fired yet: passed through as null, which the worker reads as due.
        conn.execute("UPDATE models SET next_run_at = NULL WHERE id = %s", (mid,))
    assert schedules(client, fx, out["id"]).json()[0]["next_run_at"] is None


def test_an_upstream_transform_says_what_it_waits_on(client, fx) -> None:
    tag = uuid.uuid4().hex[:6]
    zeta, alpha = upload(client, fx, f"Zeta {tag}"), upload(client, fx, f"Alpha {tag}")
    mid, out = transform(client, fx, f"Follower {tag}", [zeta, alpha], trigger_mode="upstream")
    [got] = schedules(client, fx, out["id"]).json()
    assert (got["trigger"], got["cron"], got["next_run_at"]) == ("upstream", None, None)
    assert got["watches"] == [alpha["name"], zeta["name"]]
    # A stale next_run_at left over from a cron is not this trigger's.
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE models SET next_run_at = now(), cron_schedule = '0 3 * * *'"
                     " WHERE id = %s", (mid,))
    got = schedules(client, fx, out["id"]).json()[0]
    assert (got["cron"], got["next_run_at"]) == (None, None)


def test_a_scheduled_sync_is_listed_after_the_transforms(client, fx) -> None:
    tag = uuid.uuid4().hex[:6]
    source = upload(client, fx, f"Src {tag}")
    _, out = transform(client, fx, f"Beta {tag}", [source],
                       trigger_mode="cron", cron_schedule="*/15 * * * *")
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        for name, schedule in ((f"Aaa warehouse {tag}", "0 * * * *"),
                               (f"Unscheduled {tag}", None)):
            conn.execute(
                """INSERT INTO connections (workspace_id, project_id, scope, name, source_type,
                                            config, created_by, sync_mode, sync_schedule,
                                            sync_dataset_id, sync_primary_key_column,
                                            sync_cursor_column, sync_next_run_at)
                   VALUES (%s, %s, 'project', %s, 'postgres', '{}'::jsonb, %s, 'incremental',
                           %s, %s, 'id', 'id', '2026-09-27T04:00:00Z')""",
                (fx.workspace, fx.project, name, fx.owner, schedule, out["id"]))
    got = schedules(client, fx, out["id"]).json()
    # Transforms first, then syncs: not one list in name order.
    assert [(s["kind"], s["name"]) for s in got] == [
        ("transform", f"Beta {tag}"), ("sync", f"Aaa warehouse {tag}")]
    sync = got[1]
    assert (sync["trigger"], sync["cron"], sync["mode"], sync["watches"]) == (
        "cron", "0 * * * *", "incremental", [])
    assert sync["resource_id"]
    assert sync["next_run_at"].replace("Z", "+00:00") == "2026-09-27T04:00:00+00:00"


def test_transforms_are_in_name_order(client, fx) -> None:
    tag = uuid.uuid4().hex[:6]
    source = upload(client, fx, f"Src {tag}")
    _, out = transform(client, fx, f"Zulu {tag}", [source], trigger_mode="upstream")
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO models (project_id, name, language, code, output_dataset_id, trigger_mode)"
            " VALUES (%s, %s, 'sql', 'SELECT 1', %s, 'upstream')", (fx.project, f"Alpha {tag}", out["id"]))
    assert [s["name"] for s in schedules(client, fx, out["id"]).json()] == [
        f"Alpha {tag}", f"Zulu {tag}"]


def test_schedules_are_read_as_the_reader_and_within_the_project(client, fx) -> None:
    made = upload(client, fx, f"Private {uuid.uuid4().hex[:6]}")
    assert schedules(client, fx, made["id"], sub=fx.outsider_sub).status_code in (403, 404)
    assert schedules(client, fx, str(uuid.uuid4())).status_code == 404
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        other = conn.execute(
            "INSERT INTO projects (workspace_id, name, slug, created_by)"
            " VALUES (%s, %s, %s, %s) RETURNING id",
            (fx.workspace, "Elsewhere", f"elsewhere-{uuid.uuid4().hex[:6]}", fx.owner)).fetchone()[0]
        conn.execute("UPDATE datasets SET project_id = %s WHERE id = %s", (other, made["id"]))
    assert client.get(f"/api/workspaces/{fx.workspace}/projects/{other}/datasets/{made['id']}/schedules",
                      headers=hdr(fx.viewer_sub)).status_code == 200
    assert schedules(client, fx, made["id"]).status_code == 404


def test_what_an_upstream_trigger_waits_on_is_in_name_order(client, fx) -> None:
    """Pinned so that no order but the names' can pass: Zeta is inserted
    first **and** has the smaller id, so a list in either of those orders
    starts with it."""
    tag = uuid.uuid4().hex[:6]
    out = upload(client, fx, f"Out {tag}")
    ids = {"Zeta": f"00000000-0000-4000-8000-{tag}000000", "Alpha": f"ffffffff-0000-4000-8000-{tag}000000"}
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        for name, did in ids.items():
            conn.execute(
                """INSERT INTO datasets (id, project_id, workspace_id, name, slug, origin,
                                         s3_location, table_schema, row_count, current_version)
                   VALUES (%s, %s, %s, %s, %s, 'upload', 'x', '[]'::jsonb, 0, 1)""",
                (did, fx.project, fx.workspace, f"{name} {tag}", f"s-{uuid.uuid4().hex[:10]}"))
        mid = conn.execute(
            "INSERT INTO models (project_id, name, language, code, output_dataset_id, trigger_mode)"
            " VALUES (%s, %s, 'sql', 'SELECT 1', %s, 'upstream') RETURNING id",
            (fx.project, f"Follower {tag}", out["id"])).fetchone()[0]
        for alias, name in (("z", "Zeta"), ("a", "Alpha")):
            conn.execute("INSERT INTO model_inputs (model_id, dataset_id, input_alias)"
                         " VALUES (%s, %s, %s)", (mid, ids[name], alias))
    [got] = schedules(client, fx, out["id"]).json()
    assert got["watches"] == [f"Alpha {tag}", f"Zeta {tag}"]
