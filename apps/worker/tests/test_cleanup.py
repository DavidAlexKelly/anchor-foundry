"""Worker tests. The cleanup job runs against the real local database as
platform_app: create a workspace with a provisioned schema, delete the row
as the owner role (simulating the API's delete), and verify the job drops
exactly the orphaned schema while the guards protect live ones."""
from __future__ import annotations

import os
import sys
import uuid

import psycopg
import pytest
from dagster import build_op_context

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from anchor_worker.definitions import defs  # noqa: E402
from anchor_worker.jobs.cleanup import drop_orphaned_schemas  # noqa: E402
from anchor_worker.resources import PlatformDatabase  # noqa: E402

ADMIN_DSN = os.environ["TEST_ADMIN_DSN"]
APP_DSN = os.environ["WORKER_DATABASE_URL"]


def test_definitions_load() -> None:
    assert defs.get_job_def("workspace_cleanup") is not None
    assert any(s.name == "nightly_workspace_cleanup" for s in defs.schedules)


@pytest.fixture()
def orphan_and_live() -> tuple[str, str]:
    """Create two workspaces with provisioned schemas; delete one row so its
    schema becomes an orphan. Returns (orphan_schema, live_schema)."""
    tag = uuid.uuid4().hex[:8]
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        org = conn.execute(
            "INSERT INTO organisations (name, slug) VALUES (%s,%s) RETURNING id",
            (f"CleanupOrg {tag}", f"cleanup-{tag}"),
        ).fetchone()[0]
        user = conn.execute(
            """INSERT INTO users (organisation_id, email, display_name, org_role,
                                  cognito_sub, status)
               VALUES (%s,%s,%s,'owner',%s,'active') RETURNING id""",
            (org, f"cleanup-{tag}@example.com", "Cleanup", f"sub-cleanup-{tag}"),
        ).fetchone()[0]

        schemas: list[str] = []
        ids: list[uuid.UUID] = []
        for i in range(2):
            wid = uuid.uuid4()
            short = wid.hex[:12]
            conn.execute(
                """INSERT INTO workspaces (id, organisation_id, name, slug, s3_prefix,
                                           pg_schema, search_prefix, created_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (wid, org, f"W{i} {tag}", f"w{i}-{tag}", f"workspaces/w{i}-{tag}/",
                 f"ws_{short}", f"ws-{short}-", user),
            )
            conn.execute("SELECT provision_workspace_schema(%s)", (wid,))
            schemas.append(f"ws_{short}")
            ids.append(wid)

        # Simulate the API's workspace deletion: row gone, schema left behind.
        conn.execute("DELETE FROM workspaces WHERE id = %s", (ids[0],))
    return schemas[0], schemas[1]


def _schema_exists(name: str) -> bool:
    with psycopg.connect(ADMIN_DSN) as conn:
        row = conn.execute(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name = %s", (name,)
        ).fetchone()
    return row is not None


def test_cleanup_drops_orphan_and_keeps_live(orphan_and_live: tuple[str, str]) -> None:
    orphan, live = orphan_and_live
    assert _schema_exists(orphan) and _schema_exists(live)

    ctx = build_op_context(resources={"platform_db": PlatformDatabase(dsn=APP_DSN)})
    dropped = drop_orphaned_schemas(ctx)

    assert orphan in dropped
    assert live not in dropped
    assert not _schema_exists(orphan)
    assert _schema_exists(live)


def test_drop_function_refuses_live_and_foreign_schemas(orphan_and_live: tuple[str, str]) -> None:
    _, live = orphan_and_live
    with psycopg.connect(APP_DSN) as conn:
        with pytest.raises(psycopg.errors.RaiseException, match="live workspace"):
            conn.execute("SELECT drop_orphaned_workspace_schema(%s)", (live,))
        conn.rollback()
        with pytest.raises(psycopg.errors.RaiseException, match="non-workspace"):
            conn.execute("SELECT drop_orphaned_workspace_schema('public')")
        conn.rollback()


def test_cleanup_is_idempotent(orphan_and_live: tuple[str, str]) -> None:
    orphan, _ = orphan_and_live
    ctx = build_op_context(resources={"platform_db": PlatformDatabase(dsn=APP_DSN)})
    first = drop_orphaned_schemas(ctx)
    assert orphan in first
    second = drop_orphaned_schemas(build_op_context(
        resources={"platform_db": PlatformDatabase(dsn=APP_DSN)}
    ))
    assert orphan not in second  # nothing left to drop; no error
