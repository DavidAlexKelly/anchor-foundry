"""A listener's events, archived every five minutes (§519; db 0108;
`data-connection` p.264).

    "Every few minutes, the listener event stream will archive into a backing
     dataset." (p.264)

The API's "Archive now" is `apps/api/tests/test_listener_archive.py`, which
also holds the shared block of the two archivers to the same text. What is
here is the worker's half: discovery, one run per listener, appending, and one
listener's failure not stopping the rest.
"""
from __future__ import annotations

import json
import os
import sys
import uuid

import duckdb
import psycopg
import pytest
from dagster import build_op_context

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from anchor_worker.jobs import listener_archives  # noqa: E402
from anchor_worker.jobs.listener_archives import archive_listener_events  # noqa: E402
from anchor_worker.resources import PlatformDatabase  # noqa: E402
from anchor_worker.storage import gateway_from_env  # noqa: E402

ADMIN_DSN = os.environ["TEST_ADMIN_DSN"]
APP_DSN = os.environ["WORKER_DATABASE_URL"]


@pytest.fixture()
def storage_root(tmp_path, monkeypatch) -> str:
    root = str(tmp_path / "storage")
    monkeypatch.setenv("LOCAL_STORAGE_ROOT", root)
    monkeypatch.delenv("DATA_BUCKET", raising=False)
    return root


@pytest.fixture()
def workspace(storage_root: str):
    tag = uuid.uuid4().hex[:8]
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        org = conn.execute("INSERT INTO organisations (name, slug) VALUES (%s,%s) RETURNING id",
                           (f"LisOrg {tag}", f"lis-org-{tag}")).fetchone()[0]
        user = conn.execute(
            """INSERT INTO users (organisation_id, email, display_name, org_role, cognito_sub, status)
               VALUES (%s,%s,%s,'owner',%s,'active') RETURNING id""",
            (org, f"lis-{tag}@example.com", "Lis", f"sub-lis-{tag}")).fetchone()[0]
        wid = uuid.uuid4()
        short = wid.hex[:12]
        conn.execute(
            """INSERT INTO workspaces (id, organisation_id, name, slug, s3_prefix, pg_schema,
                                       search_prefix, created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (wid, org, f"W {tag}", f"w-{tag}", f"workspaces/w-{tag}/", f"ws_{short}", f"ws-{short}-", user))
        pid = conn.execute(
            "INSERT INTO projects (workspace_id, name, slug, created_by) VALUES (%s,%s,%s,%s) RETURNING id",
            (wid, f"P {tag}", f"p-{tag}", user)).fetchone()[0]
    yield {"tag": tag, "workspace_id": wid, "project_id": pid}
    # Archive what this left behind, so later runs of the job have only their
    # own listeners to find.
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("DELETE FROM listeners WHERE workspace_id = %s", (wid,))


def listener(workspace: dict, name: str) -> uuid.UUID:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        return conn.execute(
            "INSERT INTO listeners (workspace_id, project_id, display_name) VALUES (%s, %s, %s) RETURNING id",
            (workspace["workspace_id"], workspace["project_id"], name)).fetchone()[0]


def send(listener_id: uuid.UUID, body: bytes) -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("SELECT record_listener_event(%s, NULL, 'application/json', %s, %s)",
                     (listener_id, body, json.dumps({"x-trace": "w"})))


def run() -> int:
    return archive_listener_events(build_op_context(resources={"platform_db": PlatformDatabase(dsn=APP_DSN)}))


def archived(listener_id: uuid.UUID) -> tuple:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        return conn.execute(
            """SELECT d.name, d.origin::text, d.current_version, d.s3_location, d.row_count, d.table_schema
                 FROM listeners l JOIN datasets d ON d.id = l.archive_dataset_id WHERE l.id = %s""",
            (listener_id,)).fetchone()


def bodies(location: str) -> list[str]:
    path = gateway_from_env().local_path(location)
    return [r[0] for r in duckdb.connect().execute(
        "SELECT body FROM read_parquet(?) ORDER BY event_id", [path]).fetchall()]


def test_the_job_archives_new_events_and_appends_later_ones(workspace) -> None:
    lid = listener(workspace, f"Hook {workspace['tag']}")
    send(lid, b'{"n": 1}')
    send(lid, b'{"n": 2}')
    assert run() >= 2
    name, origin, version, location, rows, schema = archived(lid)
    assert (name, origin, version, rows) == (f"Hook {workspace['tag']} events", "listener", 1, 2)
    assert [c["name"] for c in schema] == [n for n, _ in listener_archives.COLUMNS]
    assert all(c.get("data_type") for c in schema)
    assert bodies(location) == ['{"n": 1}', '{"n": 2}']
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        made = conn.execute(
            "SELECT produced_by_kind, produced_by_id FROM dataset_versions v JOIN listeners l"
            " ON l.archive_dataset_id = v.dataset_id WHERE l.id = %s", (lid,)).fetchall()
    assert made == [("listener", lid)]

    send(lid, b'{"n": 3}')
    run()
    name, _, version, location, rows, _ = archived(lid)
    assert (version, rows) == (2, 3)
    assert bodies(location) == ['{"n": 1}', '{"n": 2}', '{"n": 3}']
    # Nothing new: no version.
    run()
    assert archived(lid)[2] == 2


def test_one_listener_failing_does_not_stop_the_others(workspace, monkeypatch) -> None:
    good = listener(workspace, f"Good {workspace['tag']}")
    bad = listener(workspace, f"Bad {workspace['tag']}")
    send(good, b"{}")
    send(bad, b"{}")
    real = listener_archives.archive_one

    def flaky(platform_db, storage, listener_id, workspace_id):
        if listener_id == bad:
            raise RuntimeError("storage fell over")
        return real(platform_db, storage, listener_id, workspace_id)
    monkeypatch.setattr(listener_archives, "archive_one", flaky)
    run()
    assert archived(good) is not None and archived(bad) is None


def test_a_name_already_taken_gets_a_number(workspace) -> None:
    name = f"Clash {workspace['tag']}"
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            """INSERT INTO datasets (project_id, workspace_id, name, slug, origin, s3_location)
               VALUES (%s, %s, %s, %s, 'upload', 'x')""",
            (workspace["project_id"], workspace["workspace_id"], f"{name} events",
             f"clash-{workspace['tag']}-events"))
    lid = listener(workspace, name)
    send(lid, b"{}")
    run()
    assert archived(lid)[0] == f"{name} events 2"


def test_a_deleted_dataset_starts_the_archive_over(workspace) -> None:
    lid = listener(workspace, f"Again {workspace['tag']}")
    send(lid, b"1")
    send(lid, b"2")
    run()
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("DELETE FROM datasets d USING listeners l WHERE l.archive_dataset_id = d.id AND l.id = %s",
                     (lid,))
    run()
    _, _, version, location, rows, _ = archived(lid)
    assert (version, rows) == (1, 2) and bodies(location) == ["1", "2"]


def test_a_listener_with_nothing_new_is_left_alone(workspace) -> None:
    """The discovery and the lock are two steps, and "Archive now" can archive
    in between: a run that then finds nothing writes nothing."""
    lid = listener(workspace, f"Idle {workspace['tag']}")
    send(lid, b"1")
    run()
    before = archived(lid)
    db = PlatformDatabase(dsn=APP_DSN)
    assert listener_archives.archive_one(db, gateway_from_env(), lid, workspace["workspace_id"]) == 0
    assert archived(lid) == before
