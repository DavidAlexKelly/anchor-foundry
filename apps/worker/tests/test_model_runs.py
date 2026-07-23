"""Model run job tests — SQL and Python transforms executed via the real
worker path (RLS-scoped connections, real Postgres, real Parquet files),
plus cron enqueueing. Mirrors test_cleanup.py's fixture shape."""
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

from anchor_worker.jobs.model_runs import run_model_runs  # noqa: E402
from anchor_worker.resources import PlatformDatabase  # noqa: E402

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
    """One org/workspace/project, and a two-row input dataset materialised
    on disk under storage_root at the key its s3_location row points to."""
    tag = uuid.uuid4().hex[:8]
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        org = conn.execute(
            "INSERT INTO organisations (name, slug) VALUES (%s,%s) RETURNING id",
            (f"ModelOrg {tag}", f"model-org-{tag}"),
        ).fetchone()[0]
        user = conn.execute(
            """INSERT INTO users (organisation_id, email, display_name, org_role, cognito_sub, status)
               VALUES (%s,%s,%s,'owner',%s,'active') RETURNING id""",
            (org, f"model-{tag}@example.com", "Model", f"sub-model-{tag}"),
        ).fetchone()[0]
        wid = uuid.uuid4()
        short = wid.hex[:12]
        conn.execute(
            """INSERT INTO workspaces (id, organisation_id, name, slug, s3_prefix, pg_schema,
                                       search_prefix, created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (wid, org, f"W {tag}", f"w-{tag}", f"workspaces/w-{tag}/", f"ws_{short}", f"ws-{short}-", user),
        )
        pid = conn.execute(
            "INSERT INTO projects (workspace_id, name, slug, created_by) VALUES (%s,%s,%s,%s) RETURNING id",
            (wid, f"P {tag}", f"p-{tag}", user),
        ).fetchone()[0]

        did = uuid.uuid4()
        key = f"workspaces/w-{tag}/datasets/{did}/v1/data.parquet"
        full_path = os.path.join(storage_root, key)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        duckdb.connect().execute(
            f"COPY (SELECT * FROM (VALUES (1,10),(2,20)) t(id,val)) TO '{full_path}' (FORMAT parquet)"
        )
        conn.execute(
            """INSERT INTO datasets (id, project_id, workspace_id, name, slug, origin, s3_location,
                                     table_schema, row_count, current_version, created_by)
               VALUES (%s,%s,%s,%s,%s,'upload',%s,'[]'::jsonb,2,1,%s)""",
            (did, pid, wid, f"Input {tag}", f"input-{tag}", key, user),
        )
    return {"tag": tag, "workspace_id": wid, "project_id": pid, "user_id": user, "input_dataset_id": did}


def _create_model(workspace: dict, *, language: str, code: str, trigger_mode: str = "manual",
                   cron_schedule: str | None = None, next_run_at=None) -> uuid.UUID:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        mid = uuid.uuid4()
        conn.execute(
            """INSERT INTO models (id, project_id, name, language, code, trigger_mode,
                                   cron_schedule, next_run_at, created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (mid, workspace["project_id"], f"Model {uuid.uuid4().hex[:6]}", language, code,
             trigger_mode, cron_schedule, next_run_at, workspace["user_id"]),
        )
        conn.execute(
            "INSERT INTO model_inputs (model_id, dataset_id, input_alias) VALUES (%s,%s,'t')",
            (mid, workspace["input_dataset_id"]),
        )
    return mid


def _queue_run(model_id: uuid.UUID) -> uuid.UUID:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        return conn.execute(
            "INSERT INTO model_runs (model_id, trigger_kind) VALUES (%s,'manual') RETURNING id",
            (model_id,),
        ).fetchone()[0]


def _run_row(run_id: uuid.UUID) -> tuple:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        return conn.execute(
            "SELECT status, error_message, rows_produced, output_version FROM model_runs WHERE id=%s",
            (run_id,),
        ).fetchone()


def _ctx():
    return build_op_context(resources={"platform_db": PlatformDatabase(dsn=APP_DSN)})


def test_sql_model_run_succeeds_and_versions_output(workspace: dict) -> None:
    mid = _create_model(workspace, language="sql", code="SELECT id, val * 2 AS doubled FROM t")
    run_id = _queue_run(mid)

    executed = run_model_runs(_ctx())
    assert executed >= 1

    status, error, rows, output_version = _run_row(run_id)
    assert status == "succeeded" and error is None and rows == 2 and output_version is not None

    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        output_dataset_id = conn.execute(
            "SELECT output_dataset_id FROM models WHERE id=%s", (mid,)
        ).fetchone()[0]
        assert output_dataset_id is not None
        version = conn.execute(
            "SELECT current_version FROM datasets WHERE id=%s", (output_dataset_id,)
        ).fetchone()[0]
        assert version == 1

    # Re-run: same output dataset, version bumps to 2.
    run_id_2 = _queue_run(mid)
    run_model_runs(_ctx())
    status2, _, rows2, _ = _run_row(run_id_2)
    assert status2 == "succeeded" and rows2 == 2
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        version = conn.execute(
            "SELECT current_version FROM datasets WHERE id=%s", (output_dataset_id,)
        ).fetchone()[0]
        assert version == 2


def test_python_model_run_succeeds(workspace: dict) -> None:
    mid = _create_model(
        workspace, language="python",
        code="output = t.copy()\noutput['tripled'] = output['val'] * 3",
    )
    run_id = _queue_run(mid)
    executed = run_model_runs(_ctx())
    assert executed >= 1
    status, error, rows, output_version = _run_row(run_id)
    assert status == "succeeded" and error is None and rows == 2 and output_version is not None


def test_failing_sql_run_is_recorded_truthfully(workspace: dict) -> None:
    mid = _create_model(workspace, language="sql", code="SELECT no_such_column FROM t")
    run_id = _queue_run(mid)
    run_model_runs(_ctx())
    status, error, rows, output_version = _run_row(run_id)
    assert status == "failed"
    assert error is not None and "no_such_column" in error
    assert rows is None and output_version is None


def test_cron_model_is_enqueued_and_rescheduled(workspace: dict) -> None:
    import datetime

    past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)
    mid = _create_model(
        workspace, language="sql", code="SELECT * FROM t",
        trigger_mode="cron", cron_schedule="*/10 * * * *", next_run_at=past,
    )
    run_model_runs(_ctx())

    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        runs = conn.execute(
            "SELECT status, trigger_kind FROM model_runs WHERE model_id=%s", (mid,)
        ).fetchall()
        next_run_at = conn.execute(
            "SELECT next_run_at FROM models WHERE id=%s", (mid,)
        ).fetchone()[0]

    assert any(r[1] == "cron" for r in runs)
    assert any(r[0] == "succeeded" for r in runs)
    assert next_run_at is not None and next_run_at > past


def test_manual_trigger_model_is_not_auto_enqueued(workspace: dict) -> None:
    mid = _create_model(workspace, language="sql", code="SELECT * FROM t", trigger_mode="manual")
    run_model_runs(_ctx())
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        count = conn.execute(
            "SELECT count(*) FROM model_runs WHERE model_id=%s", (mid,)
        ).fetchone()[0]
    assert count == 0
