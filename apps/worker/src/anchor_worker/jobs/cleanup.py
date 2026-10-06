"""Workspace cleanup (spec §8 isolation): the deferred half of deleting a
workspace or dataset - see apps/api/src/services/workspaces.py. Its schema,
and since §864 its files.

When a workspace row is deleted the API leaves the isolated ws_* schema in
place; this job finds schemas with no owning workspaces row and drops them
through the guarded SECURITY DEFINER function from migration 0010. Both the
listing and the drop re-verify orphanhood server-side, so a workspace created
between list and drop cannot be harmed.
"""

import re

from dagster import OpExecutionContext, job, op

from .. import instance_index
from ..resources import PlatformDatabase
from ..storage import gateway_from_env

#: What a tombstone may name (§864): a workspace's whole prefix, or one
#: dataset's within it. Anything else is refused before the bucket is touched -
#: `delete_prefix("workspaces/")` would be every customer file in the stack.
TOMBSTONE_PREFIX = re.compile(r"^workspaces/[a-z0-9-]+/(datasets/[0-9a-f-]{36}/)?$")
#: Tombstones handled per night. A workspace's prefix can hold many objects,
#: and the rest wait for tomorrow rather than holding the run open.
TOMBSTONES_PER_RUN = 500
#: A workspace's object index (§876): one per object type since decision 0006,
#: or the single index each workspace had before it. The prefix is
#: `isolation_anchors`' search prefix; any other name on the domain is left.
WORKSPACE_INDEX = re.compile(
    r"^(ws-[0-9a-f]{12}-)(objects-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|object-instances)$"
)


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


@op
def purge_deleted_storage(context: OpExecutionContext, platform_db: PlatformDatabase) -> int:
    """Delete what each tombstone names, then forget it (§864; db 0164).

    A deleted workspace's or dataset's files, which until this stayed in the
    bucket for the life of the stack. One tombstone at a time, forgotten only
    once its prefix is deleted, so a run that fails part-way leaves the rest to
    the next night rather than forgetting what it did not delete.
    """
    storage = gateway_from_env()
    with platform_db.connect() as conn:
        rows = conn.execute(
            "SELECT id, prefix FROM list_storage_tombstones(%s)", (TOMBSTONES_PER_RUN,)
        ).fetchall()
        purged = 0
        for tombstone_id, prefix in rows:
            if not TOMBSTONE_PREFIX.match(prefix or ""):
                context.log.warning("refusing to delete storage prefix %r", prefix)
            else:
                storage.delete_prefix(prefix)
                purged += 1
                context.log.info("deleted %s", prefix)
            conn.execute("SELECT forget_storage_tombstone(%s)", (tombstone_id,))
            conn.commit()
    return purged


@op
def drop_orphaned_indices(context: OpExecutionContext, platform_db: PlatformDatabase) -> list[str]:
    """Delete the object indices of workspaces that no longer exist (§876; db
    0166).

    Deleting a workspace deletes its object types by cascade, which no route
    sees, so their indices stayed on the domain for the life of the stack.
    Nothing to do where objects live in Postgres: there they were in the
    workspace's schema, which `drop_orphaned_schemas` drops.
    """
    index = instance_index.from_env()
    if index is None:
        return []
    dropped: list[str] = []
    try:
        names = [n for n in index.workspace_indices() if WORKSPACE_INDEX.match(n)]
        prefixes = sorted({WORKSPACE_INDEX.match(n).group(1) for n in names})
        if not prefixes:
            return []
        with platform_db.connect() as conn:
            orphaned = {row[0] for row in conn.execute(
                "SELECT orphaned_search_prefixes(%s)", (prefixes,)).fetchall()}
        for name in names:
            if WORKSPACE_INDEX.match(name).group(1) in orphaned:
                index.drop_index(name)
                dropped.append(name)
                context.log.info("deleted index %s", name)
    finally:
        index.close()
    return dropped


@job
def workspace_cleanup():
    drop_orphaned_schemas()
    purge_deleted_storage()
    drop_orphaned_indices()
