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

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID, uuid5

from ..lib.db import fetch_all
# Stdlib-only, so importing it does not undo this module's care about staying
# usable on the OpenSearch-only path.
from . import instance_mapping, object_sets

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
        # The object type's declared properties (`ontology.list_properties`),
        # so the index can be created and widened with the mapping they ask
        # for (decision 0006 §1). Optional because the Postgres store has no
        # mapping to keep, and because a caller with nothing to declare - the
        # backfill, replaying rows that are already coerced - should not have
        # to invent one.
        declared: list[dict[str, Any]] | None = None,
    ) -> int: ...

    async def delete_stale_instances(
        self, *, search_prefix: str, object_type_id: UUID, source_id: UUID,
        synced_before: datetime,
    ) -> int: ...

    async def delete_instances(
        self, *, search_prefix: str, object_type_id: UUID, source_id: UUID,
        primary_keys: list[str],
    ) -> int: ...

    async def adopt_legacy_index(
        self, *, search_prefix: str, object_type_id: UUID,
        declared: list[dict[str, Any]] | None = None,
    ) -> int:
        """Copy one type's documents out of the pre-0006 workspace index.

        Returns how many were moved. See `split_workspace_index` for why the
        old index is the source and why running it twice is safe.
        """
        ...

    async def drop_type(self, *, search_prefix: str, object_type_id: UUID) -> None:
        """Forget every instance of an object type that no longer exists.

        **Nothing did this before**, and on the OpenSearch path that was a real
        leak rather than a tidiness problem: deleting an object type dropped
        its Postgres rows by cascade and left its documents in the index, where
        the workspace explorer - which filters by type only when asked - went
        on returning them. Objects of a type nobody could name.

        It is one line now because there is an index to delete (decision 0006
        §1), which is the same argument the decision makes: "deleting an object
        type deletes an index, which is cleaner than the delete-by-query it
        does today."
        """
        ...

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

    async def find_by_property(
        self,
        *,
        search_prefix: str,
        object_type_id: UUID,
        property_name: str | None,
        value: Any,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]: ...

    async def evaluate_object_set(
        self,
        *,
        search_prefix: str,
        object_type_id: UUID,
        filters: "tuple[Any, ...]",
        limit: int,
        offset: int,
        # An `object_sets.Sort`. A bare string is still accepted and means one
        # of the four fixed sorts, so a caller that has not been updated keeps
        # working - a property sort is the only thing that needs the value
        # object, because it is the only sort that carries a declared type.
        sort: "Any" = object_sets.DEFAULT_SORT,
    ) -> tuple[list[dict[str, Any]], int]:
        """One page of a filtered set, and how many are in it (roadmap 1.2).

        The total is the whole set, not the page - "127 sites match" is the
        answer a Workshop app needs and the one a page of rows cannot give.
        """
        ...

    async def aggregate_object_set(
        self,
        *,
        search_prefix: str,
        object_type_id: UUID,
        filters: "tuple[Any, ...]",
        aggregation: "Any",
        property_name: str | None = None,
    ) -> "float | int | None":
        """One number over a whole set (roadmap 1.5 - what a Metric Card shows).

        p.310's six: the two text-identity ones, which need no declared type,
        and §226's four numeric ones, which carry theirs on the
        `object_sets.Aggregation` the caller validated. `None` means there was
        nothing to aggregate, which is not zero.
        """
        ...

    async def group_object_set(
        self,
        *,
        search_prefix: str,
        object_type_id: UUID,
        filters: "tuple[Any, ...]",
        property_name: str,
        limit: int,
        aggregation: "Any" = None,
    ) -> "tuple[list[tuple[str, int, float | int | None]], int]":
        """One number per distinct value of a property - what a chart over a set
        plots (roadmap 1.5; §227's metric).

        Returns `(buckets, distinct_total)` where a bucket is
        `(value, count, metric)`. Ordered by count descending then value
        ascending - or by the **metric** when there is one, since that is what
        sizes a slice and truncation has to keep the largest. **Both parts of
        that ordering matter**: one key alone leaves ties to each store's own
        tie-break, so two deployments would draw the same data in a different
        order and one of them would look wrong to whoever knew the other.
        """
        ...

    async def cross_tab_object_set(
        self,
        *,
        search_prefix: str,
        object_type_id: UUID,
        filters: "tuple[Any, ...]",
        row_property: str,
        column_property: str,
        row_values: "tuple[str, ...]",
        column_values: "tuple[str, ...]",
    ) -> "dict[tuple[str, str], int]":
        """The cells of a cross-tab - what a Pivot Table shows (roadmap 1.5).

        **Cells only, and the axes are given rather than chosen.** Both axes
        come from `group_object_set`, so a pivot's row totals are the same
        numbers a bar chart over the same property draws; and OpenSearch's
        nested terms aggregation truncates its inner buckets per outer bucket,
        so a store choosing its own columns would produce a grid whose columns
        changed from row to row.

        A missing cell is zero. Returning only the non-empty ones keeps a
        sparse grid cheap and makes "no rows have both values" the same answer
        on both stores.
        """
        ...

    async def time_series_object_set(
        self,
        *,
        search_prefix: str,
        object_type_id: UUID,
        filters: "tuple[Any, ...]",
        interval: str,
    ) -> "list[tuple[datetime, int]]":
        """How many objects last changed in each time bucket - what a Time
        Series plots (roadmap 1.5).

        **Over `updated_at`, in UTC, and only over `updated_at`.** It is a real
        `timestamptz` on one store and a mapped `date` on the other, so both
        bucket it identically without knowing any property's type. A date
        *property* is stored untyped like every other, which is the same
        blocker ordered operators have (`object_sets.DATE_PROPERTY_HINT`).

        Only the buckets that have rows, ascending. Gaps are filled once in
        `object_sets.fill_time_buckets`, so the two stores cannot fill
        differently - and so a chart and an export of the same series agree.
        """
        ...


def _text_value(value: Any) -> str:
    """The text form used for filter comparison. Deliberately the same
    rule as `join_key` and `object_sets._text`: one definition of what a
    value *is*, so a filter and a link agree about it."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def join_key(value: Any) -> str | None:
    """The text form of a join value, shared by both stores so a link
    traverses to the same set whichever one is configured.

    Links join on the *text* of a value, not on a typed comparison. That is a
    deliberate narrowing, and it is the honest one: the two sides of a link
    are two independently-mapped datasets, so a department code can perfectly
    well arrive as an integer on one side and a string on the other, and a
    type-strict join would silently find nothing in exactly the case the
    feature exists for. The cost is that 1 and 1.0 are different keys - which
    is also true of the upstream data they were read from.

    None means "no key": a null property points at nothing, so the traversal
    is empty rather than matching every instance whose property is also null.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"  # not Python's "True"
    return str(value)


def _index_name(search_prefix: str, object_type_id: "UUID | str") -> str:
    """One index per object type (decision 0006 §1).

    **This used to be one index per workspace**, and the name it returned is
    still reachable as `instance_mapping.legacy_index_name` because a
    deployment that has not run the migration still has one. The reason for the
    split is that an object type *is* a schema: a workspace holding an Order
    whose `status` is a string and a Reading whose `status` is an integer
    cannot have one mapping for `properties.status`, so declared types were not
    merely hard to honour in the old shape — they were inexpressible.

    The naming lives in `instance_mapping`, with the rules and the test that
    the workspace-wide pattern does not also match the index this replaces.
    """
    return instance_mapping.index_name(search_prefix, object_type_id)


def _bound_value(bound: Any) -> Any:
    """A comparable, in the form a query body carries it.

    `object_sets.comparable` answers in Python's own types so the reference
    semantics can compare them; a datetime has to go over the wire as the
    ISO-8601 text the `date` mapping declares it accepts. Bound through the
    same function the reference compares with, so the value a query carries is
    the value that definition agreed to.
    """
    return bound.isoformat() if isinstance(bound, datetime) else bound


def _sort_clause(sort: "Any") -> list[dict[str, Any]]:
    """p.223's **Default sort(s)**, as an OpenSearch sort: one, or several.

    The whole list ties on `primary_key` **once, last**, so two rows that share
    an `updated_at` - which a bulk sync makes routine, since it writes them in
    the same instant - come back in the same order on both stores and on every
    page. Without that, "the next page" can repeat a row it already showed and
    skip one it never did, and nothing about the symptom points at the sort.

    Once, and last, for the reason `instances._order_by` gives: `primary_key` is
    unique, so any sort field after it can never fire. A per-entry tie-break
    would leave an author's second and third orderings configured and dead.

    A **property sort** (§221) needs the tie-break more, not less: `status` has
    five distinct values over a million rows, so almost every page boundary
    falls inside a group of equals.
    """
    from . import object_sets

    sorts = sort if isinstance(sort, tuple) else (sort,)
    if not sorts:
        sorts = (object_sets.DEFAULT_SORT,)
    fields: list[dict[str, Any]] = []
    for one in sorts:
        fields.extend(_sort_field(one))
    key_of = lambda s: s if isinstance(s, str) else s.key  # noqa: E731
    if not any(key_of(one) in ("key", "-key") for one in sorts):
        fields.append({"primary_key": "asc"})
    return fields


def _sort_field(sort: "Any") -> list[dict[str, Any]]:
    """One ordering, with no tie-break of its own - see `_sort_clause`."""
    key = sort if isinstance(sort, str) else sort.key
    if key == "key":
        return [{"primary_key": "asc"}]
    if key == "-key":
        return [{"primary_key": "desc"}]
    if key == "oldest":
        return [{"updated_at": "asc"}]
    if isinstance(sort, str) or sort.property is None or key == "recent":
        return [{"updated_at": "desc"}]
    return [
        # `missing: _last` in **both** directions. OpenSearch's default already
        # puts missing values last, but a descending sort inverts a great many
        # defaults and stating it costs nothing - Postgres genuinely does put
        # NULLs first descending, and a page that opens with the unusable rows
        # on one store and the largest on the other is the invisible kind of
        # wrong the cross-store tests exist for.
        {f"properties.{sort.property}": {
            "order": "desc" if sort.descending else "asc", "missing": "_last",
        }},
    ]


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

    async def _ensure_index(
        self, index: str, declared: "list[dict[str, Any]] | None" = None
    ) -> None:
        """Create the type's index, or widen the one that exists.

        **Two operations, deliberately not one.** Creating is what the first
        sync of a type does. *Widening* is what a later one does after somebody
        declared another property: OpenSearch adds a field to an existing
        mapping happily, and a store that only created would leave the new
        property undeclared — which, under `dynamic: "strict"`, means the next
        document carrying it is **refused** rather than silently mapped by
        guess. That refusal is correct (0006 §5) and this is what stops it
        firing for the ordinary case.

        A *changed* type is neither, and is not done here: OpenSearch cannot
        remap a field in place, so it is a reindex (0006 §4) with a cost that
        belongs in the impact report rather than inside a sync.
        """
        exists = await self._client.indices.exists(index=index)
        if not exists:
            await self._client.indices.create(
                index=index, body=instance_mapping.mapping_for(declared)
            )
            return
        if not declared:
            return
        live = await self._client.indices.get_mapping(index=index)
        added = instance_mapping.added_fields(live, declared)
        if not added:
            return
        await self._client.indices.put_mapping(
            index=index,
            body={"properties": {"properties": {"properties": added}}},
        )

    async def upsert_instances(
        self,
        *,
        search_prefix: str,
        object_type_id: UUID,
        source_id: UUID,
        rows: list[tuple[str, dict[str, Any]]],
        synced_at: datetime,
        declared: list[dict[str, Any]] | None = None,
    ) -> int:
        if not rows:
            return 0
        index = _index_name(search_prefix, object_type_id)
        await self._ensure_index(index, declared)

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
        self, *, search_prefix: str, object_type_id: UUID, source_id: UUID,
        synced_before: datetime,
    ) -> int:
        index = _index_name(search_prefix, object_type_id)
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

    async def delete_instances(
        self, *, search_prefix: str, object_type_id: UUID, source_id: UUID,
        primary_keys: list[str],
    ) -> int:
        """Remove named instances (`delete_object`, §138).

        Scoped by `source_id` as well as by key, because instance identity is
        `(source_id, primary_key)` - two sources feeding one object type can
        each hold a "1", and deleting a row from one dataset must not remove
        the other's.
        """
        if not primary_keys:
            return 0
        resp = await self._client.delete_by_query(
            index=_index_name(search_prefix, object_type_id),
            body={
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"source_id": str(source_id)}},
                            {"terms": {"primary_key": [str(k) for k in primary_keys]}},
                        ]
                    }
                }
            },
            refresh=True,
        )
        return int(resp.get("deleted", 0))

    # How many documents one migration round trip carries. Not the page size
    # a browser gets: this is a batch bound by the bulk body it produces, and
    # a thousand instances is a request a cluster is comfortable with while
    # still bounding memory here.
    MIGRATION_BATCH = 1000

    async def adopt_legacy_index(
        self, *, search_prefix: str, object_type_id: UUID,
        declared: list[dict[str, Any]] | None = None,
    ) -> int:
        legacy = instance_mapping.legacy_index_name(search_prefix)
        if not await self._client.indices.exists(index=legacy):
            # Nothing to migrate: a workspace created after the split, or one
            # already moved. Zero rather than an error, so the migration can be
            # run over every workspace without knowing which are which.
            return 0
        target = _index_name(search_prefix, object_type_id)
        await self._ensure_index(target, declared)

        moved = 0
        after: list[Any] | None = None
        while True:
            body: dict[str, Any] = {
                "query": {"term": {"object_type_id": str(object_type_id)}},
                # **`search_after`, not `from`/`size`.** Offset paging stops at
                # `index.max_result_window` — ten thousand documents — and a
                # migration that silently moved the first ten thousand of a
                # larger type would be the worst possible outcome here: a
                # workspace that looks migrated and is missing rows.
                #
                # **Sorted on `source_id` *and* `primary_key`, because neither
                # is unique alone.** Instance identity is the pair — two sources
                # feeding one object type can each hold a row keyed "1", which
                # `delete_instances` says in as many words. `search_after` on a
                # non-unique sort skips every document sharing the cursor's
                # value, so a type fed by two datasets would have lost rows
                # here: quietly, and in proportion to how many keys the two
                # datasets happen to share. It is the same rule `_sort_clause`
                # already states for a viewer's page, where the symptom is a
                # repeated row rather than a missing one.
                "sort": [{"source_id": "asc"}, {"primary_key": "asc"}],
                "size": self.MIGRATION_BATCH,
            }
            if after is not None:
                body["search_after"] = after
            resp = await self._client.search(index=legacy, body=body)
            hits = resp["hits"]["hits"]
            if not hits:
                break
            bulk_body: list[dict[str, Any]] = []
            for hit in hits:
                # **The document id is carried, not recomputed.** It is derived
                # from (source_id, primary_key) either way, but re-deriving it
                # would silently renumber anything whose id predates that rule -
                # and `action_runs.instance_id` points at these.
                bulk_body.append({"update": {"_index": target, "_id": hit["_id"]}})
                bulk_body.append({"doc": hit["_source"], "doc_as_upsert": True})
            result = await self._client.bulk(body=bulk_body, refresh="wait_for")
            if result.get("errors"):
                failed = [
                    item["update"]["error"]
                    for item in result["items"] if "error" in item.get("update", {})
                ]
                # 0006 §5: loudly broken beats quietly wrong. A document the new
                # mapping refuses is a value that does not fit its declared
                # type, and skipping it would leave an index quietly missing
                # rows a filter should have matched.
                raise RuntimeError(
                    f"migrating {object_type_id} had {len(failed)} refusal(s): {failed[:3]}"
                )
            moved += len(hits)
            cursor = hits[-1]["sort"]
            # **A cursor that does not advance is a hang, and a hang is the
            # worst failure a migration can have**: nothing to read, nothing
            # logged, and no way to tell it from a large one still working.
            # Reachable if a store ever ignores `search_after` or answers a
            # page it has already given — found by a mutant that did exactly
            # that and spun the harness for four minutes rather than failing.
            if cursor == after:
                raise RuntimeError(
                    f"migrating {object_type_id} made no progress past {cursor!r} - "
                    "the store is not honouring search_after"
                )
            after = cursor
        return moved

    async def drop_type(self, *, search_prefix: str, object_type_id: UUID) -> None:
        await self._client.indices.delete(
            index=_index_name(search_prefix, object_type_id),
            # A type deleted before it ever synced has no index, and a delete
            # that raised would make the type undeletable - the ontology's
            # record gone or kept depending on whether anything had been
            # indexed yet.
            ignore_unavailable=True,
        )

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
        index = _index_name(search_prefix, object_type_id)
        resp = await self._client.search(
            index=index,
            body={
                "query": {"term": {"object_type_id": str(object_type_id)}},
                "sort": [{"updated_at": "desc"}],
                "from": offset,
                "size": limit,
            },
            # **An object type that has never synced now has no index at all.**
            # Before the split it read from the workspace's index, which existed
            # the moment anything at all had synced, so "no instances yet" and
            # "no index yet" were the same state and neither was an error. They
            # are different states now, and a browser that 404'd on a type
            # nobody had synced would be reporting a broken cluster to describe
            # an empty table.
            ignore_unavailable=True,
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
        index = _index_name(search_prefix, object_type_id)
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
        index = _index_name(search_prefix, object_type_id)
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
        resp = await self._client.search(
            index=instance_mapping.all_types_pattern(search_prefix),
            body=body,
            # A workspace with no synced type yet has no index at all, and a
            # pattern matching nothing is a 404 rather than an empty result.
            # An explorer that errored before the first sync would be reporting
            # a broken cluster to describe an empty workspace.
            ignore_unavailable=True,
        )
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

    @staticmethod
    def _set_clauses(object_type_id: UUID, filters: tuple[Any, ...]) -> dict[str, Any]:
        """The bool clauses for one set definition.

        Shared by paging and aggregating on purpose: two copies would be two
        definitions of what a set *is*, and the first time they drifted a
        Metric Card would count rows the table beside it does not show.
        """
        must: list[dict[str, Any]] = []
        must_not: list[dict[str, Any]] = []
        for f in filters:
            # The primary key is its own keyword field, not a property - and a
            # traversal landing on the far side's key filters on it
            # (`object_sets.PRIMARY_KEY_FILTER`). `keyword` already, so no
            # `.keyword` subfield and no analyser in the way.
            field = (
                "primary_key"
                if f.property == object_sets.PRIMARY_KEY_FILTER
                else f"properties.{f.property}"
            )
            if f.op == "eq":
                must.append({"term": {field: _text_value(f.value)}})
            elif f.op == "neq":
                must_not.append({"term": {field: _text_value(f.value)}})
            elif f.op == "in":
                must.append({"terms": {field: [_text_value(v) for v in f.value]}})
            elif f.op == "starts_with":
                must.append({
                    "multi_match": {
                        "query": _text_value(f.value),
                        "fields": [field],
                        "type": "phrase_prefix",
                    }
                })
            elif f.op in object_sets.GEO_OPERATORS:
                # Decision 0006 §3's whole argument, in one clause. The mapped
                # `geo_point` field answers this natively and **handles the
                # antimeridian itself** - a box whose `top_left` longitude is
                # east of its `bottom_right` one wraps, which is the same rule
                # `object_sets.in_box` states and the Postgres store writes out
                # as a union. Four range clauses would need the rule restated
                # here and would get it wrong the same silent way.
                must.append({"geo_bounding_box": {field: {
                    "top_left": {"lat": f.value.north, "lon": f.value.west},
                    "bottom_right": {"lat": f.value.south, "lon": f.value.east},
                }}})
            elif f.op in object_sets.ORDERED_OPERATORS:
                bound = object_sets.comparable(f.value, f.data_type)
                if bound is None:
                    # A bound that does not fit its own declared type — a
                    # `capacity > "abc"` a raw definition can hold. The
                    # reference says nothing matches, and an empty `terms` is
                    # how to say that without a second clause shape: sending a
                    # range with a null edge is an error rather than an answer.
                    must.append({"terms": {field: []}})
                else:
                    must.append({"range": {field: {f.op: _bound_value(bound)}}})
            else:  # pragma: no cover - object_sets.parse refuses anything else
                raise ValueError(f"unsupported object-set operator {f.op!r}")

        clauses: dict[str, Any] = {
            "filter": [{"term": {"object_type_id": str(object_type_id)}}, *must]
        }
        if must_not:
            clauses["must_not"] = must_not
        return clauses

    async def aggregate_object_set(
        self,
        *,
        search_prefix: str,
        object_type_id: UUID,
        filters: tuple[Any, ...],
        aggregation: "Any",
        property_name: str | None = None,
    ) -> "float | int | None":
        """Roadmap 1.5; §226. `size: 0` - the number is the answer, the
        documents are not, and fetching a page to count it would be the
        client-side filtering object sets exist to avoid."""
        from .instances import _named, _number

        agg = _named(aggregation)
        body: dict[str, Any] = {
            "query": {"bool": self._set_clauses(object_type_id, filters)},
            "size": 0,
        }
        if agg.numeric:
            # The typed field §220's mapping declares, **not** its `.keyword`
            # subfield: a numeric aggregation over indexed text is what this
            # was refused for. A document whose value would not fit the mapping
            # never indexed, so it is absent here for the same reason Postgres
            # sees NULL for it.
            field = f"properties.{agg.property}"
            # **`value_count` beside it, and it is not redundant.** "How many
            # documents matched" is the wrong emptiness test: a document can
            # match the filters and carry no value for this property at all -
            # or carry one that never indexed - and OpenSearch's `sum` then
            # answers `0.0` where Postgres answers NULL. `value_count` counts
            # the values the aggregation actually saw, which is exactly what
            # Postgres's NULL-skipping aggregates count.
            body["aggs"] = {
                "value": {agg.name: {"field": field}},
                "seen": {"value_count": {"field": field}},
            }
        elif agg.name == "count_distinct":
            # The `.keyword` subfield, which `_ensure_index` declares rather
            # than leaving to dynamic mapping - a cardinality aggregation on
            # the analysed text field would count *tokens*, so "Aberdeen Yard"
            # and "Bristol Yard" would share one.
            body["aggs"] = {
                "distinct": {"cardinality": {"field": f"properties.{property_name}.keyword"}}
            }
        resp = await self._client.search(
            index=_index_name(search_prefix, object_type_id), body=body,
            ignore_unavailable=True,
        )
        if agg.numeric:
            # **`0.0` over nothing is this store's answer, and it is the wrong
            # one.** OpenSearch's sum aggregation returns zero where Postgres
            # `sum()` returns NULL - the identical divergence decision 0006
            # exists to remove, arriving from the store that was supposed to be
            # the strict one. `seen` is what tells them apart.
            if int(resp["aggregations"]["seen"]["value"]) == 0:
                return None
            return _number(resp["aggregations"]["value"]["value"], agg)
        if agg.name == "count_distinct":
            return int(resp["aggregations"]["distinct"]["value"])
        return int(resp["hits"]["total"]["value"])

    async def group_object_set(
        self,
        *,
        search_prefix: str,
        object_type_id: UUID,
        filters: tuple[Any, ...],
        property_name: str,
        limit: int,
        aggregation: "Any" = None,
    ) -> "tuple[list[tuple[str, int, float | int | None]], int]":
        """Roadmap 1.5; §227's metric. A terms aggregation on the `.keyword`
        subfield, with an explicit two-key order so ties do not depend on the
        store."""
        from .instances import _named, _number

        agg = _named(aggregation) if aggregation is not None else None
        field = f"properties.{property_name}.keyword"
        clauses = self._set_clauses(object_type_id, filters)
        order: list[dict[str, str]] = [{"_count": "desc"}, {"_key": "asc"}]
        sub: dict[str, Any] = {}
        if agg is not None and agg.numeric:
            metric_field = f"properties.{agg.property}"
            # **The documents with no value for the metric are filtered out of
            # the whole query**, not just out of the metric - which is what
            # keeps the two stores in the same order. Left in, a bucket whose
            # documents all lack the property has a null metric on Postgres and
            # a `0.0` sum here, and the two sort it to opposite ends. It is
            # also the honest reading: a slice sized by average capacity is a
            # slice of the objects that have a capacity.
            clauses = {**clauses, "filter": [*clauses.get("filter", []),
                                             {"exists": {"field": metric_field}}]}
            sub = {"metric": {agg.name: {"field": metric_field}}}
            order = [{"metric": "desc"}, {"_key": "asc"}]
        body: dict[str, Any] = {
            "query": {"bool": clauses},
            "size": 0,
            "aggs": {
                "groups": {
                    "terms": {"field": field, "size": limit, "order": order},
                    **({"aggs": sub} if sub else {}),
                },
                "distinct": {"cardinality": {"field": field}},
            },
        }
        resp = await self._client.search(
            index=_index_name(search_prefix, object_type_id), body=body,
            ignore_unavailable=True,
        )
        buckets = [
            (str(b["key"]), int(b["doc_count"]),
             _number(b["metric"]["value"], agg) if sub else None)
            for b in resp["aggregations"]["groups"]["buckets"]
        ]
        return buckets, int(resp["aggregations"]["distinct"]["value"])

    async def cross_tab_object_set(
        self,
        *,
        search_prefix: str,
        object_type_id: UUID,
        filters: tuple[Any, ...],
        row_property: str,
        column_property: str,
        row_values: tuple[str, ...],
        column_values: tuple[str, ...],
    ) -> dict[tuple[str, str], int]:
        """Roadmap 1.5. A terms aggregation inside a terms aggregation, both
        pinned to the axis values with `include` and sized to them.

        `include` is what makes this a cross-tab rather than a stack of
        unrelated top-N lists: without it the inner terms would pick each row's
        own largest columns, and column 3 would mean something different on
        every line.
        """
        if not row_values or not column_values:
            return {}
        body: dict[str, Any] = {
            "query": {"bool": self._set_clauses(object_type_id, filters)},
            "size": 0,
            "aggs": {
                "rows": {
                    "terms": {
                        "field": f"properties.{row_property}.keyword",
                        "include": list(row_values),
                        "size": len(row_values),
                    },
                    "aggs": {
                        "cols": {
                            "terms": {
                                "field": f"properties.{column_property}.keyword",
                                "include": list(column_values),
                                "size": len(column_values),
                            }
                        }
                    },
                }
            },
        }
        resp = await self._client.search(
            index=_index_name(search_prefix, object_type_id), body=body,
            ignore_unavailable=True,
        )
        return {
            (str(row["key"]), str(col["key"])): int(col["doc_count"])
            for row in resp["aggregations"]["rows"]["buckets"]
            for col in row["cols"]["buckets"]
        }

    async def time_series_object_set(
        self,
        *,
        search_prefix: str,
        object_type_id: UUID,
        filters: tuple[Any, ...],
        interval: str,
    ) -> list[tuple[datetime, int]]:
        """Roadmap 1.5. A date histogram on `updated_at`.

        `calendar_interval` rather than `fixed_interval`: a month is not
        2,592,000 seconds, and Postgres's `date_trunc('month', ...)` lands on
        the first of the month whatever its length. A fixed interval would
        drift past every 31-day month and the two stores would slowly disagree
        about which bucket a row is in - starting correct, which is the worst
        way for a difference to begin.

        `time_zone` is stated rather than defaulted, for the same reason
        Postgres is pinned to UTC: two clusters configured differently would
        put the day boundary in different places.
        """
        body: dict[str, Any] = {
            "query": {"bool": self._set_clauses(object_type_id, filters)},
            "size": 0,
            "aggs": {
                "series": {
                    "date_histogram": {
                        "field": "updated_at",
                        "calendar_interval": interval,
                        "time_zone": "UTC",
                        # Only the populated buckets, matching what Postgres's
                        # GROUP BY returns. Asking OpenSearch to fill them
                        # would put the filling in one store and not the other.
                        "min_doc_count": 1,
                        "order": {"_key": "asc"},
                    }
                }
            },
        }
        resp = await self._client.search(
            index=_index_name(search_prefix, object_type_id), body=body,
            ignore_unavailable=True,
        )
        return [
            (
                datetime.fromtimestamp(int(b["key"]) / 1000, tz=timezone.utc),
                int(b["doc_count"]),
            )
            for b in resp["aggregations"]["series"]["buckets"]
        ]

    async def evaluate_object_set(
        self,
        *,
        search_prefix: str,
        object_type_id: UUID,
        filters: tuple[Any, ...],
        limit: int,
        offset: int,
        # An `object_sets.Sort`. A bare string is still accepted and means one
        # of the four fixed sorts, so a caller that has not been updated keeps
        # working - a property sort is the only thing that needs the value
        # object, because it is the only sort that carries a declared type.
        sort: "Any" = object_sets.DEFAULT_SORT,
    ) -> tuple[list[dict[str, Any]], int]:
        """Roadmap 1.2. Filters become query clauses rather than a post-filter
        over a page, which is the whole reason this is server-side.

        Properties are indexed as text, so ordered comparisons run against the
        same text the equality operators use - consistent with
        `object_sets.matches`, and consistent between the two stores, which
        matters more than either being individually cleverer.
        """
        limit = max(1, min(limit, INSTANCE_PAGE_SIZE))
        offset = max(0, offset)
        if offset + limit > MAX_RESULT_WINDOW:
            raise ValueError(
                f"pagination past {MAX_RESULT_WINDOW:,} rows needs search_after, not offset - "
                "not implemented here"
            )

        clauses = self._set_clauses(object_type_id, filters)
        body = {
            "query": {"bool": clauses},
            "sort": _sort_clause(sort),
            "from": offset,
            "size": limit,
        }
        resp = await self._client.search(
            index=_index_name(search_prefix, object_type_id), body=body,
            ignore_unavailable=True,
        )
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

    async def find_by_property(
        self,
        *,
        search_prefix: str,
        object_type_id: UUID,
        property_name: str | None,
        value: Any,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """Exact-equality lookup: the far end of a link traversal (roadmap
        Objects item 3). ``property_name=None`` means the instance's primary
        key rather than one of its properties.

        Not `search()` with a query string: that is `phrase_prefix` over every
        field, which would match a department called "Engineering West" when
        asked for "Engineering" and return the wrong objects with a straight
        face. A link is an equality, so it gets an equality.
        """
        key = join_key(value)
        if key is None:
            return [], 0
        limit = max(1, min(limit, INSTANCE_PAGE_SIZE))
        offset = max(0, offset)

        if property_name is None:
            # primary_key is mapped keyword, so one exact term is the whole test.
            should: list[dict[str, Any]] = [{"term": {"primary_key": key}}]
        else:
            field = f"properties.{property_name}"
            # Two clauses because the property's mapping depends on what the
            # first document put there: strings land on text + .keyword (the
            # dynamic template above), numbers and booleans land on long /
            # double / boolean with no subfield. Querying both and requiring
            # one costs nothing - a term on a field that does not exist
            # matches nothing rather than erroring - and avoids having to
            # trust the object type's *declared* data_type, which describes
            # the ontology, not what the mapper actually wrote.
            should = [
                {"term": {f"{field}.keyword": key}},
                {"term": {field: value}},
            ]
        body = {
            "query": {
                "bool": {
                    "filter": [{"term": {"object_type_id": str(object_type_id)}}],
                    "should": should,
                    "minimum_should_match": 1,
                }
            },
            "sort": [{"primary_key": "asc"}],
            "from": offset,
            "size": limit,
        }
        resp = await self._client.search(
            index=_index_name(search_prefix, object_type_id), body=body,
            ignore_unavailable=True,
        )
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
        # Accepted and unused: Postgres holds `properties` as `jsonb` and has
        # no mapping to keep in step, so the declaration reaches it and stops
        # there. Named rather than swallowed by `**_`, so the signature says
        # which store the argument is for.
        declared: list[dict[str, Any]] | None = None,
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
        self, *, search_prefix: str, object_type_id: UUID, source_id: UUID,
        synced_before: datetime,
    ) -> int:
        from . import instances as instances_service

        return await instances_service.delete_stale_instances(
            self._conn, source_id=source_id, synced_before=synced_before
        )

    async def delete_instances(
        self, *, search_prefix: str, object_type_id: UUID, source_id: UUID,
        primary_keys: list[str],
    ) -> int:
        from . import instances as instances_service

        return await instances_service.delete_instances(
            self._conn, source_id=source_id, primary_keys=primary_keys
        )

    async def adopt_legacy_index(
        self, *, search_prefix: str, object_type_id: UUID,
        declared: list[dict[str, Any]] | None = None,
    ) -> int:
        """Nothing to migrate: this store has no indices to split. A workspace
        on Postgres reaches per-type indices by `backfill` when it cuts over,
        which now writes them by construction."""
        return 0

    async def drop_type(self, *, search_prefix: str, object_type_id: UUID) -> None:
        """Nothing to do: `object_instances.object_type_id` is `ON DELETE
        CASCADE`, so Postgres has already forgotten them by the time the route
        gets here. Implemented rather than omitted, so the route can call one
        method without knowing which store it has."""
        return None

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

    async def find_by_property(
        self,
        *,
        search_prefix: str,
        object_type_id: UUID,
        property_name: str | None,
        value: Any,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        from . import instances as instances_service

        key = join_key(value)
        if key is None:
            return [], 0
        return await instances_service.find_by_property(
            self._conn,
            object_type_id=object_type_id,
            property_name=property_name,
            key=key,
            limit=limit,
            offset=offset,
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


    async def evaluate_object_set(
        self,
        *,
        search_prefix: str,
        object_type_id: UUID,
        filters: tuple[Any, ...],
        limit: int,
        offset: int,
        # An `object_sets.Sort`. A bare string is still accepted and means one
        # of the four fixed sorts, so a caller that has not been updated keeps
        # working - a property sort is the only thing that needs the value
        # object, because it is the only sort that carries a declared type.
        sort: "Any" = object_sets.DEFAULT_SORT,
    ) -> tuple[list[dict[str, Any]], int]:
        """`search_prefix` ignored, as everywhere else on this store: Postgres
        scopes by RLS and object_type_id."""
        from . import instances as instances_service

        return await instances_service.evaluate_object_set(
            self._conn,
            sort=sort,
            object_type_id=object_type_id,
            filters=filters,
            limit=limit,
            offset=offset,
        )

    async def aggregate_object_set(
        self,
        *,
        search_prefix: str,
        object_type_id: UUID,
        filters: tuple[Any, ...],
        aggregation: "Any",
        property_name: str | None = None,
    ) -> "float | int | None":
        from . import instances as instances_service

        return await instances_service.aggregate_object_set(
            self._conn,
            object_type_id=object_type_id,
            filters=filters,
            aggregation=aggregation,
            property_name=property_name,
        )

    async def group_object_set(
        self,
        *,
        search_prefix: str,
        object_type_id: UUID,
        filters: tuple[Any, ...],
        property_name: str,
        limit: int,
        aggregation: "Any" = None,
    ) -> "tuple[list[tuple[str, int, float | int | None]], int]":
        from . import instances as instances_service

        return await instances_service.group_object_set(
            self._conn,
            object_type_id=object_type_id,
            filters=filters,
            property_name=property_name,
            limit=limit,
            aggregation=aggregation,
        )

    async def cross_tab_object_set(
        self,
        *,
        search_prefix: str,
        object_type_id: UUID,
        filters: tuple[Any, ...],
        row_property: str,
        column_property: str,
        row_values: tuple[str, ...],
        column_values: tuple[str, ...],
    ) -> dict[tuple[str, str], int]:
        from . import instances as instances_service

        return await instances_service.cross_tab_object_set(
            self._conn,
            object_type_id=object_type_id,
            filters=filters,
            row_property=row_property,
            column_property=column_property,
            row_values=row_values,
            column_values=column_values,
        )

    async def time_series_object_set(
        self,
        *,
        search_prefix: str,
        object_type_id: UUID,
        filters: tuple[Any, ...],
        interval: str,
    ) -> list[tuple[datetime, int]]:
        from . import instances as instances_service

        return await instances_service.time_series_object_set(
            self._conn,
            object_type_id=object_type_id,
            filters=filters,
            interval=interval,
        )


async def split_workspace_index(
    conn: "AsyncConnection",
    gateway: "InstanceStoreGateway",
    *,
    workspace_id: UUID,
    search_prefix: str,
) -> dict[str, int]:
    """Move one workspace from the single index to one per object type.

    **Decision 0006 §1's data movement**, and the reason that document exists
    rather than a commit. Every instance is rewritten into the index its type
    now owns, with the mapping its declared types ask for.

    **Read from the old index, not from Postgres**, and the distinction is the
    whole correctness of this. `backfill` reads `object_instances` because it
    moves a workspace that is still *on* Postgres. A workspace already on
    OpenSearch has not written to those rows since its own cutover, so they are
    a snapshot of whenever that happened — reading them here would silently
    restore a workspace to an old state and call it a migration.

    Reading the index back is safe in the way that matters: OpenSearch stores
    `_source` verbatim, so the values come back as they were written rather
    than as the mapping indexed them. A `capacity` that was indexed as text is
    still the number it arrived as.

    Every document id is derived from `(source_id, primary_key)` and is not
    recomputed here, so running this twice rewrites exactly the same documents.
    **Run it, flip, run it again**: the second pass is a catch-up for anything
    written in between, not a duplicate — the same procedure the original
    cutover used, and the reason neither needs dual-write machinery.

    The old index is **not deleted.** A migration that removes its own source
    leaves nothing to compare counts against and nothing to fall back to, and
    an index costing disk is a smaller problem than a rollback that cannot
    happen. Dropping `{search_prefix}object-instances` is a step for whoever
    has checked the counts.
    """
    types = await fetch_all(
        conn,
        "SELECT id FROM object_types WHERE workspace_id = :wid ORDER BY id",
        {"wid": str(workspace_id)},
    )
    from . import ontology

    moved = 0
    for row in types:
        type_id = UUID(str(row["id"]))
        moved += await gateway.adopt_legacy_index(
            search_prefix=search_prefix,
            object_type_id=type_id,
            declared=await ontology.list_properties(conn, type_id),
        )
    return {"instances": moved, "object_types": len(types)}


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

    # Each type's declared properties, read once per type rather than once per
    # (type, source): a type with eight sources would otherwise ask the same
    # question eight times, and the answer cannot change inside a backfill.
    #
    # **Read at all** because decision 0006 made an index carry its type's
    # mapping. A backfill replaying rows with nothing declared would create
    # every index with an empty strict mapping and then have every document it
    # was copying refused - which is the correct refusal reaching the one
    # caller that has the declaration and had not been asked for it.
    from . import ontology

    declared_by_type: dict[UUID, list[dict[str, Any]]] = {}
    for object_type_id, _source_id in grouped:
        if object_type_id not in declared_by_type:
            declared_by_type[object_type_id] = await ontology.list_properties(
                conn, object_type_id
            )

    copied = 0
    for (object_type_id, source_id), group in grouped.items():
        copied += await gateway.upsert_instances(
            search_prefix=search_prefix,
            object_type_id=object_type_id,
            source_id=source_id,
            rows=group,
            synced_at=newest[(object_type_id, source_id)],
            declared=declared_by_type[object_type_id],
        )
    return {"instances": copied, "sources": len(grouped), "action_runs_remapped": remapped}

