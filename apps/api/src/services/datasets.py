"""Datasets service (spec §16 datasets/dataset_versions, §17 "Datasets:
CRUD, upload, preview, query, profile, schema, versions, export").

Storage layout under the workspace isolation anchor:
    {ws.s3_prefix}datasets/{dataset_id}/v{version}/data.parquet
    {ws.s3_prefix}datasets/{dataset_id}/original/{safe_filename}
Uploads are converted to canonical Parquet at ingest; the original bytes are
kept verbatim beside it ("export everything" §11 includes what you gave us).

This slice covers origin='upload'. origin='sync' rows are written by the
connection-sync worker job (next slice); origin='model_output' by the models
layer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text as _text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import ConflictError, NotFoundError
from .dataset_engine import ColumnSchema, DatasetEngineError
from .storage import StorageGateway

_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9_-]{0,61}[a-z0-9])?$")
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # flag: conservative day-one cap


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-_")
    slug = re.sub(r"-{2,}", "-", slug)[:63].strip("-_")
    if not _SLUG_RE.match(slug):
        raise ValueError(f"cannot derive a valid slug from {name!r}")
    return slug


def safe_filename(filename: str) -> str:
    """Original filenames become storage-key segments; strip anything that
    isn't plainly safe and keep the extension."""
    name = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "upload"
    return cleaned[:120]


def storage_prefix(ws_s3_prefix: str, dataset_id: UUID) -> str:
    return f"{ws_s3_prefix}datasets/{dataset_id}/"


_COLUMNS = """
    id, project_id, workspace_id, name, slug, description, origin,
    connection_id, s3_location, table_schema, row_count, current_version,
    schema_policy, forked_from_dataset_id, forked_from_version,
    created_by, created_at, updated_at
"""

# Migration 0023 enforces the schema policy in a BEFORE INSERT trigger on
# dataset_versions - the one place all seven writers across both codebases go
# through - and raises with this SQLSTATE so the refusal can be told apart
# from every other constraint on the table. main.py translates it to a 422.
SCHEMA_POLICY_SQLSTATE = "AF001"


def schema_policy_error(exc: Exception) -> "DatasetEngineError | None":
    """The user-safe error for a schema-policy refusal, or None if this
    database error is something else and must not be swallowed.

    Callers that own a record which must be closed truthfully - a model run,
    a sync run - translate the refusal here so it lands in their existing
    `except DatasetEngineError` and the run is written `failed` with the
    reason. Callers with no such record (upload) leave it alone: main.py's
    handler turns it straight into a 422, which is the whole answer there.
    Mirrored in apps/worker's dataset_engine.py.
    """
    original = getattr(exc, "orig", exc)
    if getattr(original, "sqlstate", None) != SCHEMA_POLICY_SQLSTATE:
        return None
    diag = getattr(original, "diag", None)
    message = getattr(diag, "message_primary", None) or str(original).splitlines()[0]
    hint = getattr(diag, "message_hint", None)
    return DatasetEngineError(message if not hint else f"{message} - {hint}")


async def list_for_project(conn: AsyncConnection, project_id: UUID) -> list[dict[str, Any]]:
    return await fetch_all(
        conn,
        f"SELECT {_COLUMNS} FROM datasets WHERE project_id = :pid ORDER BY name",
        {"pid": str(project_id)},
    )


async def get(conn: AsyncConnection, project_id: UUID, dataset_id: UUID) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        f"SELECT {_COLUMNS} FROM datasets WHERE id = :did AND project_id = :pid",
        {"did": str(dataset_id), "pid": str(project_id)},
    )
    if row is None:
        raise NotFoundError("dataset")
    return row


async def workspace_s3_prefix(conn: AsyncConnection, workspace_id: UUID) -> str:
    row = await fetch_one(
        conn, "SELECT s3_prefix FROM workspaces WHERE id = :wid", {"wid": str(workspace_id)}
    )
    if row is None:
        raise NotFoundError("workspace")
    return str(row["s3_prefix"])


async def create_from_upload(
    conn: AsyncConnection,
    *,
    dataset_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    name: str,
    description: str,
    parquet_key: str,
    schema: list[ColumnSchema],
    row_count: int,
    created_by: UUID,
) -> dict[str, Any]:
    """Insert the dataset row + version 1 after the bytes are already in
    storage (see routes: storage first, row second - an orphaned file is
    recoverable garbage; a row without its file is a broken dataset)."""
    slug = slugify(name)
    existing = await fetch_one(
        conn,
        "SELECT 1 AS x FROM datasets WHERE project_id = :pid AND slug = :slug",
        {"pid": str(project_id), "slug": slug},
    )
    if existing is not None:
        raise ConflictError(f"a dataset with slug '{slug}' already exists in this project")

    import json

    schema_json = json.dumps([c.as_dict() for c in schema])
    row = await fetch_one(
        conn,
        f"""
        INSERT INTO datasets (id, project_id, workspace_id, name, slug, description,
                              origin, s3_location, table_schema, row_count,
                              current_version, created_by)
        VALUES (:id, :pid, :wid, :name, :slug, :descr, 'upload', :loc,
                CAST(:schema AS jsonb), :rows, 1, :by)
        RETURNING {_COLUMNS}
        """,
        {
            "id": str(dataset_id),
            "pid": str(project_id),
            "wid": str(workspace_id),
            "name": name,
            "slug": slug,
            "descr": description,
            "loc": parquet_key,
            "schema": schema_json,
            "rows": row_count,
            "by": str(created_by),
        },
    )
    assert row is not None  # parent-checking policy: RETURNING safe
    await fetch_one(
        conn,
        """
        INSERT INTO dataset_versions (dataset_id, version_number, s3_manifest_key,
                                      table_schema, row_count, produced_by_kind, created_by)
        VALUES (:did, 1, :key, CAST(:schema AS jsonb), :rows, 'upload', :by)
        RETURNING id
        """,
        {
            "did": str(dataset_id),
            "key": parquet_key,
            "schema": schema_json,
            "rows": row_count,
            "by": str(created_by),
        },
    )
    return row


async def fork(
    conn: AsyncConnection,
    storage: StorageGateway,
    *,
    workspace_id: UUID,
    project_id: UUID,
    dataset_id: UUID,
    name: str,
    version_number: int | None,
    created_by: UUID,
) -> dict[str, Any]:
    """Copy one version of a dataset into a new, independent dataset
    (roadmap Datasets item 6, migration 0025).

    Independent means independent: the bytes are copied to the fork's own
    storage prefix rather than shared, so deleting the original cannot empty
    the fork, and the fork starts at version 1 with its own history.

    `version_number` defaults to the source's current version - forking "as
    it is now" is the common case, and naming a specific version is what
    makes this useful for going back to a state that has since been
    overwritten.
    """
    source = await get(conn, project_id, dataset_id)
    target_version = version_number if version_number is not None else int(source["current_version"])
    version = await fetch_one(
        conn,
        """
        SELECT version_number, s3_manifest_key, table_schema, row_count
          FROM dataset_versions
         WHERE dataset_id = :did AND version_number = :v
        """,
        {"did": str(dataset_id), "v": target_version},
    )
    if version is None:
        raise NotFoundError("dataset version")
    if not version["s3_manifest_key"]:
        # **Three states, not two** (§357; `dataset-preview` p.4). A version
        # that was never asked for is a 404; one whose bytes are unaddressable
        # is not missing, it is unreadable, and saying "not found" about a
        # version whose row, schema and count are all right there sends a
        # reader looking for a deletion that did not happen. The read path
        # already draws this distinction (`_parquet_path` in routes/datasets);
        # this one collapsed both into the 404, which is §191's hazard in the
        # direction that matters - the two paths disagreed about the same
        # state, and only one of them was right.
        raise ConflictError(
            f"version {target_version} has no stored file recorded, so there is "
            "nothing to copy. Its schema and row count are still what it reported."
        )

    slug = slugify(name)
    clash = await fetch_one(
        conn,
        "SELECT 1 AS x FROM datasets WHERE project_id = :pid AND slug = :slug",
        {"pid": str(project_id), "slug": slug},
    )
    if clash is not None:
        raise ConflictError(f"a dataset with slug '{slug}' already exists in this project")

    import json

    fork_id = uuid4()
    ws_prefix = await workspace_s3_prefix(conn, workspace_id)
    parquet_key = f"{storage_prefix(ws_prefix, fork_id)}v1/data.parquet"
    schema_json = json.dumps(
        version["table_schema"]
        if not isinstance(version["table_schema"], str)
        else json.loads(version["table_schema"])
    )
    # Storage first, row second - the same ordering create_from_upload uses,
    # and for the same reason: an orphaned file is recoverable garbage, a row
    # without its file is a broken dataset.
    try:
        storage.put(parquet_key, storage.read(str(version["s3_manifest_key"])))
    except FileNotFoundError as exc:
        # The row exists and its bytes do not - storage cleared under a dev
        # machine, a bucket lifecycle rule, a database restored against the
        # wrong bucket. §56 named this failure and turned it into a sentence on
        # the *read* path; forking one endpoint over still raised it, which is
        # a 500 and a traceback on a button somebody pressed deliberately.
        #
        # Nothing has been written yet when this fires: storage comes before
        # the row precisely so that a failure here leaves no dataset behind.
        #
        # p.4 scopes branching to transactions "that have not been deleted by a
        # retention policy". This platform has no retention policy at all
        # (docs/decisions/0005 - nothing deletes an old version today), so there
        # is no policy to name; the same *state* arrives by the routes above,
        # and this is the sentence for it.
        raise ConflictError(
            f"version {target_version}'s underlying file is missing from storage, "
            "so there is nothing to copy. The dataset's metadata and history are "
            "intact; rebuilding or re-uploading it will restore the data."
        ) from exc

    row = await fetch_one(
        conn,
        f"""
        INSERT INTO datasets (id, project_id, workspace_id, name, slug, description,
                              origin, s3_location, table_schema, row_count,
                              current_version, forked_from_dataset_id,
                              forked_from_version, created_by)
        VALUES (:id, :pid, :wid, :name, :slug, :descr, 'fork', :loc,
                CAST(:schema AS jsonb), :rows, 1, :src, :srcv, :by)
        RETURNING {_COLUMNS}
        """,
        {
            "id": str(fork_id), "pid": str(project_id), "wid": str(workspace_id),
            "name": name, "slug": slug,
            "descr": f"Forked from '{source['name']}' at version {target_version}",
            "loc": parquet_key, "schema": schema_json, "rows": version["row_count"],
            "src": str(dataset_id), "srcv": target_version, "by": str(created_by),
        },
    )
    assert row is not None
    await fetch_one(
        conn,
        """
        INSERT INTO dataset_versions (dataset_id, version_number, s3_manifest_key,
                                      table_schema, row_count, produced_by_kind,
                                      produced_by_id, created_by)
        VALUES (:did, 1, :key, CAST(:schema AS jsonb), :rows, 'fork', :src, :by)
        RETURNING id
        """,
        {
            "did": str(fork_id), "key": parquet_key, "schema": schema_json,
            "rows": version["row_count"], "src": str(dataset_id), "by": str(created_by),
        },
    )

    # The quality rules come with it, the cached results do not. Forking is
    # for trying a change and seeing whether it still holds up against the
    # same standard, so arriving with no standard would defeat it - but a
    # result is computed per version, and the fork's version 1 is new.
    await conn.execute(
        _text(
            """
            INSERT INTO dataset_expectations
                   (dataset_id, rule_type, column_name, config, severity, created_by)
            SELECT :fork, rule_type, column_name, config, severity, :by
              FROM dataset_expectations WHERE dataset_id = :src
            """
        ),
        {"fork": str(fork_id), "src": str(dataset_id), "by": str(created_by)},
    )
    return row


async def update(
    conn: AsyncConnection,
    project_id: UUID,
    dataset_id: UUID,
    *,
    name: str | None,
    description: str | None,
    schema_policy: str | None = None,
) -> dict[str, Any]:
    await get(conn, project_id, dataset_id)  # 404 shape before update
    row = await fetch_one(
        conn,
        f"""
        UPDATE datasets
           SET name = COALESCE(:name, name),
               description = COALESCE(:descr, description),
               schema_policy = COALESCE(
                   CAST(:policy AS dataset_schema_policy), schema_policy)
         WHERE id = :did
        RETURNING {_COLUMNS}
        """,
        {"name": name, "descr": description, "policy": schema_policy,
         "did": str(dataset_id)},
    )
    assert row is not None
    return row


async def delete(
    conn: AsyncConnection,
    storage: StorageGateway,
    *,
    workspace_id: UUID,
    project_id: UUID,
    dataset_id: UUID,
) -> None:
    await get(conn, project_id, dataset_id)
    prefix = storage_prefix(await workspace_s3_prefix(conn, workspace_id), dataset_id)
    await fetch_one(
        conn, "DELETE FROM datasets WHERE id = :did RETURNING id", {"did": str(dataset_id)}
    )
    # Storage after the row within the same request; a crash between the two
    # leaves recoverable files, and the worker's cleanup patterns extend to
    # dataset prefixes in a later milestone.
    storage.delete_prefix(prefix)


async def get_cached_profile(
    conn: AsyncConnection, dataset_id: UUID, version_number: int
) -> list[dict[str, Any]] | None:
    """The stored profile for a version, or None when it has not been computed
    yet (migration 0019)."""
    row = await fetch_one(
        conn,
        """
        SELECT column_profile
          FROM dataset_versions
         WHERE dataset_id = :did AND version_number = :version
        """,
        {"did": str(dataset_id), "version": version_number},
    )
    if row is None or row["column_profile"] is None:
        return None
    value = row["column_profile"]
    if isinstance(value, str):
        import json

        try:
            value = json.loads(value)
        except ValueError:
            return None
    return value if isinstance(value, list) else None


async def store_profile(
    conn: AsyncConnection,
    dataset_id: UUID,
    version_number: int,
    profile: list[dict[str, Any]],
) -> None:
    """Cache a computed profile. A version's data is immutable, so this is
    written once and never invalidated - and two concurrent readers racing to
    compute the same profile would write the same bytes, so the last writer
    winning is harmless rather than something to lock against."""
    import json

    await conn.execute(
        _text(
            "UPDATE dataset_versions SET column_profile = CAST(:profile AS jsonb) "
            "WHERE dataset_id = :did AND version_number = :version"
        ),
        {
            "profile": json.dumps(profile),
            "did": str(dataset_id),
            "version": version_number,
        },
    )


async def list_versions(
    conn: AsyncConnection, project_id: UUID, dataset_id: UUID
) -> list[dict[str, Any]]:
    await get(conn, project_id, dataset_id)
    return await fetch_all(
        conn,
        """
        SELECT v.id, v.version_number, v.row_count, v.table_schema,
               v.produced_by_kind, v.s3_manifest_key, v.created_at,
               -- Where a rollback took its data from, resolved to the number
               -- the history shows rather than the row id it stores, so the
               -- reader sees "rolled back to v3" instead of a uuid. Foundry
               -- crosses the skipped transactions out (p.70); saying which
               -- version came back is the same fact without editing the past.
               src.version_number AS rolled_back_to
          FROM dataset_versions v
          LEFT JOIN dataset_versions src
                 ON v.produced_by_kind = 'rollback' AND src.id = v.produced_by_id
         WHERE v.dataset_id = :did
         ORDER BY v.version_number DESC
        """,
        {"did": str(dataset_id)},
    )


async def roll_back(
    conn: AsyncConnection,
    project_id: UUID,
    dataset_id: UUID,
    version_number: int,
    *,
    rolled_back_by: UUID,
) -> dict[str, Any]:
    """Put a dataset's data back to an earlier version (§361; `data-lineage`
    p.73, p.75-76).

    > "The dataset rollback feature allows you to update the data and job
    >  history of a dataset." (p.73)

    **A rollback appends a version; it never rewinds the pointer.** That is
    this repository's convention already — `models.restore_version` (db 0024)
    and `ontology.restore_type_version` (db 0028) both record the restore as a
    *new* version so the history stays a true record — and it is the better of
    the two readings, because a model run stamped with v7 has to keep resolving
    to what v7 was however many times somebody has rolled back since. Foundry
    crosses the rolled-back transactions out instead (p.70, p.76); the version
    this writes says where it came from, which is the same information without
    editing the past.

    **No bytes are copied.** Every version has always been written to its own
    key and nothing is overwritten (`version_location`), so rolling back to v3
    writes a row pointing at v3's file. Two consequences worth naming: it costs
    nothing on a large dataset, and — unlike Foundry's, which warns that "a
    rollback cannot easily be undone" (p.76) — **this one is undoable**, by
    rolling back to the version you were on.

    Provenance goes in `produced_by_kind`/`produced_by_id`, which already mean
    "what produced this version", pointing at the version row it was taken
    from. A second column beside them would be a parallel provenance field that
    is null for every other kind.

    p.74's "you are only able to roll back to a successful transaction" needs
    no check: a `dataset_versions` row exists only for a write that committed
    (`commit_versions`). p.72's "uploaded datasets are not supported" is not
    carried over — Foundry excludes them because there is no logic to rebuild
    from, and here an earlier upload is exactly what somebody who uploaded the
    wrong file wants back.
    """
    dataset = await get(conn, project_id, dataset_id)
    current = int(dataset["current_version"])
    source = await fetch_one(
        conn,
        """
        SELECT id, version_number, s3_manifest_key, table_schema, row_count
          FROM dataset_versions
         WHERE dataset_id = :did AND version_number = :v
        """,
        {"did": str(dataset_id), "v": version_number},
    )
    if source is None:
        raise NotFoundError("dataset version")
    if version_number == current:
        # Not an error worth a traceback and not a silent no-op either: a
        # rollback that quietly wrote a duplicate version would put a row in
        # the history saying something happened when nothing did.
        raise ConflictError(
            f"this dataset is already at v{current}, so there is nothing to roll back to"
        )
    if not source["s3_manifest_key"]:
        # §357's three states, and the same refusal `fork` makes for the same
        # reason: a version whose bytes are unaddressable is not missing, and
        # calling it "not found" sends a reader looking for a deletion that did
        # not happen.
        raise ConflictError(
            f"version {version_number} has no stored file recorded, so there is "
            "nothing to roll back to. Its schema and row count are still what "
            "it reported."
        )

    import json

    schema = source["table_schema"]
    schema_json = schema if isinstance(schema, str) else json.dumps(schema)
    # **The UPDATE takes the number, and it takes the row lock with it.** Two
    # rollbacks landing together would otherwise both read v7 and both insert
    # v8, and the loser would get a unique-violation traceback instead of
    # waiting its turn. `commit_versions` solves the same race by refusing;
    # here there is nothing staged to invalidate, so the second one can simply
    # go next.
    row = await fetch_one(
        conn,
        """
        UPDATE datasets
           SET current_version = current_version + 1,
               s3_location = :loc,
               table_schema = CAST(:schema AS jsonb),
               row_count = :rows
         WHERE id = :did
        RETURNING id, project_id, name, slug, row_count, current_version
        """,
        {
            "loc": source["s3_manifest_key"], "schema": schema_json,
            "rows": source["row_count"], "did": str(dataset_id),
        },
    )
    assert row is not None
    await fetch_one(
        conn,
        """
        INSERT INTO dataset_versions (dataset_id, version_number, s3_manifest_key,
                                      table_schema, row_count, produced_by_kind,
                                      produced_by_id, created_by)
        VALUES (:did, :v, :key, CAST(:schema AS jsonb), :rows, 'rollback', :src, :by)
        RETURNING id
        """,
        {
            "did": str(dataset_id), "v": int(row["current_version"]),
            "key": source["s3_manifest_key"], "schema": schema_json,
            "rows": source["row_count"], "src": str(source["id"]),
            "by": str(rolled_back_by),
        },
    )
    return {**dict(row), "rolled_back_to": version_number}


async def version_location(
    conn: AsyncConnection, project_id: UUID, dataset_id: UUID, version_number: int
) -> dict[str, Any]:
    """Where a particular version's bytes live, plus what it said about itself.

    Time travel (roadmap 3.3) is possible at all because every version has
    always been written to its own key - `datasets/{id}/v{n}/data.parquet` - so
    nothing was overwritten and nothing needs migrating. What was missing is a
    way to *ask* for one.

    The schema and row count come from the version row rather than from the
    dataset, because that is the whole point: reading v3's rows against v7's
    column list would describe the data wrongly in exactly the case somebody is
    looking at an old version to find out what changed.
    """
    await get(conn, project_id, dataset_id)
    row = await fetch_one(
        conn,
        """
        SELECT id, version_number, s3_manifest_key, table_schema, row_count,
               produced_by_kind, produced_by_id, created_at
          FROM dataset_versions
         WHERE dataset_id = :did AND version_number = :n
        """,
        {"did": str(dataset_id), "n": version_number},
    )
    if row is None:
        raise NotFoundError(f"version {version_number} of this dataset")
    return dict(row)


@dataclass(frozen=True)
class StagedVersion:
    """A dataset version whose bytes are written and whose row is not.

    Decision 0008: an action is "a single transaction" (Foundry `action-types`
    p.2), and ours could not be while every write bumped `current_version` on
    its own. The split is what makes one possible - the slow, non-transactional,
    *discardable* half happens first, and the cheap atomic half happens last.

    **A staged version is invisible.** No `datasets` row points at the object
    and no `dataset_versions` row mentions it, so no reader can reach it; if the
    commit never comes, what is left behind is an unreferenced key in the
    bucket. That is the trade this decision makes on purpose - garbage is
    recoverable, and a dataset whose history disagrees with its contents is not.
    """

    dataset_id: UUID
    version: int
    parquet_key: str
    schema_json: str
    row_count: int
    produced_by_kind: str
    produced_by_id: UUID | None
    created_by: UUID


async def stage_version(
    conn: AsyncConnection,
    storage: StorageGateway,
    *,
    dataset_id: UUID,
    workspace_id: UUID,
    parquet_bytes: bytes,
    schema: list[ColumnSchema],
    row_count: int,
    produced_by_kind: str,
    produced_by_id: UUID | None,
    created_by: UUID,
) -> StagedVersion:
    """Write the bytes; touch no metadata."""
    import json

    ws_prefix = await workspace_s3_prefix(conn, workspace_id)
    current = await fetch_one(
        conn, "SELECT current_version FROM datasets WHERE id = :id", {"id": str(dataset_id)}
    )
    if current is None:
        raise NotFoundError("dataset")
    version = int(current["current_version"]) + 1
    parquet_key = f"{storage_prefix(ws_prefix, dataset_id)}v{version}/data.parquet"
    storage.put(parquet_key, parquet_bytes)
    return StagedVersion(
        dataset_id=dataset_id,
        version=version,
        parquet_key=parquet_key,
        schema_json=json.dumps([c.as_dict() for c in schema]),
        row_count=row_count,
        produced_by_kind=produced_by_kind,
        produced_by_id=produced_by_id,
        created_by=created_by,
    )


async def commit_versions(
    conn: AsyncConnection, staged: list[StagedVersion]
) -> dict[str, dict[str, Any]]:
    """Make every staged version current, or none of them.

    Atomic because `user_connection` is one transaction (`lib/db.py`) - the
    UPDATEs and INSERTs below either all commit with it or all roll back, and
    the caller does not have to arrange anything for that to be true. What this
    function adds is that the *set* is written in one place, so an action with
    several writes cannot commit half of them by construction rather than by
    the caller remembering to be careful.

    **Refuses a staged version whose dataset has moved on.** Staging reads
    `current_version` and commit happens later, so another writer can land in
    between - and the INSERT would then collide with the row it created. A
    named refusal beats a unique-violation traceback, and beats far more the
    silent alternative of taking whatever version number is free and writing
    somebody else's bytes into the history under it.
    """
    committed: dict[str, dict[str, Any]] = {}
    for record in staged:
        current = await fetch_one(
            conn,
            "SELECT current_version FROM datasets WHERE id = :id",
            {"id": str(record.dataset_id)},
        )
        if current is None:
            raise NotFoundError("dataset")
        if int(current["current_version"]) + 1 != record.version:
            raise ConflictError(
                f"this dataset was versioned by something else while this write was "
                f"being prepared (expected v{record.version}, found "
                f"v{int(current['current_version']) + 1}). Nothing was applied."
            )
        updated = await fetch_one(
            conn,
            """
            UPDATE datasets
               SET s3_location = :loc, table_schema = CAST(:schema AS jsonb),
                   row_count = :rows, current_version = :version
             WHERE id = :id
            RETURNING id, project_id, name, slug, row_count, current_version
            """,
            {
                "loc": record.parquet_key, "schema": record.schema_json,
                "rows": record.row_count, "version": record.version,
                "id": str(record.dataset_id),
            },
        )
        assert updated is not None
        await conn.execute(
            _text(
                """
                INSERT INTO dataset_versions (dataset_id, version_number, s3_manifest_key,
                                              table_schema, row_count, produced_by_kind,
                                              produced_by_id, created_by)
                VALUES (:did, :version, :key, CAST(:schema AS jsonb), :rows, :kind, :pbid, :by)
                """
            ),
            {
                "did": str(record.dataset_id), "version": record.version,
                "key": record.parquet_key, "schema": record.schema_json,
                "rows": record.row_count, "kind": record.produced_by_kind,
                "pbid": str(record.produced_by_id) if record.produced_by_id else None,
                "by": str(record.created_by),
            },
        )
        committed[str(record.dataset_id)] = dict(updated)
    return committed


async def add_version(
    conn: AsyncConnection,
    storage: StorageGateway,
    *,
    dataset_id: UUID,
    workspace_id: UUID,
    parquet_bytes: bytes,
    schema: list[ColumnSchema],
    row_count: int,
    produced_by_kind: str,
    produced_by_id: UUID | None,
    created_by: UUID,
) -> dict[str, Any]:
    """Append a new version to an already-known dataset in place - the
    simpler single-purpose case where uploads/model-outputs/syncs' own
    create-or-version-by-slug logic doesn't apply because the dataset id is
    already known.

    Stage and commit in one call, for the callers that write exactly one
    dataset and have nothing to be atomic *with*. Kept as its own function
    rather than left for each caller to spell out, so that "one write" stays
    one line and only the callers that need a boundary carry one.
    """
    record = await stage_version(
        conn, storage,
        dataset_id=dataset_id, workspace_id=workspace_id, parquet_bytes=parquet_bytes,
        schema=schema, row_count=row_count, produced_by_kind=produced_by_kind,
        produced_by_id=produced_by_id, created_by=created_by,
    )
    return (await commit_versions(conn, [record]))[str(dataset_id)]
