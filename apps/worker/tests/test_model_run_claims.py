"""Two passes over the same model runs, and each run happens once (§853).

The schedule fires every minute and Dagster launches each tick as its own run,
so a pass still working when the next minute comes overlaps the next pass - and
during a deploy the old and new worker both pass. Each step that acts on a row
used to read it, decide, and write later with nothing held in between, so two
passes could both decide to act. These put the second pass exactly in that gap:
inside the first pass's work, or against a row another pass holds.
"""
from __future__ import annotations

import datetime
import os
import sys
import threading
import uuid

import psycopg

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_model_runs import (  # noqa: E402,F401  (fixtures)
    ADMIN_DSN, _add_version, _create_model, _ctx, _queue_run, storage_root, workspace,
)
from anchor_worker.jobs import model_runs  # noqa: E402


def _runs(model_id: uuid.UUID) -> list[tuple]:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        return conn.execute(
            "SELECT trigger_kind, status FROM model_runs WHERE model_id=%s ORDER BY queued_at",
            (model_id,)).fetchall()


def _outputs(model_id: uuid.UUID) -> int:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        return conn.execute(
            """SELECT count(*) FROM dataset_versions dv
                 JOIN models m ON m.output_dataset_id = dv.dataset_id WHERE m.id=%s""",
            (model_id,)).fetchone()[0]


def _finishes(step, timeout: float = 15.0):
    """Runs a pass in a thread, failing rather than hanging if it waits on a
    lock it should have skipped."""
    out: dict = {}
    thread = threading.Thread(target=lambda: out.setdefault("n", step()), daemon=True)
    thread.start()
    thread.join(timeout)
    assert not thread.is_alive(), "the pass waited on a row another pass holds"
    return out.get("n")


class Holding:
    """Another pass's claim on a row: its lock, held until released."""

    def __init__(self, sql: str, row_id) -> None:
        self.conn = psycopg.connect(ADMIN_DSN)
        assert self.conn.execute(sql + " FOR UPDATE", (row_id,)).fetchone() is not None

    def release(self) -> None:
        self.conn.rollback()
        self.conn.close()


def test_a_run_is_executed_once_when_a_second_pass_starts_mid_claim(
    workspace: dict, monkeypatch
) -> None:
    """The second pass runs entirely between the first pass's read of the run
    and its write of 'running' - the window the input-health gate sits in."""
    mid = _create_model(workspace, language="sql", code="SELECT * FROM t")
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE models SET input_health_policy='warn' WHERE id=%s", (mid,))
    run_id = _queue_run(mid)
    gate = model_runs._check_input_health
    second: list[int] = []

    def gate_with_a_second_pass(cur, storage, model_id):
        # Only for this model's run, and only once: the second pass reaches
        # this gate too, for whatever it does take.
        if str(model_id) == str(mid) and not second:
            second.append(None)
            _finishes(lambda: model_runs._execute_queued_model_runs(_ctx(), model_runs_db()))
        return gate(cur, storage, model_id)

    monkeypatch.setattr(model_runs, "_check_input_health", gate_with_a_second_pass)
    model_runs._execute_queued_model_runs(_ctx(), model_runs_db())

    assert len(second) == 1
    assert _runs(mid) == [("manual", "succeeded")]
    assert _outputs(mid) == 1, "the second pass ran a run the first had claimed"
    del run_id


def test_a_run_another_pass_holds_is_left_to_it(workspace: dict) -> None:
    mid = _create_model(workspace, language="sql", code="SELECT * FROM t")
    run_id = _queue_run(mid)
    held = Holding("SELECT 1 FROM model_runs WHERE id=%s", run_id)
    try:
        _finishes(lambda: model_runs._execute_queued_model_runs(_ctx(), model_runs_db()))
        assert _runs(mid) == [("manual", "queued")]
    finally:
        held.release()
    model_runs._execute_queued_model_runs(_ctx(), model_runs_db())
    assert _runs(mid) == [("manual", "succeeded")]


def test_a_due_cron_model_is_enqueued_once_when_a_second_pass_starts_mid_claim(
    workspace: dict, monkeypatch
) -> None:
    past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)
    # A schedule no other test uses, so the hook knows this model's claim.
    mine = "7-59/53 * * * *"
    mid = _create_model(workspace, language="sql", code="SELECT * FROM t",
                        trigger_mode="cron", cron_schedule=mine, next_run_at=past)
    real = model_runs.croniter
    second: list[None] = []

    def croniter_with_a_second_pass(schedule, *args, **kwargs):
        if schedule == mine and not second:
            second.append(None)
            _finishes(lambda: model_runs._enqueue_due_cron_models(_ctx(), model_runs_db()))
        return real(schedule, *args, **kwargs)

    monkeypatch.setattr(model_runs, "croniter", croniter_with_a_second_pass)
    model_runs._enqueue_due_cron_models(_ctx(), model_runs_db())

    assert len(second) == 1
    assert _runs(mid) == [("cron", "queued")], "both passes enqueued it"


def test_a_cron_model_another_pass_holds_is_left_to_it(workspace: dict) -> None:
    past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)
    mid = _create_model(workspace, language="sql", code="SELECT * FROM t",
                        trigger_mode="cron", cron_schedule="*/10 * * * *", next_run_at=past)
    held = Holding("SELECT 1 FROM models WHERE id=%s", mid)
    try:
        _finishes(lambda: model_runs._enqueue_due_cron_models(_ctx(), model_runs_db()))
    finally:
        held.release()
    assert _runs(mid) == []


def test_an_upstream_model_another_pass_holds_is_left_to_it(workspace: dict) -> None:
    mid = _create_model(workspace, language="sql", code="SELECT * FROM t", trigger_mode="upstream")
    _add_version(workspace["input_dataset_id"], 1)
    held = Holding("SELECT 1 FROM models WHERE id=%s", mid)
    try:
        _finishes(lambda: model_runs._enqueue_due_upstream_models(_ctx(), model_runs_db()))
    finally:
        held.release()
    assert _runs(mid) == []
    # Released, the next pass takes it.
    model_runs._enqueue_due_upstream_models(_ctx(), model_runs_db())
    assert _runs(mid) == [("upstream", "queued")]


def model_runs_db():
    return _ctx().resources.platform_db



def test_a_runs_output_waits_for_another_writer_of_its_dataset(
    workspace: dict, storage_root: str
) -> None:
    """§861: the output's file is named by the version number. Read without a
    lock, another writer of the same dataset - a rollback, an action - could
    take the same number, and whichever wrote second replaced the other's
    committed file. Held, the run's write waits for the other to finish."""
    import threading
    import time

    mid = _create_model(workspace, language="sql", code="SELECT * FROM t")
    _queue_run(mid)
    model_runs._execute_queued_model_runs(_ctx(), model_runs_db())
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        out, prefix = conn.execute(
            "SELECT m.output_dataset_id, w.s3_prefix FROM models m JOIN projects p ON p.id=m.project_id"
            " JOIN workspaces w ON w.id=p.workspace_id WHERE m.id=%s", (mid,)).fetchone()
    second_file = os.path.join(storage_root, f"{prefix}datasets/{out}/v2/data.parquet")
    _queue_run(mid)

    held = psycopg.connect(ADMIN_DSN)
    held.execute("SELECT 1 FROM datasets WHERE id=%s FOR UPDATE", (out,))
    run = threading.Thread(
        target=lambda: model_runs._execute_queued_model_runs(_ctx(), model_runs_db()), daemon=True)
    run.start()
    time.sleep(1.5)
    try:
        assert not os.path.exists(second_file), "the run wrote v2's file under another writer's lock"
    finally:
        held.rollback()
        held.close()
    run.join(30)
    assert not run.is_alive()
    assert os.path.exists(second_file)
    assert _outputs(mid) == 2


def test_runs_a_stopped_worker_left_running_are_failed_and_say_why(workspace: dict) -> None:
    """§870 (db 0165): a run is marked 'running' before its work starts, so a
    worker stopped part-way left it 'running' for good - and an upstream model
    with a run "in flight" was never enqueued again. Past any run's limits, it
    is failed with the reason; a recent one is left alone."""
    import json as _json

    stale = _create_model(workspace, language="sql", code="SELECT * FROM t", trigger_mode="upstream")
    fresh = _create_model(workspace, language="sql", code="SELECT * FROM t")
    _add_version(workspace["input_dataset_id"], 1)
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        old_run = conn.execute(
            "INSERT INTO model_runs (model_id, trigger_kind, status, started_at)"
            " VALUES (%s,'upstream','running', now() - interval '2 hours') RETURNING id",
            (stale,)).fetchone()[0]
        live_run = conn.execute(
            "INSERT INTO model_runs (model_id, trigger_kind, status, started_at)"
            " VALUES (%s,'manual','running', now() - interval '5 minutes') RETURNING id",
            (fresh,)).fetchone()[0]
        repo = conn.execute(
            "INSERT INTO code_repos (project_id, name, slug, s3_prefix, created_by)"
            " VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (workspace["project_id"], f"R {workspace['tag']}", f"r-{workspace['tag']}",
             f"workspaces/w-{workspace['tag']}/repos/r/", workspace["user_id"])).fetchone()[0]
        old_test = conn.execute(
            "INSERT INTO code_test_runs (repo_id, branch, files, requested_by, status, started_at)"
            " VALUES (%s,'main',%s,%s,'running', now() - interval '1 hour') RETURNING id",
            (repo, _json.dumps({}), workspace["user_id"])).fetchone()[0]
        # And an action run the API opened and never closed.
        interface = conn.execute(
            "INSERT INTO interfaces (workspace_id, api_name, display_name) VALUES (%s,%s,'I')"
            " RETURNING id", (workspace["workspace_id"], f"i{workspace['tag']}")).fetchone()[0]
        action = conn.execute(
            "INSERT INTO action_types (workspace_id, interface_id, api_name, display_name)"
            " VALUES (%s,%s,%s,'A') RETURNING id",
            (workspace["workspace_id"], interface, f"a{workspace['tag']}")).fetchone()[0]
        old_action = conn.execute(
            "INSERT INTO action_runs (action_type_id, started_at)"
            " VALUES (%s, now() - interval '1 hour') RETURNING id", (action,)).fetchone()[0]

    model_runs.run_model_runs(_ctx())

    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        def run(run_id):
            return conn.execute("SELECT status, error_message, finished_at IS NOT NULL"
                                " FROM model_runs WHERE id=%s", (run_id,)).fetchone()
        assert run(old_run) == ("failed", "the worker stopped while this ran; run it again", True)
        assert run(live_run)[0] == "running"
        assert conn.execute("SELECT status, error FROM code_test_runs WHERE id=%s",
                            (old_test,)).fetchone() == (
            "errored", "the worker stopped while this ran; run it again")
        assert conn.execute("SELECT status, failure_category, error FROM action_runs WHERE id=%s",
                            (old_action,)).fetchone() == (
            "failed", "unclassified", "the platform stopped while this ran; submit it again")
    # Nothing in flight any more: the upstream model reacted in the same pass.
    assert ("upstream", "succeeded") in _runs(stale)
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE model_runs SET status='failed', error_message='test' WHERE id=%s",
                     (live_run,))
