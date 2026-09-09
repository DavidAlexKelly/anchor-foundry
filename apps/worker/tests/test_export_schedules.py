"""Scheduled exports (decision 0016; `data-connection` p.205; §270).

§265 built the export and the manual button; this is the cron firing, which is
the one piece `data-connection.md`'s row still named as owed.

**The dataset is produced by a real sync and then exported back out**, which is
that document's own acceptance test in its own words — *"an export writes what
a sync of the same dataset would read back"* — and it is the only arrangement
that proves the worker's copy of the export runner reads the same bytes the
API's would. A fixture that hand-wrote a parquet would prove the runner works
against a file this suite invented.

The customer's system is a Postgres database of its own, holding both the table
a sync reads and the table an export writes: the same server standing in for
two ends of the round trip, which is what makes the assertion at the far end
mean something.
"""
from __future__ import annotations

import json
import os
import sys
import uuid

import psycopg
import pytest
from dagster import build_op_context

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))))),
        "packages", "db",
    ),
)

from dsn import for_database  # noqa: E402

import anchor_worker.jobs.export_schedules as export_schedules  # noqa: E402
import anchor_worker.jobs.sync_configs as sync_configs  # noqa: E402
from anchor_worker.jobs.export_schedules import run_due_exports  # noqa: E402
from anchor_worker.jobs.sync_configs import run_due_scheduled_syncs  # noqa: E402
from anchor_worker.resources import PlatformDatabase  # noqa: E402

ADMIN_DSN = os.environ["TEST_ADMIN_DSN"]
APP_DSN = os.environ["WORKER_DATABASE_URL"]

SOURCE_DB = "worker_export_source_test"
SOURCE_USER = "worker_export_source_user"
SOURCE_PASSWORD = "w0rker-Export-77"


@pytest.fixture(scope="module", autouse=True)
def _fake_secrets():
    """No real AWS: both jobs read the same fixed password whatever ARN a
    connection stores. Patched on **both** modules, because each has its own
    `_read_secret` — a patch on one would leave the other reaching for boto3
    and failing in a way that looks like an export bug."""
    import unittest.mock as mock

    with mock.patch.object(
        sync_configs, "_read_secret", lambda arn: {"password": SOURCE_PASSWORD}
    ), mock.patch.object(
        export_schedules, "_read_secret", lambda arn: {"password": SOURCE_PASSWORD}
    ):
        yield


@pytest.fixture(scope="module")
def source_database():
    """The customer's Postgres: `items` for a sync to read, `exported` for an
    export to write. Its own login role, because p.197's truncate permission is
    a real constraint and cannot be exercised as the owner of everything."""
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {SOURCE_DB}")
        conn.execute(f"DROP ROLE IF EXISTS {SOURCE_USER}")
        conn.execute(f"CREATE ROLE {SOURCE_USER} LOGIN PASSWORD '{SOURCE_PASSWORD}'")
        conn.execute(f"GRANT {SOURCE_USER} TO platform")
        conn.execute(f"CREATE DATABASE {SOURCE_DB} OWNER {SOURCE_USER}")
    with psycopg.connect(for_database(ADMIN_DSN, SOURCE_DB), autocommit=True) as conn:
        conn.execute("CREATE TABLE public.items (id bigint PRIMARY KEY, val text NOT NULL)")
        conn.execute("CREATE TABLE public.exported (id bigint, val text)")
        conn.execute(f"GRANT ALL ON ALL TABLES IN SCHEMA public TO {SOURCE_USER}")
    yield {"host": "localhost", "port": 5432, "database": SOURCE_DB, "user": SOURCE_USER}
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {SOURCE_DB}")
        conn.execute(f"DROP ROLE IF EXISTS {SOURCE_USER}")


@pytest.fixture(autouse=True)
def _seed(source_database: dict) -> None:
    with psycopg.connect(for_database(ADMIN_DSN, SOURCE_DB), autocommit=True) as conn:
        conn.execute("TRUNCATE public.items")
        conn.execute("INSERT INTO public.items (id, val) VALUES (1,'a'), (2,'b')")
        conn.execute("TRUNCATE public.exported")


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
        org = conn.execute(
            "INSERT INTO organisations (name, slug) VALUES (%s,%s) RETURNING id",
            (f"ExpOrg {tag}", f"exp-org-{tag}"),
        ).fetchone()[0]
        user = conn.execute(
            """INSERT INTO users (organisation_id, email, display_name, org_role, cognito_sub, status)
               VALUES (%s,%s,%s,'owner',%s,'active') RETURNING id""",
            (org, f"exp-{tag}@example.com", "Exp", f"sub-exp-{tag}"),
        ).fetchone()[0]
        wid = uuid.uuid4()
        short = wid.hex[:12]
        conn.execute(
            """INSERT INTO workspaces (id, organisation_id, name, slug, s3_prefix, pg_schema,
                                       search_prefix, created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (wid, org, f"W {tag}", f"w-{tag}", f"workspaces/w-{tag}/", f"ws_{short}",
             f"ws-{short}-", user),
        )
        pid = conn.execute(
            "INSERT INTO projects (workspace_id, name, slug, created_by) VALUES (%s,%s,%s,%s)"
            " RETURNING id",
            (wid, f"P {tag}", f"p-{tag}", user),
        ).fetchone()[0]
    yield {"tag": tag, "workspace_id": wid, "project_id": pid, "user_id": user}

    # **Un-schedule everything, for `test_sync_configs`' reason.** Both jobs
    # reschedule after every run, so anything left behind with a cron stays
    # permanently due and every later run of this suite picks it up again —
    # against a source that no longer exists. That suite grew from seconds to
    # over ten minutes once a few dozen had accumulated.
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "UPDATE connections SET sync_schedule = NULL, sync_next_run_at = NULL"
            " WHERE workspace_id = %s",
            (wid,),
        )
        conn.execute(
            "UPDATE exports SET schedule = NULL, next_run_at = NULL"
            " WHERE project_id = %s",
            (pid,),
        )


def _ctx():
    return build_op_context(resources={"platform_db": PlatformDatabase(dsn=APP_DSN)})


def _connection(workspace: dict, source_db: dict, *, enabled: bool = True) -> uuid.UUID:
    """A source that a sync reads from and an export writes to.

    One connection for both directions, which is what a customer's own database
    would be — and it means the export's egress policies, credentials and
    switch are the same row the sync used.
    """
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        cid = uuid.uuid4()
        conn.execute(
            """
            INSERT INTO connections (id, workspace_id, project_id, scope, name, source_type,
                                     config, secret_arn, sync_mode, sync_schedule,
                                     sync_source_schema, sync_source_table, sync_dataset_name,
                                     exports_enabled, created_by)
            VALUES (%s,%s,%s,'project',%s,'postgres', %s::jsonb, %s,
                    CAST('full' AS sync_mode), '* * * * *', 'public', 'items', %s, %s, %s)
            """,
            (
                cid, workspace["workspace_id"], workspace["project_id"],
                f"Src {uuid.uuid4().hex[:6]}", json.dumps(source_db), "fake:secret:arn",
                f"items_{workspace['tag']}", enabled, workspace["user_id"],
            ),
        )
    return cid


def _synced_dataset(workspace: dict, connection_id: uuid.UUID) -> uuid.UUID:
    """Run the sync job and hand back the dataset it produced."""
    assert run_due_scheduled_syncs(_ctx()) >= 1
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        row = conn.execute(
            "SELECT sync_dataset_id FROM connections WHERE id = %s", (connection_id,)
        ).fetchone()
        # The sync is what created it, so stop here rather than later inside an
        # export whose failure would be about the wrong thing.
        conn.execute(
            "UPDATE connections SET sync_schedule = NULL WHERE id = %s", (connection_id,)
        )
    assert row is not None and row[0] is not None, "the sync produced no dataset"
    return row[0]


def _export(
    workspace: dict, connection_id: uuid.UUID, dataset_id: uuid.UUID, *,
    mode: str = "mirror", table: str = "exported", schedule: str | None = "* * * * *",
) -> uuid.UUID:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        eid = uuid.uuid4()
        conn.execute(
            """
            INSERT INTO exports (id, project_id, connection_id, dataset_id, name, kind,
                                 mode, destination, schedule, created_by)
            VALUES (%s,%s,%s,%s,%s,'table', CAST(%s AS export_mode), %s::jsonb, %s, %s)
            """,
            (
                eid, workspace["project_id"], connection_id, dataset_id,
                f"Nightly {uuid.uuid4().hex[:6]}", mode,
                json.dumps({"schema": "public", "table": table}),
                schedule, workspace["user_id"],
            ),
        )
    return eid


def _exported_rows() -> list[tuple]:
    with psycopg.connect(for_database(ADMIN_DSN, SOURCE_DB), autocommit=True) as conn:
        return conn.execute("SELECT id, val FROM public.exported ORDER BY id").fetchall()


def _runs(export_id: uuid.UUID) -> list[dict]:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT status, skipped, dataset_version, rows_written, error, run_by"
            " FROM export_runs WHERE export_id = %s ORDER BY started_at",
            (export_id,),
        ).fetchall()
    return [
        {"status": r[0], "skipped": r[1], "version": r[2], "rows": r[3],
         "error": r[4], "run_by": r[5]}
        for r in rows
    ]


def _export_row(export_id: uuid.UUID) -> dict:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        row = conn.execute(
            "SELECT last_version, next_run_at FROM exports WHERE id = %s", (export_id,)
        ).fetchone()
    return {"last_version": row[0], "next_run_at": row[1]}


# ---- the round trip ---------------------------------------------------------
def test_a_due_export_writes_the_synced_rows_to_the_destination(
    workspace: dict, source_database: dict
) -> None:
    """**The claim §270 exists for**, and `data-connection.md`'s acceptance test
    in its own words: an export writes what a sync of the same dataset would
    read back — this time with nobody pressing anything.
    """
    cid = _connection(workspace, source_database)
    dataset = _synced_dataset(workspace, cid)
    eid = _export(workspace, cid, dataset)

    assert run_due_exports(_ctx()) >= 1
    assert _exported_rows() == [(1, "a"), (2, "b")]

    runs = _runs(eid)
    assert len(runs) == 1
    assert runs[0]["status"] == "succeeded" and runs[0]["skipped"] is False
    assert runs[0]["rows"] == 2
    # **Nobody pressed it, and the row says so.** `run_by` is the only column
    # that differs between a scheduled run and a manual one, which is what lets
    # one history be read as one list.
    assert runs[0]["run_by"] is None
    assert _export_row(eid)["last_version"] == 1


def test_a_second_run_with_nothing_new_is_a_success_that_wrote_nothing(
    workspace: dict, source_database: dict
) -> None:
    """p.192: "exports with no new files or rows to be exported will be marked
    as `success`."

    **This is the behaviour a schedule exists to exercise.** A manual run
    twice in a row is somebody being curious; a cron firing every five minutes
    against a dataset that changes daily is this case almost every time, and a
    version of it that rewrote the destination each poll would be the whole
    cost of the feature.
    """
    cid = _connection(workspace, source_database)
    dataset = _synced_dataset(workspace, cid)
    eid = _export(workspace, cid, dataset)

    run_due_exports(_ctx())
    assert _exported_rows() == [(1, "a"), (2, "b")]
    # Something else writes to the destination between the runs. If the second
    # run were a rewrite rather than a skip, this row would be gone.
    with psycopg.connect(for_database(ADMIN_DSN, SOURCE_DB), autocommit=True) as conn:
        conn.execute("INSERT INTO public.exported VALUES (99, 'left by somebody else')")

    # **Made due again on purpose.** The first run advanced `next_run_at` to
    # the cron's next occurrence, which is the schedule working — and it means
    # a second poll finds nothing. Winding the clock back is what lets this
    # test be about p.192's skip rather than about the minute boundary.
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "UPDATE exports SET next_run_at = now() - interval '1 hour' WHERE id = %s",
            (eid,),
        )

    run_due_exports(_ctx())
    runs = _runs(eid)
    assert len(runs) == 2
    assert runs[1]["status"] == "succeeded" and runs[1]["skipped"] is True
    assert runs[1]["rows"] == 0
    assert (99, "left by somebody else") in _exported_rows()


def test_the_schedule_moves_on_after_a_run(workspace: dict, source_database: dict) -> None:
    """`next_run_at` is what stops the poll picking the same export up every
    five minutes forever. NULL means "never fired", which the discovery
    function treats as due — so an export that ran and did not advance would be
    permanently due, which is the failure `test_sync_configs`' fixture cleanup
    exists to undo."""
    cid = _connection(workspace, source_database)
    dataset = _synced_dataset(workspace, cid)
    eid = _export(workspace, cid, dataset)

    assert _export_row(eid)["next_run_at"] is None
    run_due_exports(_ctx())
    assert _export_row(eid)["next_run_at"] is not None


# ---- p.202's switch, at fire time -------------------------------------------
def test_a_schedule_on_a_source_with_exports_turned_off_does_not_run(
    workspace: dict, source_database: dict
) -> None:
    """**Decision 0013 §3's argument, applied to p.202's switch.**

    A schedule set while exports were enabled must stop when an admin turns
    them off. Checking only at create time would make the control apply to
    exports nobody has made yet, which is the mistake two of decision 0013's
    four original outbound paths had already made.
    """
    cid = _connection(workspace, source_database)
    dataset = _synced_dataset(workspace, cid)
    eid = _export(workspace, cid, dataset)

    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE connections SET exports_enabled = false WHERE id = %s", (cid,))

    run_due_exports(_ctx())
    assert _runs(eid) == []
    assert _exported_rows() == []


def test_a_schedule_on_an_enabled_source_does_run(
    workspace: dict, source_database: dict
) -> None:
    """The pair. Without it the test above passes against a job that runs
    nothing at all — which is exactly what a wrong join in `list_due_exports`
    would produce, and it would look like the control working."""
    cid = _connection(workspace, source_database)
    dataset = _synced_dataset(workspace, cid)
    eid = _export(workspace, cid, dataset)

    run_due_exports(_ctx())
    assert len(_runs(eid)) == 1


def test_clearing_the_schedule_stops_it(workspace: dict, source_database: dict) -> None:
    """A NULL schedule is how "manual only" is spelled (db 0070). There is no
    second column able to disagree about it, and this is what makes that
    true rather than intended."""
    cid = _connection(workspace, source_database)
    dataset = _synced_dataset(workspace, cid)
    eid = _export(workspace, cid, dataset, schedule=None)

    run_due_exports(_ctx())
    assert _runs(eid) == []


# ---- one failure must not take the others down ------------------------------
def test_an_export_that_cannot_write_fails_alone(
    workspace: dict, source_database: dict
) -> None:
    """**§263's finding, in the shape that would repeat it.**

    That unit found a refused sync killing the whole op, because
    `EgressRefused` is deliberately not a `ConnectorError` and escaped an
    enumerated `except`. A scheduled export is the same hazard with no caller
    to notice, so this puts a broken export ahead of a working one and asserts
    the second still ran.

    The ordering is pinned rather than hoped for: `list_due_exports` orders by
    `next_run_at NULLS FIRST`, so the broken one is given a timestamp in the
    past and the working one none at all would reverse it — the timestamps
    below put the failure first on purpose.
    """
    cid = _connection(workspace, source_database)
    dataset = _synced_dataset(workspace, cid)
    broken = _export(workspace, cid, dataset, table="no_such_table")
    working = _export(workspace, cid, dataset)

    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "UPDATE exports SET next_run_at = now() - interval '2 hours' WHERE id = %s",
            (broken,),
        )
        conn.execute(
            "UPDATE exports SET next_run_at = now() - interval '1 hour' WHERE id = %s",
            (working,),
        )

    run_due_exports(_ctx())

    failed = _runs(broken)
    assert len(failed) == 1 and failed[0]["status"] == "failed"
    assert "does not exist" in (failed[0]["error"] or "")
    # p.197's refusal names the destination rather than quoting a driver.
    assert "no_such_table" in (failed[0]["error"] or "")

    assert len(_runs(working)) == 1
    assert _runs(working)[0]["status"] == "succeeded"
    assert _exported_rows() == [(1, "a"), (2, "b")]


def test_a_failed_export_leaves_the_mark_where_it_was(
    workspace: dict, source_database: dict
) -> None:
    """A failed run must not advance `last_version`, or the retry would skip
    the work that failed — the worst outcome available, because a broken export
    would then look fixed."""
    cid = _connection(workspace, source_database)
    dataset = _synced_dataset(workspace, cid)
    eid = _export(workspace, cid, dataset, table="no_such_table")

    run_due_exports(_ctx())
    assert _runs(eid)[0]["status"] == "failed"
    assert _export_row(eid)["last_version"] is None


# ---- the allowlist, on the path with no caller ------------------------------
def test_a_refused_destination_is_recorded_and_does_not_stop_the_others(
    workspace: dict, source_database: dict
) -> None:
    """§263: the source's allowlist governs a scheduled export, and the worker
    resolves it itself because there is no request to inherit a scope from.

    Paired the way that unit's tests are: the refusal is asserted beside an
    export that is allowed through, because a refusal alone passes against an
    implementation that refuses everything.
    """
    cid = _connection(workspace, source_database)
    dataset = _synced_dataset(workspace, cid)
    eid = _export(workspace, cid, dataset)

    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO egress_policies (connection_id, host, port, description)"
            " VALUES (%s, 'warehouse.example.com', 5432, 'somewhere else')",
            (cid,),
        )

    run_due_exports(_ctx())
    runs = _runs(eid)
    assert len(runs) == 1 and runs[0]["status"] == "failed"
    assert "not allowed to reach" in (runs[0]["error"] or "")
    assert _exported_rows() == []

    # And with the real host allowed, the same export goes through.
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO egress_policies (connection_id, host, port, description)"
            " VALUES (%s, 'localhost', 5432, 'the customer database')",
            (cid,),
        )
        conn.execute("UPDATE exports SET next_run_at = now() - interval '1 hour' WHERE id = %s", (eid,))

    run_due_exports(_ctx())
    assert _exported_rows() == [(1, "a"), (2, "b")]


# ---- the discovery function itself ------------------------------------------
#
# **Two of its three filters are invisible from the job**, and that is not a
# reason to leave them untested. `_run_one` re-checks the schedule and the
# switch after discovery — deliberately, because both can change between the
# enumeration and the run — so a `list_due_exports()` that returned a disabled
# source anyway would be caught one layer down and every behavioural test would
# still pass. §270's harness proved it: both mutants survived the whole suite.
#
# §268's rule is the one that applies: the cap belongs to the sampler, so the
# test has to be at the sampler. This filter belongs to the function, so these
# call the function. It is a documented interface — SECURITY DEFINER, granted
# to `platform_app` — not an implementation detail being reached into.
def _due_ids() -> set:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        return {r[0] for r in conn.execute("SELECT export_id FROM list_due_exports()").fetchall()}


def test_discovery_leaves_out_a_source_with_exports_turned_off(
    workspace: dict, source_database: dict
) -> None:
    """The join the job's re-check hides. Both are wanted — the join keeps the
    poll from enumerating exports that can never run, the re-check handles the
    switch being thrown between enumeration and execution — and only this can
    see the join."""
    cid = _connection(workspace, source_database)
    dataset = _synced_dataset(workspace, cid)
    eid = _export(workspace, cid, dataset)
    assert eid in _due_ids()

    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE connections SET exports_enabled = false WHERE id = %s", (cid,))
    assert eid not in _due_ids()


def test_discovery_leaves_out_an_export_with_no_schedule(
    workspace: dict, source_database: dict
) -> None:
    """The other filter the re-check hides. Paired with its own presence case,
    because a function returning nothing at all would satisfy the absence half
    on its own."""
    cid = _connection(workspace, source_database)
    dataset = _synced_dataset(workspace, cid)
    scheduled = _export(workspace, cid, dataset)
    manual = _export(workspace, cid, dataset, schedule=None)

    due = _due_ids()
    assert scheduled in due
    assert manual not in due


def test_an_export_that_is_not_due_yet_is_left_alone(
    workspace: dict, source_database: dict
) -> None:
    """**The filter nothing re-checks**, which makes it the one that would
    actually have fired early.

    `_run_one` verifies the schedule and the switch after discovery and does
    *not* verify due-ness, on purpose — the poll is what decides that. So a
    `list_due_exports()` that ignored `next_run_at` would run every scheduled
    export every five minutes, and p.192's skip would hide it: the destination
    would stay correct and the history would fill with skips nobody ordered.
    """
    cid = _connection(workspace, source_database)
    dataset = _synced_dataset(workspace, cid)
    eid = _export(workspace, cid, dataset)

    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "UPDATE exports SET next_run_at = now() + interval '1 day' WHERE id = %s", (eid,)
        )

    assert eid not in _due_ids()
    run_due_exports(_ctx())
    assert _runs(eid) == []
