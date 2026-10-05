"""The object index the scheduled sync writes when a deployment has one (§811).

`apps/api`'s `services/instance_store.py` reads and writes a type's instances
in exactly one place: OpenSearch when `OPENSEARCH_ENDPOINT` and
`OPENSEARCH_SECRET_ARN` are set, Postgres otherwise. This worker wrote Postgres
whatever was configured. In a deployment with the index switched on, a
scheduled sync - the only sync there is past 20,000 rows - would have reported
"ok" into a table nobody reads, and the objects the API served would never
have changed.

So this is the API's `OpenSearchInstanceStore` write path, the three calls a
sync makes - make or widen the index, upsert, sweep - and nothing else, over
the synchronous client because a Dagster op is synchronous. What has to agree
with the API, and is checked against its source by
`tests/test_instance_index_parity.py`:

- **the document id**, `uuid5(INSTANCE_NAMESPACE, "source:key")`: a different
  one would put a second copy of every object beside the API's;
- **the index name and mapping**, from `instance_mapping.py`, which is the
  API's file copied whole rather than reimplemented - the two images share no
  Python (see `storage.py`), and a mapping that differed would refuse the
  other service's documents under `dynamic: "strict"`;
- **the document**, merged rather than replaced (`doc_as_upsert`): the
  dataset's values are layered over what is stored, so an edit-only property
  survives a sync here as it does in Postgres (§805).

Batched, where the API's sync is one request: it is capped at 20,000 rows and
this is not. Only the last batch waits for a refresh, which makes every batch
before it searchable too, and it has to happen before the sweep - a
`delete_by_query` that ran on the pre-sync view would find every row this sync
just rewrote still carrying its old `updated_at`.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any
from uuid import UUID, uuid5

from . import instance_mapping

# The API's `instance_store.INSTANCE_NAMESPACE`. Fixed forever: changing it
# would renumber every instance in every deployment.
INSTANCE_NAMESPACE = UUID("6f6b6a2e-0f1a-4f2b-9c3d-1a2b3c4d5e6f")

#: Documents per bulk request.
BULK_BATCH = 1000


class InstanceIndexError(RuntimeError):
    """The cluster refused part of a sync - a value its mapping will not take -
    or could not be reached. Either way it is this source's sync that failed,
    reported on the source, and not the job: the next source may be fine."""


def doc_id(source_id: UUID | str, primary_key: str) -> str:
    return str(uuid5(INSTANCE_NAMESPACE, f"{source_id}:{primary_key}"))


class InstanceIndex:
    def __init__(self, endpoint: str, username: str, password: str) -> None:
        from opensearchpy import OpenSearch

        # The scheme decides TLS, as the API's store does: a deployed domain is
        # https (data-stores.ts enforces it), and plain http is what lets the
        # tests drive this over a real socket against the fixture server.
        secure = endpoint.startswith("https")
        self._client = OpenSearch(
            hosts=[endpoint], http_auth=(username, password),
            use_ssl=secure, verify_certs=secure,
        )

    def close(self) -> None:
        self._client.close()

    def _ensure_index(self, index: str, declared: list[dict[str, Any]]) -> None:
        """Create the type's index, or add the properties declared since.
        The API's `_ensure_index`, for the same reason: under `dynamic:
        "strict"` a property the index has not heard of is refused."""
        if not self._client.indices.exists(index=index):
            self._client.indices.create(index=index, body=instance_mapping.mapping_for(declared))
            return
        live = self._client.indices.get_mapping(index=index)
        added = instance_mapping.added_fields(live, declared)
        if added:
            self._client.indices.put_mapping(
                index=index, body={"properties": {"properties": {"properties": added}}})

    def upsert(self, **kwargs: Any) -> int:
        return self._guarded(self._upsert, **kwargs)

    def delete_stale(self, **kwargs: Any) -> int:
        return self._guarded(self._delete_stale, **kwargs)

    @staticmethod
    def _guarded(call: Any, **kwargs: Any) -> int:
        from opensearchpy.exceptions import OpenSearchException

        try:
            return call(**kwargs)
        except OpenSearchException as exc:
            raise InstanceIndexError(f"the object index: {exc}") from exc

    def _upsert(
        self, *, search_prefix: str, object_type_id: UUID | str, source_id: UUID | str,
        rows: list[tuple[str, dict[str, Any]]], synced_at: datetime,
        declared: list[dict[str, Any]],
    ) -> int:
        index = instance_mapping.index_name(search_prefix, object_type_id)
        # Made even for no rows. The sweep after this is a `delete_by_query`,
        # which a cluster answers with a 404 for an index that does not exist,
        # and an empty dataset's first sync is exactly that; the API's store
        # skips the index and sweeps with `ignore_unavailable` instead (§810).
        # Either answers it, and a type with an empty index is the plainer.
        self._ensure_index(index, declared)
        stamp = synced_at.isoformat()
        for start in range(0, len(rows), BULK_BATCH):
            body: list[dict[str, Any]] = []
            for primary_key, properties in rows[start:start + BULK_BATCH]:
                body.append({"update": {"_index": index, "_id": doc_id(source_id, primary_key)}})
                body.append({
                    "doc": {
                        "object_type_id": str(object_type_id),
                        "source_id": str(source_id),
                        "primary_key": primary_key,
                        "properties": properties,
                        "updated_at": stamp,
                    },
                    "doc_as_upsert": True,
                })
            last = start + BULK_BATCH >= len(rows)
            resp = self._client.bulk(body=body, refresh="wait_for" if last else "false")
            if resp.get("errors"):
                failed = [item["update"]["error"] for item in resp["items"]
                          if "error" in item.get("update", {})]
                raise InstanceIndexError(
                    f"the index refused {len(failed)} object(s): {failed[:3]}")
        return len(rows)

    def _delete_stale(
        self, *, search_prefix: str, object_type_id: UUID | str, source_id: UUID | str,
        synced_before: datetime,
    ) -> int:
        resp = self._client.delete_by_query(
            index=instance_mapping.index_name(search_prefix, object_type_id),
            body={"query": {"bool": {"filter": [
                {"term": {"source_id": str(source_id)}},
                {"range": {"updated_at": {"lt": synced_before.isoformat()}}},
            ]}}},
            refresh=True,
        )
        return int(resp.get("deleted", 0))


def from_env() -> InstanceIndex | None:
    """None means no index is configured and the sync writes Postgres - the
    same two variables, read the same way, as the API's `gateway_from_env`,
    so the two services can never disagree about where objects live."""
    endpoint = os.environ.get("OPENSEARCH_ENDPOINT")
    secret_arn = os.environ.get("OPENSEARCH_SECRET_ARN")
    if not endpoint or not secret_arn:
        return None
    import boto3

    client = boto3.client("secretsmanager")
    secret = json.loads(client.get_secret_value(SecretId=secret_arn)["SecretString"])
    return InstanceIndex(endpoint, secret["username"], secret["password"])
