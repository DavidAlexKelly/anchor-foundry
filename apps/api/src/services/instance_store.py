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
the access check" — there is no RLS at the index layer.

The design used here leans on the isolation anchors the platform already
provisions per workspace (spec §16, db migration 0002: ``s3_prefix``,
``pg_schema``, ``search_prefix`` — immutable, unique, assigned atomically at
workspace creation): each workspace gets its own OpenSearch index, named
from its ``search_prefix``, exactly mirroring how S3 keys are namespaced by
``s3_prefix``. That gives structural isolation (a query against one
workspace's index cannot see another's documents even if a filter were
forgotten) rather than relying solely on an application-level term filter —
though every query still includes an explicit ``object_type_id`` filter,
since one workspace's index holds every object type's instances.

The route layer must resolve ``workspace_id``/``search_prefix`` and do its
permission check (``require_workspace_role`` et al) *before* calling this
gateway, same as it already does for every other service call — this
module trusts its caller completely and enforces no permissions of its
own, only the index-per-workspace + object_type_id scoping described above.

Not wired into routes/objects.py in this build: cutting over means
services/instances.py's Postgres-connection-shaped functions (which take
the request's already-open, RLS-scoped ``AsyncConnection``) get replaced by
calls through this gateway instead — a service-layer change, not a
route-layer one, as already promised. That cutover is left for a follow-up
so the swap can be reviewed on its own; the gateway itself is complete and
production-shaped. Like Boto3SecretsGateway/S3StorageGateway, it is not
unit-tested against a real cluster in this build — no OpenSearch instance
is available in this dev/test environment, and there is no equivalent of
moto for OpenSearch here.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

INSTANCE_PAGE_SIZE = 50
# OpenSearch's default index.max_result_window — from/size pagination past
# this needs search_after instead; flagged rather than silently raised here,
# since the day-one instance browser (services/instances.py) never needs it.
MAX_RESULT_WINDOW = 10_000


class InstanceStoreGateway(Protocol):
    """Mirrors the operations services/instances.py performs against
    Postgres, but workspace-scoped explicitly (via ``search_prefix``) rather
    than implicitly via RLS — see the module docstring for why."""

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


def _index_name(search_prefix: str) -> str:
    # search_prefix already ends in "-" (db 0002: f"{slug}-{short_id}-");
    # index names must be lowercase with no leading "-" or "_" — search_prefix
    # is always lowercase-slug-derived so this is safe without re-validating.
    return f"{search_prefix}object-instances"


def _doc_id(source_id: UUID, primary_key: str) -> str:
    """Deterministic, not random — re-syncing the same source row upserts
    the same document instead of leaking a duplicate, and needs no
    round-trip to look up "does this instance already exist" first."""
    return f"{source_id}:{primary_key}"


class OpenSearchInstanceStore:
    """Production gateway. Auth is HTTP basic against the domain's
    fine-grained-access-control master user (CDK: ``data-stores.ts``'s
    ``fineGrainedAccessControl.masterUserName``); the master password comes
    from Secrets Manager like every other credential in this build, never
    from an env var directly."""

    def __init__(self, endpoint: str, username: str, password: str) -> None:
        from opensearchpy import AsyncOpenSearch  # deferred: not installed in local dev

        self._client = AsyncOpenSearch(
            hosts=[endpoint],
            http_auth=(username, password),
            use_ssl=True,
            verify_certs=True,
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
                f"pagination past {MAX_RESULT_WINDOW:,} rows needs search_after, not offset — "
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
            return None  # exists, but under a different type — not this caller's to see
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

    async def close(self) -> None:
        await self._client.close()


def gateway_from_env() -> InstanceStoreGateway | None:
    """None means "no OpenSearch configured" — callers fall back to the
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
