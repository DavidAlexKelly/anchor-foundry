"""Model run job tests - SQL and Python transforms executed via the real
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


def _add_version(dataset_id, version_number: int, *, produced_by=None) -> None:
    """Record a dataset version. The `workspace` fixture creates its input
    dataset without one (nothing read dataset_versions before upstream
    triggers existed), so upstream tests add them explicitly."""
    kind, pid = ("model", produced_by) if produced_by else (None, None)
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            """INSERT INTO dataset_versions (dataset_id, version_number, produced_by_kind,
                                             produced_by_id)
               VALUES (%s,%s,%s,%s)""",
            (dataset_id, version_number, kind, pid),
        )


def _runs(model_id: uuid.UUID) -> list[tuple]:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        return conn.execute(
            "SELECT status, trigger_kind FROM model_runs WHERE model_id=%s ORDER BY queued_at",
            (model_id,),
        ).fetchall()


def _watermark(model_id: uuid.UUID):
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        return conn.execute(
            "SELECT upstream_watermark FROM models WHERE id=%s", (model_id,)
        ).fetchone()[0]


def test_upstream_model_fires_on_a_new_input_version(workspace: dict) -> None:
    mid = _create_model(
        workspace, language="sql", code="SELECT * FROM t", trigger_mode="upstream"
    )
    assert _watermark(mid) is None
    _add_version(workspace["input_dataset_id"], 1)

    run_model_runs(_ctx())

    runs = _runs(mid)
    assert [r[1] for r in runs] == ["upstream"]
    assert runs[0][0] == "succeeded"
    assert _watermark(mid) is not None


def test_upstream_model_does_not_refire_without_a_new_version(workspace: dict) -> None:
    mid = _create_model(
        workspace, language="sql", code="SELECT * FROM t", trigger_mode="upstream"
    )
    _add_version(workspace["input_dataset_id"], 1)
    run_model_runs(_ctx())
    first_watermark = _watermark(mid)
    assert len(_runs(mid)) == 1

    # Nothing new upstream - two further poll passes must be no-ops.
    run_model_runs(_ctx())
    run_model_runs(_ctx())
    assert len(_runs(mid)) == 1
    assert _watermark(mid) == first_watermark

    # A second version lands: exactly one more run, watermark advances.
    _add_version(workspace["input_dataset_id"], 2)
    run_model_runs(_ctx())
    runs = _runs(mid)
    assert len(runs) == 2 and runs[1][1] == "upstream"
    assert _watermark(mid) > first_watermark


def test_upstream_model_ignores_versions_it_produced_itself(workspace: dict) -> None:
    """A model whose output dataset is also one of its inputs is legal, and
    would re-trigger itself forever without 0021's self-loop guard."""
    mid = _create_model(
        workspace, language="sql", code="SELECT * FROM t", trigger_mode="upstream"
    )
    _add_version(workspace["input_dataset_id"], 1, produced_by=mid)

    run_model_runs(_ctx())

    assert _runs(mid) == []
    assert _watermark(mid) is None


def test_upstream_model_is_not_enqueued_while_a_run_is_in_flight(workspace: dict) -> None:
    """Coalescing: versions landing while a run is queued produce one run,
    not a backlog. The run here is left 'running' so the execute step skips
    it, isolating the enqueue decision."""
    mid = _create_model(
        workspace, language="sql", code="SELECT * FROM t", trigger_mode="upstream"
    )
    _add_version(workspace["input_dataset_id"], 1)
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            """INSERT INTO model_runs (model_id, trigger_kind, status, started_at)
               VALUES (%s,'manual','running',now())""",
            (mid,),
        )

    run_model_runs(_ctx())

    assert [r[1] for r in _runs(mid)] == ["manual"]
    assert _watermark(mid) is None  # still due once the in-flight run clears


def test_upstream_chain_runs_the_downstream_model_next_pass(workspace: dict) -> None:
    """The point of the feature: one model's output version is another
    model's input version. Model A reads the uploaded dataset, B reads A's
    output. B fires on the pass *after* A's run commits - the one-pass lag
    run_model_runs documents."""
    a = _create_model(
        workspace, language="sql", code="SELECT id, val * 2 AS doubled FROM t",
        trigger_mode="upstream",
    )
    # Pre-create A's output dataset so B can point at it before A has ever
    # run; A's first run versions it rather than creating it.
    out = uuid.uuid4()
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            """INSERT INTO datasets (id, project_id, workspace_id, name, slug, origin,
                                     s3_location, table_schema, row_count, current_version,
                                     created_by)
               VALUES (%s,%s,%s,%s,%s,'model_output','',
                       '[]'::jsonb,0,0,%s)""",
            (out, workspace["project_id"], workspace["workspace_id"],
             f"A out {workspace['tag']}", f"a-out-{workspace['tag']}", workspace["user_id"]),
        )
        conn.execute("UPDATE models SET output_dataset_id=%s WHERE id=%s", (out, a))
        b = uuid.uuid4()
        conn.execute(
            """INSERT INTO models (id, project_id, name, language, code, trigger_mode, created_by)
               VALUES (%s,%s,%s,'sql','SELECT sum(doubled) AS total FROM t','upstream',%s)""",
            (b, workspace["project_id"], f"B {workspace['tag']}", workspace["user_id"]),
        )
        conn.execute(
            "INSERT INTO model_inputs (model_id, dataset_id, input_alias) VALUES (%s,%s,'t')",
            (b, out),
        )

    _add_version(workspace["input_dataset_id"], 1)

    run_model_runs(_ctx())          # pass 1: A fires; B's input gains a version
    assert [r[1] for r in _runs(a)] == ["upstream"]
    assert _runs(a)[0][0] == "succeeded"
    assert _runs(b) == [], "B's input version only exists after A's run committed"

    run_model_runs(_ctx())          # pass 2: B sees it
    b_runs = _runs(b)
    assert [r[1] for r in b_runs] == ["upstream"]
    assert b_runs[0][0] == "succeeded", b_runs
    assert _runs(a) == [("succeeded", "upstream")], "A must not re-fire on its own output"


def _set_policy(model_id: uuid.UUID, policy: str) -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "UPDATE models SET input_health_policy = %s WHERE id = %s", (policy, model_id)
        )


def _add_not_null_rule(workspace: dict, column: str) -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            """INSERT INTO dataset_expectations (dataset_id, rule_type, column_name, severity)
               VALUES (%s, 'not_null', %s, 'error')""",
            (workspace["input_dataset_id"], column),
        )


@pytest.fixture()
def failing_input(workspace: dict, storage_root: str):
    """Rewrite the fixture's input Parquet with a null in `val`, and assert
    a not-null rule on it, so the dataset's health is genuinely `fail`."""
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        key = conn.execute(
            "SELECT s3_location FROM datasets WHERE id = %s",
            (workspace["input_dataset_id"],),
        ).fetchone()[0]
    path = os.path.join(storage_root, key)
    duckdb.connect().execute(
        f"COPY (SELECT * FROM (VALUES (1,10),(2,NULL)) t(id,val)) TO '{path}' (FORMAT parquet)"
    )
    _add_not_null_rule(workspace, "val")
    return workspace


def test_worker_and_api_agree_on_the_rule_types(workspace: dict) -> None:
    """The evaluator is mirrored into the worker (see its dataset_engine
    docstring). A rule the API can store but the worker cannot evaluate would
    make a gated run silently disagree with the dataset's own health badge."""
    # Read the literal out of the API's source rather than importing it: the
    # two apps have separate virtualenvs by design, and this assertion should
    # fail on real drift, not on the API growing a dependency the worker
    # doesn't install.
    import ast

    api_engine_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "api", "src", "services", "dataset_engine.py",
    )
    with open(api_engine_path) as handle:
        tree = ast.parse(handle.read())
    api_rule_types = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(getattr(t, "id", None) == "RULE_TYPES" for t in node.targets)
    )

    from anchor_worker import dataset_engine as worker_engine

    assert worker_engine.RULE_TYPES == api_rule_types


def test_block_policy_refuses_a_run_on_failing_input(failing_input: dict) -> None:
    mid = _create_model(failing_input, language="sql", code="SELECT * FROM t")
    _set_policy(mid, "block")
    run_id = _queue_run(mid)

    run_model_runs(_ctx())

    status, error, rows, output_version = _run_row(run_id)
    assert status == "failed", (status, error)
    assert "blocked" in error and "val" in error
    assert rows is None and output_version is None

    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        health, started = conn.execute(
            "SELECT input_health, started_at FROM model_runs WHERE id = %s", (run_id,)
        ).fetchone()
    assert health[0]["status"] == "fail"
    assert health[0]["failing"] == ["val: 1 null value(s)"]
    assert started is not None, "a blocked run still records when it was decided"


def test_the_gate_evaluates_health_nothing_has_cached(failing_input: dict) -> None:
    """Migration 0020 said expectations lacked a reader to trigger
    computation on the automated path; this is that reader."""
    def cached():
        with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
            return conn.execute(
                """SELECT v.expectation_results FROM dataset_versions v
                    JOIN datasets d ON d.id = v.dataset_id
                   WHERE d.id = %s AND v.version_number = d.current_version""",
                (failing_input["input_dataset_id"],),
            ).fetchone()

    _add_version(failing_input["input_dataset_id"], 1)
    assert cached()[0] is None

    mid = _create_model(failing_input, language="sql", code="SELECT * FROM t")
    _set_policy(mid, "block")
    _queue_run(mid)
    run_model_runs(_ctx())

    assert cached()[0] is not None, "the gate must compute health, not only read it"


def test_warn_policy_runs_anyway_and_records_what_it_saw(failing_input: dict) -> None:
    mid = _create_model(failing_input, language="sql", code="SELECT * FROM t")
    _set_policy(mid, "warn")
    run_id = _queue_run(mid)

    run_model_runs(_ctx())

    status, error, rows, _ = _run_row(run_id)
    assert status == "succeeded", (status, error)
    assert rows == 2
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        health = conn.execute(
            "SELECT input_health FROM model_runs WHERE id = %s", (run_id,)
        ).fetchone()[0]
    assert health[0]["status"] == "fail", "warn records the same evidence block would"


def test_block_does_not_stop_an_upstream_chain_from_settling(failing_input: dict) -> None:
    """A blocked run must still be a finished run: if it stayed queued the
    coalescing guard in 0021 would wedge the model forever."""
    mid = _create_model(
        failing_input, language="sql", code="SELECT * FROM t", trigger_mode="upstream"
    )
    _set_policy(mid, "block")
    _add_version(failing_input["input_dataset_id"], 1)

    run_model_runs(_ctx())
    first = _runs(mid)
    assert [r[0] for r in first] == ["failed"]

    run_model_runs(_ctx())
    assert _runs(mid) == first, "nothing new upstream, so no retry storm"


def test_ignore_is_the_default_and_costs_nothing(failing_input: dict) -> None:
    mid = _create_model(failing_input, language="sql", code="SELECT * FROM t")
    run_id = _queue_run(mid)
    run_model_runs(_ctx())
    status, error, _, _ = _run_row(run_id)
    assert status == "succeeded", (status, error)
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        health = conn.execute(
            "SELECT input_health FROM model_runs WHERE id = %s", (run_id,)
        ).fetchone()[0]
    assert health is None


def test_a_strict_output_dataset_fails_the_run_rather_than_the_batch(workspace: dict) -> None:
    """Migration 0023 enforces the schema policy in a trigger, so the refusal
    reaches the worker as a psycopg error rather than a check this code made.
    Untranslated it would escape the per-run isolation and take down the whole
    poll pass - the same bug STATUS §16 fixed for StorageKeyError."""
    mid = _create_model(workspace, language="sql", code="SELECT id, val FROM t")
    _queue_run(mid)
    run_model_runs(_ctx())   # creates the output dataset at version 1

    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        out = conn.execute(
            "SELECT output_dataset_id FROM models WHERE id = %s", (mid,)
        ).fetchone()[0]
        conn.execute(
            "UPDATE datasets SET schema_policy = 'strict' WHERE id = %s", (out,)
        )
        conn.execute("UPDATE models SET code = %s WHERE id = %s", ("SELECT id FROM t", mid))

    # A second, unrelated model in the same pass must still run: the refusal
    # is this run's failure, not the batch's.
    other = _create_model(workspace, language="sql", code="SELECT * FROM t")
    bad_run, good_run = _queue_run(mid), _queue_run(other)

    run_model_runs(_ctx())

    status, error, _, _ = _run_row(bad_run)
    assert status == "failed", (status, error)
    assert "columns removed: val" in error and "permissive" in error
    assert _run_row(good_run)[0] == "succeeded"

    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        version = conn.execute(
            "SELECT current_version FROM datasets WHERE id = %s", (out,)
        ).fetchone()[0]
    assert version == 1, "the refused version must not have rolled current_version"


def test_manual_trigger_model_is_not_auto_enqueued(workspace: dict) -> None:
    mid = _create_model(workspace, language="sql", code="SELECT * FROM t", trigger_mode="manual")
    run_model_runs(_ctx())
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        count = conn.execute(
            "SELECT count(*) FROM model_runs WHERE model_id=%s", (mid,)
        ).fetchone()[0]
    assert count == 0
