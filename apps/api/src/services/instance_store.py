"""Production object instance store: OpenSearch (spec: "object instances are
stored and indexed in OpenSearch"), completing the swap flagged in
services/instances.py's docstring.

Why this isn't a drop-in gateway swap like StorageGateway/SecretsGateway
-------------------------------------------------------------------------
Postgres enforces workspace isolation on ``object_instances`` two ways at
once: RLS policies (keyed off the request's ``app.user_id`` GUC, checked
against ``effective_workspace_role``) as a second, independent layer behind
the route's own permission check. OpenSearch has no equivalent of "run this
query as this authenticated user and let the store's own row policies do
the access check" - there is no RLS at the index layer.

The design used here leans on the isolation anchors the platform already
provisions per workspace (spec §16, db migration 0002: ``s3_prefix``,
``pg_schema``, ``search_prefix`` - immutable, unique, assigned atomically at
workspace creation): each workspace gets its own OpenSearch index, named
from its ``search_prefix``, exactly mirroring how S3 keys are namespaced by
``s3_prefix``. That gives structural isolation (a query against one
workspace's index cannot see another's documents even if a filter were
forgotten) rather than relying solely on an application-level term filter -
though every query still includes an explicit ``object_type_id`` filter,
since one workspace's index holds every object type's instances.

The route layer must resolve ``workspace_id``/``search_prefix`` and do its
permission check (``require_workspace_role`` et al) *before* calling this
gateway, same as it already does for every other service call - this
module trusts its caller completely and enforces no permissions of its
own, only the index-per-workspace + object_type_id scoping described above.

Wired in as of roadmap Objects item 1. ``PostgresInstanceStore`` below
implements the same Protocol over the request's connection, ``store_for()``
picks between them, and ``routes/objects.py``/``routes/actions.py`` go
through that seam - so the Postgres path stays as the fallback and the
local-dev default rather than being deleted the day the new store is
switched on. ``backfill()`` moves an existing workspace across.

Testing, stated precisely: ``tests/test_instance_store.py`` drives this
class over real HTTP through the real ``opensearchpy`` client against
``tests/opensearch_fixture_server.py``, which implements the REST subset
used here. That proves the requests this gateway forms and the responses it
parses are right. It does **not** prove a real cluster agrees - there are no
analyzers, no mapping enforcement and no refresh semantics in a fixture, and
no OpenSearch is available in this environment to check against. Treat the
first deployment against a real domain as the remaining verification step.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID, uuid5

from ..lib.db import fetch_all

if TYPE_CHECKING:  # avoids importing SQLAlchemy for the OpenSearch-only path
    from sqlalchemy.ext.asyncio import AsyncConnection

INSTANCE_PAGE_SIZE = 50
# OpenSearch's default index.max_result_window - from/size pagination past
# this needs search_after instead; flagged rather than silently raised here,
# since the day-one instance browser (services/instances.py) never needs it.
MAX_RESULT_WINDOW = 10_000


class InstanceStoreGateway(Protocol):
    """Mirrors the operations services/instances.py performs against
    Postgres, but workspace-scoped explicitly (via ``search_prefix``) rather
    than implicitly via RLS - see the module docstring for why."""

    async def upsert_instances(
        self,
        *,
        search_prefix: str,
        object_type_id: UUID,
        source_id: UUID,
        rows: list[tuple[str, dict[str, Any]]],
        synced_at: datetime,
    ) -> int: ...

    async def delete_stale_instances(
        self, *, search_prefix: str, source_id: UUID, synced_before: datetime
    ) -> int: ...

    async def list_for_type(
        self, *, search_prefix: str, object_type_id: UUID, limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], int]: ...

    async def get_instance(
        self, *, search_prefix: str, object_type_id: UUID, instance_id: str
    ) -> dict[str, Any] | None: ...

    async def update_properties(
        self, *, search_prefix: str, object_type_id: UUID, instance_id: str, properties: dict[str, Any]
    ) -> None: ...

    async def search(
        self,
        *,
        search_prefix: str,
        workspace_id: UUID,
        query: str | None,
        object_type_ids: list[UUID] | None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]: ...


def _index_name(search_prefix: str) -> str:
    # search_prefix already ends in "-" (db 0002: f"{slug}-{short_id}-");
    # index names must be lowercase with no leading "-" or "_" - search_prefix
    # is always lowercase-slug-derived so this is safe without re-validating.
    return f"{search_prefix}object-instances"


# Namespace for deterministic instance ids. Fixed forever: changing it would
# renumber every instance in every deployment.
INSTANCE_NAMESPACE = UUID("6f6b6a2e-0f1a-4f2b-9c3d-1a2b3c4d5e6f")


def _doc_id(source_id: UUID, primary_key: str) -> str:
    """Deterministic, not random - re-syncing the same source row upserts the
    same document instead of leaking a duplicate, and needs no round-trip to
    ask "does this instance already exist" first.

    A **uuid5**, not the raw "source:key" string, so an instance id has the
    same shape whichever store is behind it: the API's InstanceOut.id is a
    UUID and `action_runs.instance_id` is a uuid column, and a cutover that
    changed the type of a public identifier would be a breaking API change
    dressed up as an infrastructure one.
    """
    return str(uuid5(INSTANCE_NAMESPACE, f"{source_id}:{primary_key}"))


class OpenSearchInstanceStore:
    """Production gateway. Auth is HTTP basic against the domain's
    fine-grained-access-control master user (CDK: ``data-stores.ts``'s
    ``fineGrainedAccessControl.masterUserName``); the master password comes
    from Secrets Manager like every other credential in this build, never
    from an env var directly."""

    def __init__(self, endpoint: str, username: str, password: str) -> None:
        from opensearchpy import AsyncOpenSearch

        # The endpoint's scheme decides TLS rather than a hardcoded True: a
        # deployed domain is always https so production is unchanged, and a
        # plain-http endpoint is what lets the fixture server in
        # tests/opensearch_fixture_server.py exercise this class over a real
        # socket instead of leaving it untested.
        secure = endpoint.startswith("https")
        self._client = AsyncOpenSearch(
            hosts=[endpoint],
            http_auth=(username, password),
            use_ssl=secure,
            verify_certs=secure,
        )

    async def _ensure_index(self, index: str) -> None:
        exists = await self._client.indices.exists(index=index)
        if exists:
            return
        await self._client.indices.create(
            index=index,
            body={
                "mappings": {
                    "properties": {
                        "object_type_id": {"type": "keyword"},
                        "source_id": {"type": "keyword"},
                        "primary_key": {"type": "keyword"},
                        "properties": {"type": "object", "enabled": True},
                        "updated_at": {"type": "date"},
                    }
                }
            },
        )

    async def upsert_instances(
        self,
        *,
        search_prefix: str,
        object_type_id: UUID,
        source_id: UUID,
        rows: list[tuple[str, dict[str, Any]]],
        synced_at: datetime,
    ) -> int:
        if not rows:
            return 0
        index = _index_name(search_prefix)
        await self._ensure_index(index)

        bulk_body: list[dict[str, Any]] = []
        for primary_key, properties in rows:
            doc_id = _doc_id(source_id, primary_key)
            bulk_body.append({"update": {"_index": index, "_id": doc_id}})
            bulk_body.append(
                {
                    "doc": {
                        "object_type_id": str(object_type_id),
                        "source_id": str(source_id),
                        "primary_key": primary_key,
                        "properties": properties,
                        "updated_at": synced_at.isoformat(),
                    },
                    "doc_as_upsert": True,
                }
            )
        resp = await self._client.bulk(body=bulk_body, refresh="wait_for")
        if resp.get("errors"):
            failed = [item["update"]["error"] for item in resp["items"] if "error" in item.get("update", {})]
            raise RuntimeError(f"OpenSearch bulk upsert had {len(failed)} failure(s): {failed[:3]}")
        return len(rows)

    async def delete_stale_instances(
        self, *, search_prefix: str, source_id: UUID, synced_before: datetime
    ) -> int:
        index = _index_name(search_prefix)
        resp = await self._client.delete_by_query(
            index=index,
            body={
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"source_id": str(source_id)}},
                            {"range": {"updated_at": {"lt": synced_before.isoformat()}}},
                        ]
                    }
                }
            },
            refresh=True,
        )
        return int(resp.get("deleted", 0))

    async def list_for_type(
        self, *, search_prefix: str, object_type_id: UUID, limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], int]:
        limit = max(1, min(limit, INSTANCE_PAGE_SIZE))
        offset = max(0, offset)
        if offset + limit > MAX_RESULT_WINDOW:
            raise ValueError(
                f"pagination past {MAX_RESULT_WINDOW:,} rows needs search_after, not offset - "
                "not implemented here (day-one instance browser never reaches it)"
            )
        index = _index_name(search_prefix)
        resp = await self._client.search(
            index=index,
            body={
                "query": {"term": {"object_type_id": str(object_type_id)}},
                "sort": [{"updated_at": "desc"}],
                "from": offset,
                "size": limit,
            },
        )
        hits = resp["hits"]["hits"]
        rows = [
            {
                "id": h["_id"],
                "primary_key": h["_source"]["primary_key"],
                "properties": h["_source"]["properties"],
                "updated_at": h["_source"]["updated_at"],
            }
            for h in hits
        ]
        total = int(resp["hits"]["total"]["value"])
        return rows, total

    async def get_instance(
        self, *, search_prefix: str, object_type_id: UUID, instance_id: str
    ) -> dict[str, Any] | None:
        index = _index_name(search_prefix)
        try:
            resp = await self._client.get(index=index, id=instance_id)
        except Exception:  # opensearchpy.NotFoundError, deferred import
            return None
        source = resp["_source"]
        if str(source.get("object_type_id")) != str(object_type_id):
            return None  # exists, but under a different type - not this caller's to see
        return {
            "id": resp["_id"],
            "source_id": source["source_id"],
            "primary_key": source["primary_key"],
            "properties": source["properties"],
            "updated_at": source["updated_at"],
        }

    async def update_properties(
        self, *, search_prefix: str, object_type_id: UUID, instance_id: str, properties: dict[str, Any]
    ) -> None:
        index = _index_name(search_prefix)
        existing = await self.get_instance(
            search_prefix=search_prefix, object_type_id=object_type_id, instance_id=instance_id
        )
        if existing is None:
            raise LookupError("object instance")
        merged = {**existing["properties"], **properties}
        await self._client.update(
            index=index,
            id=instance_id,
            body={"doc": {"properties": merged, "updated_at": datetime.utcnow().isoformat()}},
            refresh=True,
        )

    async def search(
        self,
        *,
        search_prefix: str,
        workspace_id: UUID,
        query: str | None,
        object_type_ids: list[UUID] | None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """Workspace-wide instance search (roadmap Objects item 2) - the read
        the cutover was for. `workspace_id` is accepted and unused here: the
        index *is* the workspace, so scoping is structural. It exists for the
        Postgres store, which has no index to lean on."""
        limit = max(1, min(limit, INSTANCE_PAGE_SIZE))
        offset = max(0, offset)
        if offset + limit > MAX_RESULT_WINDOW:
            raise ValueError(
                f"pagination past {MAX_RESULT_WINDOW:,} rows needs search_after, not offset - "
                "not implemented here"
            )
        clauses: dict[str, Any] = {}
        if object_type_ids:
            clauses["filter"] = [
                {"terms": {"object_type_id": [str(t) for t in object_type_ids]}}
            ]
        if query:
            # phrase_prefix so a half-typed value still matches, across every
            # property plus the primary key - "search by any property value".
            clauses["must"] = [{
                "multi_match": {
                    "query": query,
                    "fields": ["properties.*", "primary_key"],
                    "type": "phrase_prefix",
                }
            }]
        body: dict[str, Any] = {
            "query": {"bool": clauses} if clauses else {"match_all": {}},
            "sort": [{"updated_at": "desc"}],
            "from": offset,
            "size": limit,
        }
        resp = await self._client.search(index=_index_name(search_prefix), body=body)
        rows = [
            {
                "id": h["_id"],
                "object_type_id": h["_source"]["object_type_id"],
                "primary_key": h["_source"]["primary_key"],
                "properties": h["_source"]["properties"],
                "updated_at": h["_source"]["updated_at"],
            }
            for h in resp["hits"]["hits"]
        ]
        return rows, int(resp["hits"]["total"]["value"])

    async def close(self) -> None:
        await self._client.close()


_configured: "InstanceStoreGateway | None" = None


def configure_instance_store(gateway: "InstanceStoreGateway | None") -> None:
    """Install the process-wide store, or clear it back to Postgres. Called
    from main.py's production wiring and from tests; same shape as
    routes/datasets.py's `configure_storage_gateway`."""
    global _configured
    _configured = gateway


def store_for(conn: "AsyncConnection") -> "InstanceStoreGateway":
    """The one place that decides which store a request talks to.

    Returns the configured gateway when there is one, otherwise a
    `PostgresInstanceStore` over this request's connection. Selection is by
    configuration rather than a per-request flag on purpose: a deployment
    reads its instances out of exactly one place, and "some requests see the
    new store" is a bug surface, not a feature.
    """
    return _configured if _configured is not None else PostgresInstanceStore(conn)


def gateway_from_env() -> InstanceStoreGateway | None:
    """None means "no OpenSearch configured" - callers fall back to the
    Postgres-backed services/instances.py path, matching how
    S3StorageGateway/Boto3SecretsGateway fall back to their dev counterparts
    when their env vars are unset."""
    import os

    endpoint = os.environ.get("OPENSEARCH_ENDPOINT")
    secret_arn = os.environ.get("OPENSEARCH_SECRET_ARN")
    if not endpoint or not secret_arn:
        return None

    import json

    import boto3  # deferred: not installed in local dev

    client = boto3.client("secretsmanager")
    secret = json.loads(client.get_secret_value(SecretId=secret_arn)["SecretString"])
    return OpenSearchInstanceStore(endpoint, secret["username"], secret["password"])


class PostgresInstanceStore:
    """The Postgres-backed store, behind the same Protocol as the OpenSearch
    one (roadmap Objects item 1).

    This is the seam §14 said the cutover needed and deliberately left out:
    with both backends behind one interface, `routes/objects.py` stops caring
    which is configured, and the Postgres path can stay in place as the
    fallback and the local-dev default instead of being deleted on the same
    day the new one is switched on.

    It holds the request's already-open, RLS-scoped connection, which is
    exactly why this could not be a stateless module-level gateway like
    StorageGateway: workspace isolation on `object_instances` comes from RLS
    keyed to that connection's `app.user_id`. `search_prefix` is accepted and
    ignored - Postgres scopes by RLS and object_type_id, and the parameter
    exists for the store that needs it.
    """

    def __init__(self, conn: "AsyncConnection") -> None:  # noqa: F821
        self._conn = conn

    async def upsert_instances(
        self,
        *,
        search_prefix: str,
        object_type_id: UUID,
        source_id: UUID,
        rows: list[tuple[str, dict[str, Any]]],
        synced_at: datetime,
    ) -> int:
        from . import instances as instances_service

        return await instances_service.upsert_instances(
            self._conn,
            object_type_id=object_type_id,
            source_id=source_id,
            rows=rows,
            synced_at=synced_at,
        )

    async def delete_stale_instances(
        self, *, search_prefix: str, source_id: UUID, synced_before: datetime
    ) -> int:
        from . import instances as instances_service

        return await instances_service.delete_stale_instances(
            self._conn, source_id=source_id, synced_before=synced_before
        )

    async def list_for_type(
        self, *, search_prefix: str, object_type_id: UUID, limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], int]:
        from . import instances as instances_service

        return await instances_service.list_for_type(
            self._conn, object_type_id, limit=limit, offset=offset
        )

    async def get_instance(
        self, *, search_prefix: str, object_type_id: UUID, instance_id: str
    ) -> dict[str, Any] | None:
        from ..lib.errors import NotFoundError
        from . import instances as instances_service

        try:
            return await instances_service.get(
                self._conn, object_type_id, UUID(str(instance_id))
            )
        except NotFoundError:
            return None

    async def search(
        self,
        *,
        search_prefix: str,
        workspace_id: UUID,
        query: str | None,
        object_type_ids: list[UUID] | None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        from . import instances as instances_service

        return await instances_service.search(
            self._conn, workspace_id=workspace_id, query=query,
            object_type_ids=object_type_ids, limit=limit, offset=offset,
        )

    async def update_properties(
        self, *, search_prefix: str, object_type_id: UUID, instance_id: str,
        properties: dict[str, Any],
    ) -> None:
        from . import instances as instances_service

        existing = await self.get_instance(
            search_prefix=search_prefix, object_type_id=object_type_id,
            instance_id=instance_id,
        )
        if existing is None:
            raise LookupError("object instance")
        await instances_service.update_properties(
            self._conn, UUID(str(instance_id)), properties
        )


async def backfill(
    conn: "AsyncConnection",
    gateway: "InstanceStoreGateway",
    *,
    workspace_id: UUID,
    search_prefix: str,
) -> dict[str, int]:
    """Copy a workspace's Postgres instances into the configured store, and
    re-point the audit trail at their new ids.

    The cutover procedure this is built for, and why it needs no dual-write
    machinery: **backfill, flip, backfill again**. Every document id is
    derived from (source_id, primary_key), so a second pass rewrites exactly
    the same documents - running it twice is not a duplicate, it is a
    catch-up for anything written between the first pass and the flip. A
    dual-write period would buy the same safety for considerably more moving
    parts, and it is the thing that goes wrong quietly when one of the two
    writes fails.

    `action_runs.instance_id` is rewritten from the old random uuid to the
    deterministic one. Without that the audit trail silently loses which
    instance every historical write-back touched - the FK is ON DELETE SET
    NULL, so it would degrade to null rather than fail loudly, which is the
    worst of both.
    """
    rows = await fetch_all(
        conn,
        """
        SELECT i.id, i.object_type_id, i.source_id, i.primary_key, i.properties,
               i.updated_at
          FROM object_instances i
          JOIN object_types t ON t.id = i.object_type_id
         WHERE t.workspace_id = :wid
         ORDER BY i.object_type_id, i.source_id
        """,
        {"wid": str(workspace_id)},
    )

    import json as _json
    from collections import defaultdict
    from sqlalchemy import text as _sql

    # One bulk call per (object_type, source): the gateway's upsert signature
    # is per-source, and grouping keeps that one round trip per group rather
    # than one per row.
    grouped: dict[tuple[UUID, UUID], list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    newest: dict[tuple[UUID, UUID], datetime] = {}
    remapped = 0
    for row in rows:
        properties = row["properties"]
        if isinstance(properties, str):
            properties = _json.loads(properties)
        key = (UUID(str(row["object_type_id"])), UUID(str(row["source_id"])))
        grouped[key].append((str(row["primary_key"]), properties))
        newest[key] = max(newest.get(key, row["updated_at"]), row["updated_at"])

        new_id = _doc_id(UUID(str(row["source_id"])), str(row["primary_key"]))
        if new_id != str(row["id"]):
            result = await conn.execute(
                _sql("UPDATE action_runs SET instance_id = CAST(:new AS uuid) "
                     "WHERE instance_id = CAST(:old AS uuid)"),
                {"new": new_id, "old": str(row["id"])},
            )
            remapped += result.rowcount or 0

    copied = 0
    for (object_type_id, source_id), group in grouped.items():
        copied += await gateway.upsert_instances(
            search_prefix=search_prefix,
            object_type_id=object_type_id,
            source_id=source_id,
            rows=group,
            synced_at=newest[(object_type_id, source_id)],
        )
    return {"instances": copied, "sources": len(grouped), "action_runs_remapped": remapped}
