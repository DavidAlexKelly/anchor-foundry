"""Scheduled object-type-source sync job tests - real Postgres, real Parquet
files on disk, no external source system needed (unlike sync_configs.py,
this job reads a dataset already materialised in this platform's own
storage). Mirrors test_model_runs.py's fixture shape."""
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

from anchor_worker.jobs.instance_syncs import run_due_object_source_syncs  # noqa: E402
from anchor_worker.resources import PlatformDatabase  # noqa: E402

ADMIN_DSN = os.environ["TEST_ADMIN_DSN"]
APP_DSN = os.environ["WORKER_DATABASE_URL"]


@pytest.fixture()
def storage_root(tmp_path, monkeypatch) -> str:
    root = str(tmp_path / "storage")
    monkeypatch.setenv("LOCAL_STORAGE_ROOT", root)
    monkeypatch.delenv("S3_DATA_BUCKET", raising=False)
    return root


def _write_dataset_parquet(storage_root: str, ws_prefix: str, dataset_id: uuid.UUID, version: int, rows: list[tuple]) -> str:
    key = f"{ws_prefix}datasets/{dataset_id}/v{version}/data.parquet"
    full_path = os.path.join(storage_root, key)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    values = ", ".join(f"({r[0]},'{r[1]}','{r[2]}')" for r in rows)
    duckdb.connect().execute(
        f"COPY (SELECT * FROM (VALUES {values}) t(customer_id, name, email)) TO '{full_path}' (FORMAT parquet)"
    )
    return key


@pytest.fixture()
def workspace(storage_root: str):
    tag = uuid.uuid4().hex[:8]
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        org = conn.execute(
            "INSERT INTO organisations (name, slug) VALUES (%s,%s) RETURNING id",
            (f"InstSyncOrg {tag}", f"inst-sync-org-{tag}"),
        ).fetchone()[0]
        user = conn.execute(
            """INSERT INTO users (organisation_id, email, display_name, org_role, cognito_sub, status)
               VALUES (%s,%s,%s,'owner',%s,'active') RETURNING id""",
            (org, f"inst-{tag}@example.com", "Inst", f"sub-inst-{tag}"),
        ).fetchone()[0]
        wid = uuid.uuid4()
        short = wid.hex[:12]
        ws_prefix = f"workspaces/w-{tag}/"
        conn.execute(
            """INSERT INTO workspaces (id, organisation_id, name, slug, s3_prefix, pg_schema,
                                       search_prefix, created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (wid, org, f"W {tag}", f"w-{tag}", ws_prefix, f"ws_{short}", f"ws-{short}-", user),
        )
        pid = conn.execute(
            "INSERT INTO projects (workspace_id, name, slug, created_by) VALUES (%s,%s,%s,%s) RETURNING id",
            (wid, f"P {tag}", f"p-{tag}", user),
        ).fetchone()[0]

        did = uuid.uuid4()
        key = _write_dataset_parquet(
            storage_root, ws_prefix, did, 1, [(1, "Ada", "ada@example.com"), (2, "Grace", "grace@example.com")]
        )
        conn.execute(
            """INSERT INTO datasets (id, project_id, workspace_id, name, slug, origin, s3_location,
                                     table_schema, row_count, current_version, created_by)
               VALUES (%s,%s,%s,%s,%s,'upload',%s,'[]'::jsonb,2,1,%s)""",
            (did, pid, wid, f"Customers {tag}", f"customers-{tag}", key, user),
        )

        otid = uuid.uuid4()
        conn.execute(
            "INSERT INTO object_types (id, workspace_id, api_name, display_name, created_by) VALUES (%s,%s,%s,%s,%s)",
            (otid, wid, "Customer", "Customer", user),
        )
        conn.execute(
            """INSERT INTO object_type_properties (object_type_id, api_name, display_name, data_type)
               VALUES (%s,'name','Name','string'), (%s,'email','Email','string')""",
            (otid, otid),
        )
        sid = uuid.uuid4()
        conn.execute(
            """INSERT INTO object_type_sources (id, object_type_id, dataset_id, primary_key_column, column_mappings)
               VALUES (%s,%s,%s,'customer_id', %s)""",
            (sid, otid, did, json.dumps({"name": "name", "email": "email"})),
        )
    yield {
        "tag": tag, "workspace_id": wid, "project_id": pid, "user_id": user,
        "ws_prefix": ws_prefix, "dataset_id": did, "object_type_id": otid, "source_id": sid,
    }

    # Same reason as test_sync_configs.py's workspace fixture: the job
    # reschedules a source after every run, so one left scheduled stays
    # permanently due and every later suite run picks it up again - against a
    # tmp storage root that no longer exists.
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "UPDATE object_type_sources SET sync_schedule = NULL, sync_next_run_at = NULL "
            "WHERE id = %s",
            (sid,),
        )


def _set_due(source_id: uuid.UUID, cron: str = "*/15 * * * *") -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "UPDATE object_type_sources SET sync_schedule=%s, sync_next_run_at=NULL WHERE id=%s",
            (cron, source_id),
        )


def _source_row(source_id: uuid.UUID) -> tuple:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        return conn.execute(
            "SELECT sync_status, last_error, sync_next_run_at FROM object_type_sources WHERE id=%s",
            (source_id,),
        ).fetchone()


def _instances(object_type_id: uuid.UUID) -> list[tuple]:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        return conn.execute(
            "SELECT primary_key, properties FROM object_instances WHERE object_type_id=%s ORDER BY primary_key",
            (object_type_id,),
        ).fetchall()


def _ctx():
    return build_op_context(resources={"platform_db": PlatformDatabase(dsn=APP_DSN)})


def test_scheduled_sync_upserts_instances(workspace: dict) -> None:
    _set_due(workspace["source_id"])
    ran = run_due_object_source_syncs(_ctx())
    assert ran >= 1

    status, error, next_run = _source_row(workspace["source_id"])
    assert status == "ok" and error is None and next_run is not None

    rows = _instances(workspace["object_type_id"])
    assert [r[0] for r in rows] == ["1", "2"]
    by_pk = {r[0]: r[1] for r in rows}
    assert by_pk["1"]["name"] == "Ada" and by_pk["1"]["email"] == "ada@example.com"


def test_resync_after_dataset_change_marks_and_sweeps(workspace: dict, storage_root: str) -> None:
    _set_due(workspace["source_id"])
    run_due_object_source_syncs(_ctx())

    # New dataset version: Ada's email changed, Grace dropped, Carol added.
    key = _write_dataset_parquet(
        storage_root, workspace["ws_prefix"], workspace["dataset_id"], 2,
        [(1, "Ada", "ada@newmail.com"), (3, "Carol", "carol@example.com")],
    )
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "UPDATE datasets SET s3_location=%s, current_version=2 WHERE id=%s",
            (key, workspace["dataset_id"]),
        )
    _set_due(workspace["source_id"])
    run_due_object_source_syncs(_ctx())

    rows = _instances(workspace["object_type_id"])
    assert [r[0] for r in rows] == ["1", "3"]  # Grace (pk 2) swept away
    by_pk = {r[0]: r[1] for r in rows}
    assert by_pk["1"]["email"] == "ada@newmail.com"
    assert by_pk["3"]["name"] == "Carol"


def test_failing_sync_isolated_and_reschedules(workspace: dict) -> None:
    # Well-formed key (passes storage key validation) but no file behind it -
    # a genuinely missing Parquet object, not a malformed key.
    missing_key = f"{workspace['ws_prefix']}datasets/{uuid.uuid4()}/v99/data.parquet"
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "UPDATE datasets SET s3_location=%s WHERE id=%s",
            (missing_key, workspace["dataset_id"]),
        )
    _set_due(workspace["source_id"])
    run_due_object_source_syncs(_ctx())

    status, error, next_run = _source_row(workspace["source_id"])
    assert status == "error"
    assert error is not None
    assert next_run is not None  # still rescheduled despite the failure


def test_unscheduled_source_is_not_touched(workspace: dict) -> None:
    ran = run_due_object_source_syncs(_ctx())
    status, error, next_run = _source_row(workspace["source_id"])
    assert status == "never_synced"
    assert next_run is None


def test_a_scheduled_sync_keeps_what_the_dataset_cannot_say(workspace: dict) -> None:
    """`object-link-types` p.113's edit-only property has no column, so a sync
    has nothing to say about it - and this sync used to delete it, writing
    `properties = EXCLUDED.properties` where the API's merges (§805)."""
    _set_due(workspace["source_id"])
    run_due_object_source_syncs(_ctx())
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "UPDATE object_instances SET properties = properties || %s::jsonb "
            "WHERE source_id = %s AND primary_key = '1'",
            (json.dumps({"triage_note": "call the owner"}), workspace["source_id"]),
        )
    _set_due(workspace["source_id"])
    run_due_object_source_syncs(_ctx())
    by_pk = {r[0]: r[1] for r in _instances(workspace["object_type_id"])}
    assert by_pk["1"] == {"name": "Ada", "email": "ada@example.com",
                          "triage_note": "call the owner"}


def test_a_sync_longer_than_a_batch_loses_nothing_at_the_seams(
    workspace: dict, storage_root: str, monkeypatch
) -> None:
    """A statement per batch (§805): seven rows over batches of three, a key
    repeated across a seam and one within a batch - the later row wins, as
    it did when every row was its own statement."""
    from anchor_worker.jobs import instance_syncs

    monkeypatch.setattr(instance_syncs, "UPSERT_BATCH", 3)
    key = _write_dataset_parquet(
        storage_root, workspace["ws_prefix"], workspace["dataset_id"], 2,
        [(1, "a", "a@x"), (2, "b", "b@x"), (3, "c", "c@x"), (3, "c2", "c2@x"),
         (4, "d", "d@x"), (4, "d2", "d2@x"), (5, "e", "e@x")],
    )
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE datasets SET s3_location=%s, current_version=2 WHERE id=%s",
                     (key, workspace["dataset_id"]))
    _set_due(workspace["source_id"])
    run_due_object_source_syncs(_ctx())
    by_pk = {r[0]: r[1]["name"] for r in _instances(workspace["object_type_id"])}
    assert by_pk == {"1": "a", "2": "b", "3": "c2", "4": "d2", "5": "e"}
    assert _source_row(workspace["source_id"])[0] == "ok"


def test_a_scheduled_sync_reads_an_array_property_by_its_element_type(
    workspace: dict, storage_root: str
) -> None:
    """An array is read element by element as its declared element type
    (db 0087), and the job never passed that type along - so every scheduled
    sync of a type with an array property failed with "an array value cannot
    be read without its property's element type", while the API's sync of the
    same source worked (§809)."""
    key = f"{workspace['ws_prefix']}datasets/{workspace['dataset_id']}/v2/data.parquet"
    full = os.path.join(storage_root, key)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    duckdb.connect().execute(
        "COPY (SELECT * FROM (VALUES (1, 'Ada', 'a@x', '[\"7\", 8]'), (2, 'Grace', 'g@x', '[]')) "
        f"t(customer_id, name, email, scores)) TO '{full}' (FORMAT parquet)")
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE datasets SET s3_location=%s, current_version=2 WHERE id=%s",
                     (key, workspace["dataset_id"]))
        conn.execute(
            "INSERT INTO object_type_properties (object_type_id, api_name, display_name, "
            "data_type, array_of) VALUES (%s, 'scores', 'Scores', 'array', 'integer')",
            (workspace["object_type_id"],))
        conn.execute("UPDATE object_type_sources SET column_mappings = %s WHERE id = %s",
                     (json.dumps({"name": "name", "email": "email", "scores": "scores"}),
                      workspace["source_id"]))
    _set_due(workspace["source_id"])
    run_due_object_source_syncs(_ctx())
    assert _source_row(workspace["source_id"])[:2] == ("ok", None)
    by_pk = {r[0]: r[1]["scores"] for r in _instances(workspace["object_type_id"])}
    # Each element coerced as an integer, not passed through as text.
    assert by_pk == {"1": [7, 8], "2": []}


def _analyze_count() -> int:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        return conn.execute("SELECT analyze_count FROM pg_stat_user_tables "
                            "WHERE relname = 'object_instances'").fetchone()[0]


def _counted_after(before: int) -> int:
    import time

    for _ in range(20):
        now = _analyze_count()
        if now != before:
            return now
        time.sleep(0.1)
    return _analyze_count()


@pytest.mark.parametrize("threshold,analyzed", [(2, 1), (3, 0)])
def test_a_large_sync_brings_the_statistics_up_to_date(
    workspace: dict, monkeypatch, threshold: int, analyzed: int
) -> None:
    """The API's rule (§817): a sync of the threshold or more analyzes the
    table, since the planner's stale picture made the next read slow."""
    from anchor_worker.jobs import instance_syncs

    monkeypatch.setattr(instance_syncs, "ANALYZE_AFTER_ROWS", threshold)
    before = _analyze_count()
    _set_due(workspace["source_id"])
    run_due_object_source_syncs(_ctx())
    assert _source_row(workspace["source_id"])[0] == "ok"
    assert _counted_after(before) == before + analyzed


def test_a_pass_that_starts_while_a_source_syncs_leaves_it_alone(
    workspace: dict, monkeypatch
) -> None:
    """§854: the next tick, arriving mid-sync, used to find the source still
    due and sync it again alongside."""
    from anchor_worker.jobs import instance_syncs

    _set_due(workspace["source_id"])
    real = instance_syncs.engine.extract_instance_rows
    calls: list[str] = []

    ours = str(workspace["dataset_id"])

    def extract_with_a_second_pass(path, *args, **kwargs):
        if ours in str(path):
            calls.append(path)
            if len(calls) == 1:
                run_due_object_source_syncs(_ctx())
        return real(path, *args, **kwargs)

    monkeypatch.setattr(instance_syncs.engine, "extract_instance_rows", extract_with_a_second_pass)
    run_due_object_source_syncs(_ctx())
    assert len(calls) == 1, "the second pass synced the source again"
    assert [r[0] for r in _instances(workspace["object_type_id"])] == ["1", "2"]
