"""p.51's third question on the lineage graph (§583).

    "There are a few reasons why your dataset may not be up to date. Common
     scenarios to explore are: Is my dataset build failing? Is there an
     upstream dataset that hasn't built and isn't up to date? Have we received
     up-to-date data from the source?" (`data-lineage` p.51)

§352 answered the first two and named the third: it needs an expectation of
how often data arrives. A dataset a sync writes has one - the sync. It is
behind its source when the latest run into it failed, or when its schedule
says it should have run and it has not. A dataset nothing syncs has no
expectation, and says nothing.

Each test builds its datasets in a project of its own, because the graph is
per project and these assert on what a whole graph says.
"""
from __future__ import annotations

import io
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_pipeline import (  # noqa: E402,F401
    ROWS, _connection, _fresh_identity_cache, _sync_run, client, fx,
)
from test_api import ADMIN_DSN, hdr  # noqa: E402
from src.services import pipeline  # noqa: E402

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


# ---- the rule --------------------------------------------------------------------
def test_the_latest_run_failing_is_behind() -> None:
    runs = [("succeeded", NOW - 2 * HOUR), ("failed", NOW - HOUR)]
    assert pipeline.source_behind(runs, schedule=None, next_run_at=None, now=NOW) == "failed"


def test_a_failure_since_put_right_is_not() -> None:
    runs = [("failed", NOW - 2 * HOUR), ("succeeded", NOW - HOUR)]
    assert pipeline.source_behind(runs, schedule=None, next_run_at=None, now=NOW) is None


def test_the_latest_is_by_when_it_started_not_by_order() -> None:
    runs = [("failed", NOW - HOUR), ("succeeded", NOW - 2 * HOUR)]
    assert pipeline.source_behind(runs, schedule=None, next_run_at=None, now=NOW) == "failed"


def test_a_scheduled_sync_past_its_grace_is_overdue() -> None:
    ok = [("succeeded", NOW - 5 * HOUR)]
    late = NOW - pipeline.OVERDUE_GRACE - timedelta(seconds=1)
    assert pipeline.source_behind(ok, schedule="0 * * * *", next_run_at=late, now=NOW) == "overdue"
    within = NOW - pipeline.OVERDUE_GRACE + timedelta(seconds=1)
    assert pipeline.source_behind(ok, schedule="0 * * * *", next_run_at=within, now=NOW) is None
    assert pipeline.source_behind(ok, schedule="0 * * * *", next_run_at=NOW + HOUR, now=NOW) is None


def test_a_sync_only_run_by_hand_is_never_late() -> None:
    ok = [("succeeded", NOW - 50 * HOUR)]
    assert pipeline.source_behind(ok, schedule=None, next_run_at=NOW - 40 * HOUR, now=NOW) is None
    assert pipeline.source_behind(ok, schedule="", next_run_at=NOW - 40 * HOUR, now=NOW) is None


def test_a_failure_says_failed_even_when_also_late() -> None:
    runs = [("failed", NOW - HOUR)]
    assert pipeline.source_behind(runs, schedule="0 * * * *", next_run_at=NOW - 5 * HOUR,
                                  now=NOW) == "failed"


# ---- on the graph ----------------------------------------------------------------
@pytest.fixture()
def project(client, fx) -> dict:
    stamp = uuid.uuid4().hex[:8]
    r = client.post(f"/api/workspaces/{fx.workspace}/projects", headers=hdr(fx.owner_sub),
                    json={"name": f"Behind {stamp}", "slug": f"behind-{stamp}"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    return {"id": pid, "base": f"/api/workspaces/{fx.workspace}/projects/{pid}", "stamp": stamp}


def upload(client, fx, project, name: str) -> str:
    r = client.post(f"{project['base']}/datasets/upload", headers=hdr(fx.owner_sub),
                    data={"name": f"{name} {project['stamp']}"},
                    files={"file": ("rows.csv", io.BytesIO(ROWS), "text/csv")})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def connection(client, fx, project, name: str) -> str:
    r = client.post(f"{project['base']}/connections", headers=hdr(fx.editor_sub), json={
        "name": f"{name} {project['stamp']}", "source_type": "postgres",
        "config": {"host": "nowhere.invalid", "port": 5432, "database": "src", "user": "u"},
        "secret": {"password": "x"}})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def schedule(connection_id: str, dataset: str, next_run_at: datetime) -> None:
    import psycopg

    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE connections SET sync_schedule = '0 * * * *', "
                     "sync_dataset_id = %s, sync_next_run_at = %s WHERE id = %s",
                     (dataset, next_run_at, connection_id))


def nodes(client, fx, project) -> dict:
    r = client.get(f"{project['base']}/pipeline", headers=hdr(fx.owner_sub))
    assert r.status_code == 200, r.text
    return {n["id"]: n for n in r.json()["nodes"]}


def test_a_dataset_whose_latest_sync_failed_is_behind_its_source(client, fx, project) -> None:
    synced = upload(client, fx, project, "Synced")
    feeder = connection(client, fx, project, "Feeder")
    _sync_run(feeder, synced, "succeeded", "public.a")
    _sync_run(feeder, synced, "failed", "public.a")
    got = nodes(client, fx, project)[f"dataset:{synced}"]
    assert (got["out_of_date"], got["out_of_date_reason"], got["source_behind"]) == (
        True, "source_is_behind", "failed")


def test_a_sync_that_recovered_is_not(client, fx, project) -> None:
    synced = upload(client, fx, project, "Recovered")
    feeder = connection(client, fx, project, "Feeder")
    _sync_run(feeder, synced, "failed", "public.a")
    _sync_run(feeder, synced, "succeeded", "public.a")
    got = nodes(client, fx, project)[f"dataset:{synced}"]
    assert (got["out_of_date"], got["out_of_date_reason"], got["source_behind"]) == (
        False, None, None)


def test_an_overdue_scheduled_sync_is_behind_and_its_downstream_says_so(client, fx, project) -> None:
    synced = upload(client, fx, project, "Scheduled")
    feeder = connection(client, fx, project, "Feeder")
    _sync_run(feeder, synced, "succeeded", "public.a")
    schedule(feeder, synced, datetime.now(timezone.utc) - 3 * HOUR)
    r = client.post(f"{project['base']}/models", headers=hdr(fx.owner_sub), json={
        "name": f"Doubled {project['stamp']}", "code": "SELECT id, val * 2 AS v FROM raw",
        "inputs": [{"dataset_id": synced, "input_alias": "raw"}]})
    assert r.status_code == 201, r.text
    ran = client.post(f"{project['base']}/models/{r.json()['id']}/run", headers=hdr(fx.owner_sub))
    assert ran.json()["ok"], ran.text
    built = ran.json()["output_dataset"]["id"]
    got = nodes(client, fx, project)
    assert got[f"dataset:{synced}"]["source_behind"] == "overdue"
    assert got[f"dataset:{synced}"]["out_of_date_reason"] == "source_is_behind"
    # The model's output was built after the sync, so nothing about its inputs
    # is newer - it is behind because its source is.
    assert got[f"dataset:{built}"]["out_of_date_reason"] == "upstream_is_out_of_date"
    assert got[f"dataset:{built}"]["source_behind"] is None


def test_a_schedule_speaks_only_for_the_dataset_it_manages(client, fx, project) -> None:
    """db 0014's `sync_dataset_id`: a connection that has also filled another
    dataset by hand is not late for that one."""
    managed = upload(client, fx, project, "Managed")
    other = upload(client, fx, project, "Other")
    feeder = connection(client, fx, project, "Feeder")
    _sync_run(feeder, managed, "succeeded", "public.a")
    _sync_run(feeder, other, "succeeded", "public.b")
    schedule(feeder, managed, datetime.now(timezone.utc) - 3 * HOUR)
    got = nodes(client, fx, project)
    assert got[f"dataset:{managed}"]["source_behind"] == "overdue"
    assert got[f"dataset:{other}"]["out_of_date"] is False


def test_a_dataset_nothing_syncs_says_nothing_about_a_source(client, fx, project) -> None:
    uploaded = upload(client, fx, project, "Uploaded")
    got = nodes(client, fx, project)[f"dataset:{uploaded}"]
    assert (got["out_of_date"], got["source_behind"]) == (False, None)
