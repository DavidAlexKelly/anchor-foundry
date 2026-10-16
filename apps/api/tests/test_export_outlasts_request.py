"""An export run is recorded as running while it runs (§968; db 0172).

A run from the API wrote its row only once it had finished, so one that
outlasted CloudFront's sixty seconds was a 504 with nothing to say it was
still going, and pressing Run again sent the same rows twice. These hold what
replaced that: the row opened first and completed after, a run that outlasts
its request answered with that row, one run at a time, and a run whose API
stopped under it failed by the sweep rather than running for good.
"""
from __future__ import annotations

import os
import sys
import time

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, hdr  # noqa: E402
from test_export_runs import (  # noqa: E402,F401 (fixtures)
    base, client, destination, destination_connection, fx, make_export, make_table, rows_in,
    storage_root, versioned,
)
from src.lib import long_work  # noqa: E402
from src.services import export_runs  # noqa: E402

ADMIN_DSN = os.environ["TEST_ADMIN_DSN"]


@pytest.fixture()
def export_id(client: TestClient, fx: Fixture, destination: dict) -> str:
    make_table("orders", "id bigint, email text")
    cid = destination_connection(client, fx, destination)
    _model, did = versioned(client, fx)
    return make_export(client, fx, cid, did, mode="mirror").json()["id"]


def history(client: TestClient, fx: Fixture, export_id: str) -> list[dict]:
    r = client.get(f"{base(fx)}/exports/{export_id}/runs", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return r.json()["runs"]


def settled(client: TestClient, fx: Fixture, export_id: str, run_id: str) -> dict:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        run = next(r for r in history(client, fx, export_id) if r["id"] == run_id)
        if run["status"] != "running":
            return run
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} still running")


def post_run(client: TestClient, fx: Fixture, export_id: str):
    return client.post(f"{base(fx)}/exports/{export_id}/run", headers=hdr(fx.editor_sub))


def test_a_run_that_finishes_in_time_is_one_row_answered_whole(
    client: TestClient, fx: Fixture, export_id: str
) -> None:
    r = post_run(client, fx, export_id)
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["rows_written"]) == ("succeeded", 2)
    # Opened and completed: one row, not a running one beside a finished one.
    assert [run["id"] for run in history(client, fx, export_id)] == [r.json()["id"]]


def test_a_run_that_outlasts_its_request_answers_with_its_running_row(
    client: TestClient, fx: Fixture, export_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(long_work, "ANSWER_WITHIN_S", 0)
    r = post_run(client, fx, export_id)
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "running" and r.json()["finished_at"] is None
    run = settled(client, fx, export_id, r.json()["id"])
    assert (run["status"], run["rows_written"]) == ("succeeded", 2)
    assert len(rows_in("orders")) == 2
    with psycopg.connect(ADMIN_DSN) as conn:
        assert conn.execute("SELECT last_version FROM exports WHERE id = %s",
                            (export_id,)).fetchone()[0] == run["dataset_version"]


def test_a_second_run_is_refused_while_one_runs(
    client: TestClient, fx: Fixture, export_id: str
) -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("INSERT INTO export_runs (export_id, status, dataset_version)"
                     " VALUES (%s, 'running', 1)", (export_id,))
    r = post_run(client, fx, export_id)
    assert r.status_code == 409, r.text
    assert "already running" in r.json()["detail"]
    assert len(rows_in("orders")) == 0


def test_a_run_the_api_stopped_under_is_failed_by_the_sweep(
    client: TestClient, fx: Fixture, export_id: str
) -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("INSERT INTO export_runs (export_id, status, dataset_version, started_at)"
                     " VALUES (%s, 'running', 1, now() - interval '31 minutes')", (export_id,))
        # The worker's call, which names four intervals and takes the fifth's default.
        conn.execute("SELECT fail_abandoned_runs(interval '1 day', interval '1 day',"
                     " interval '1 day', interval '1 day')")
    [run] = history(client, fx, export_id)
    assert run["status"] == "failed"
    assert run["error"] == "the platform stopped while this export ran; run it again"
    # And the export can run again.
    assert post_run(client, fx, export_id).status_code == 200


def test_a_fault_in_the_run_completes_its_row_as_failed(
    client: TestClient, fx: Fixture, export_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*args, **kwargs):
        raise RuntimeError("a bug in the export")

    monkeypatch.setattr(export_runs, "perform", broken)
    with pytest.raises(RuntimeError, match="a bug in the export"):
        post_run(client, fx, export_id)
    [run] = history(client, fx, export_id)
    assert (run["status"], run["error"]) == (
        "failed", "the export stopped unexpectedly; run it again")
