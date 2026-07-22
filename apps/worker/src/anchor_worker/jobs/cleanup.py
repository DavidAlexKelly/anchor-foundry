"""Workspace schema cleanup (spec §8 isolation; deferred DDL from workspace
deletion — see apps/api/src/services/workspaces.py).

When a workspace row is deleted the API leaves the isolated ws_* schema in
place; this job finds schemas with no owning workspaces row and drops them
through the guarded SECURITY DEFINER function from migration 0010. Both the
listing and the drop re-verify orphanhood server-side, so a workspace created
between list and drop cannot be harmed.
"""

from dagster import OpExecutionContext, job, op

from ..resources import PlatformDatabase


@op
def drop_orphaned_schemas(context: OpExecutionContext, platform_db: PlatformDatabase) -> list[str]:
    dropped: list[str] = []
    with platform_db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT list_orphaned_workspace_schemas()")
            candidates = [row[0] for row in cur.fetchall()]
        context.log.info("orphaned workspace schemas: %s", candidates or "none")
        for schema in candidates:
            with conn.cursor() as cur:
                cur.execute("SELECT drop_orphaned_workspace_schema(%s)", (schema,))
                row = cur.fetchone()
                if row is not None and row[0]:
                    dropped.append(schema)
                    context.log.info("dropped %s", schema)
        conn.commit()
    return dropped


@job
def workspace_cleanup():
    drop_orphaned_schemas()
