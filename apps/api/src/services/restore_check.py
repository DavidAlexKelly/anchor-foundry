"""After a restore: does the database agree with storage and the index?
(roadmap phase 3, E.7; §803)

`docs/roadmap-phase-3-fidelity.md` E.7: "Backup and restore has never been
rehearsed. An untested backup is a hope." The stack keeps three stores, and
they are backed up three different ways (`infra/cdk/src/constructs/data-
stores.ts`): Postgres by RDS's automated backups, restored to a point in time;
the data bucket by S3 versioning; and the OpenSearch index not at all, because
it is a projection of the datasets (decision 0008) and is rebuilt by syncing.
A restore is only finished when all three agree again, and this is the check
that says whether they do.

- **Every dataset's current file is in storage**, and every recorded version's
  file too. A version is written to its own key and never over another
  (`v{n}/data.parquet`, `datasets.stage_version`), so a database restored to
  an earlier point names files the versioned bucket still holds - unless one
  was deleted since, which is what this finds, and what restoring that key's
  previous S3 version repairs.
- **Every object type's index holds as many objects as its datasets name.**
  The database may now be older or newer than the index; a type whose count
  differs is named with the sources whose re-sync rebuilds it. "Name" is
  distinct non-null primary keys across the type's current files, because
  that is what a sync makes objects of: a null key is skipped and a repeated
  one is one object (`instances.extract_rows`, the upsert) - so a dataset's
  `row_count` would call a type with one duplicate key broken for ever. A
  type no sync and no write ever built - an empty index whose sources have
  never synced - is skipped as never built. A type whose file is
  missing is `index_unchecked` rather than stale: until the file is back
  there is neither an expected count nor a re-sync to run.

What it does not check, stated: attachment files, which are property values
inside a dataset's rows rather than rows of any table; and a dataset's
*contents* - that the right bytes are at a key is the bucket's versioning,
not something a count can tell.

Run as `python -m src.services.restore_check` with the platform's
`DATABASE_URL` (the owner role, so it sees every workspace) and the same
storage and index settings as the API. It prints a JSON report and exits 1
when anything needs repairing.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all
from . import instance_store


async def check(
    conn: AsyncConnection, storage: Any, *, workspace_id: UUID | None = None,
) -> dict[str, Any]:
    """What a restore left disagreeing, by store. Empty lists mean it agrees.

    Every workspace, or one: a restore is of the whole database, but repairing
    one customer workspace at a time is how it is usually worked through."""
    scope = {"wid": str(workspace_id) if workspace_id else None}
    missing_current = [
        {"dataset_id": str(row["id"]), "name": row["name"], "key": row["s3_location"]}
        for row in await fetch_all(conn, """
            SELECT id, name, s3_location FROM datasets
             WHERE CAST(:wid AS uuid) IS NULL OR workspace_id = CAST(:wid AS uuid)
             ORDER BY name, id
        """, scope)
        if not _held(storage, str(row["s3_location"]))
    ]
    missing_versions = [
        {"dataset_id": str(row["dataset_id"]), "version": int(row["version_number"]),
         "key": row["s3_manifest_key"]}
        for row in await fetch_all(conn, """
            SELECT v.dataset_id, v.version_number, v.s3_manifest_key
              FROM dataset_versions v JOIN datasets d ON d.id = v.dataset_id
             WHERE v.s3_manifest_key IS NOT NULL
               AND (CAST(:wid AS uuid) IS NULL OR d.workspace_id = CAST(:wid AS uuid))
             ORDER BY v.dataset_id, v.version_number
        """, scope)
        if not _held(storage, str(row["s3_manifest_key"]))
    ]

    # Each object type's sources, and the files and key columns they read.
    missing = {item["key"] for item in missing_current}
    types: dict[str, dict[str, Any]] = {}
    for row in await fetch_all(conn, """
        SELECT s.id AS source_id, s.object_type_id, s.primary_key_column, ot.api_name,
               w.search_prefix, d.s3_location, s.last_synced_at
          FROM object_type_sources s
          JOIN object_types ot ON ot.id = s.object_type_id
          JOIN workspaces w ON w.id = ot.workspace_id
          JOIN datasets d ON d.id = s.dataset_id
         WHERE CAST(:wid AS uuid) IS NULL OR ot.workspace_id = CAST(:wid AS uuid)
         ORDER BY ot.api_name, s.id
    """, scope):
        entry = types.setdefault(str(row["object_type_id"]), {
            "object_type_id": str(row["object_type_id"]), "api_name": row["api_name"],
            "search_prefix": str(row["search_prefix"]), "files": [], "sources": [],
        })
        entry["sources"].append(str(row["source_id"]))
        entry["synced"] = entry.get("synced", False) or row["last_synced_at"] is not None
        if row["s3_location"] in missing:
            entry["unreadable"] = True
        else:
            entry["files"].append((storage.local_path(str(row["s3_location"])),
                                   str(row["primary_key_column"])))

    store = instance_store.store_for(conn)
    stale_index, index_unchecked = [], []
    for entry in types.values():
        if entry.get("unreadable"):
            # Its file is gone, so neither the expected count nor a re-sync
            # exists until the file is put back: the file is the repair, and
            # the index is checked on the next run.
            index_unchecked.append({"object_type_id": entry["object_type_id"],
                                    "api_name": entry["api_name"]})
            continue
        _newest, indexed = await store.freshness(
            search_prefix=entry["search_prefix"], object_type_id=UUID(entry["object_type_id"]))
        if indexed == 0 and not entry["synced"]:
            # Nothing has ever built this index - no sync, and nothing written
            # to it directly - so an empty one is what it should be, not what
            # a restore did. (An action log is the other case: its source is
            # never synced, its entries are written straight to the index,
            # and it is compared like any other.)
            continue
        expected = distinct_keys(entry["files"])
        if indexed != expected:
            stale_index.append({
                "object_type_id": entry["object_type_id"], "api_name": entry["api_name"],
                "keys_in_datasets": expected, "indexed": indexed,
                "resync_sources": entry["sources"],
            })

    return {
        "missing_current_files": missing_current,
        "missing_version_files": missing_versions,
        "stale_index": stale_index,
        "index_unchecked": index_unchecked,
        # `index_unchecked` is only ever beside a missing file, so it does
        # not need its own term here.
        "ok": not (missing_current or missing_versions or stale_index),
    }


def _held(storage: Any, key: str) -> bool:
    """Whether storage holds this key. A key storage refuses to read - one a
    restore brought back from before a rule about keys - is reported as
    missing rather than ending the check: a report that stops at the first
    odd row is no report."""
    from .storage import StorageKeyError

    try:
        return storage.size(key) is not None
    except StorageKeyError:
        return False


def distinct_keys(files: list[tuple[str, str]]) -> int:
    """Distinct non-null primary keys across these parquet files, each read by
    its own key column - the objects a sync of them makes."""
    if not files:
        return 0
    import duckdb

    def quoted(text: str) -> str:
        return text.replace("'", "''")

    union = " UNION ALL ".join(
        f'SELECT CAST("{column.replace(chr(34), chr(34) * 2)}" AS VARCHAR) AS k '
        f"FROM read_parquet('{quoted(path)}')"
        for path, column in files)
    con = duckdb.connect()
    try:
        return int(con.execute(
            # `count(DISTINCT ...)` leaves NULL out by itself.
            f"SELECT count(DISTINCT k) FROM ({union})").fetchone()[0])
    finally:
        con.close()


def _storage_from_env() -> Any:
    """The API's own choice of gateway: S3 in a deployed stack, else local."""
    import os

    from .storage import LocalStorageGateway, S3StorageGateway

    bucket = os.environ.get("S3_DATA_BUCKET")
    if bucket:
        return S3StorageGateway(bucket, os.environ.get("AWS_REGION", ""))
    return LocalStorageGateway(os.environ.get("STORAGE_ROOT", "/tmp/anchor-storage"))


async def _main(argv: list[str]) -> int:
    import argparse

    # An operator's run over a whole deployment, not a request: no
    # statement limit unless one is asked for (§833).
    os.environ.setdefault("STATEMENT_TIMEOUT_MS", "0")

    from ..lib.db import get_engine

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workspace", type=UUID, default=None,
                        help="check one workspace rather than all of them")
    args = parser.parse_args(argv)
    instance_store.configure_instance_store(instance_store.gateway_from_env())
    async with get_engine().connect() as conn:
        report = await check(conn, _storage_from_env(), workspace_id=args.workspace)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(sys.argv[1:])))
