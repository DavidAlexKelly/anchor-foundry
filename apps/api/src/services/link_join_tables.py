"""Following a many-to-many link through its join table (§552; db 0115;
`object-link-types` p.35, p.197).

    "Join table dataset: For "many-to-many" cardinality link types. This option
     allows you to use a join table dataset to back the link." (p.197)

A property-pair link (db 0027) is followed by reading a value off the near
object and matching it on the far type. A join-table link has no such value:
the pairs are rows of a dataset. So it is followed in two steps - the near
objects' primary keys, through the join table, to the far objects' primary
keys - and the second step is the same `in` on the far type's primary key
that a pair joined on `$primary_key` would produce. Everything downstream of
the keys is therefore the traversal that already existed, on both stores.

**Read from the dataset's current version, at the time of asking**, which is
0027's argument for deriving a link rather than storing it: nothing to keep in
sync, so nothing to go stale. A join table updated by a build is followed as
updated at the next read.
"""
from __future__ import annotations

from typing import Any

import anyio

from ..lib.db import fetch_one
from . import dataset_engine as engine
from . import object_sets
from . import storage


def reversed_join(join: dict[str, Any]) -> dict[str, Any]:
    """The same join table followed the other way: from the far objects back
    to the near ones, as a filter on linked objects asks (§545)."""
    return {**join, "near_column": join["far_column"], "far_column": join["near_column"]}


def oriented(link: dict[str, Any], *, outbound: bool) -> dict[str, Any] | None:
    """A link's join table from one end: which column holds the keys of the
    objects in hand, and which the keys to arrive at. `None` for a link joined
    on a property pair, or one whose join table has been deleted."""
    if not link.get("join_dataset_id"):
        return None
    near, far = str(link["join_from_column"]), str(link["join_to_column"])
    return {
        "dataset_id": str(link["join_dataset_id"]),
        "near_column": near if outbound else far,
        "far_column": far if outbound else near,
    }


async def follow(conn: Any, join: dict[str, Any], keys: list[Any]) -> list[str]:
    """The far primary keys the join table pairs with these near ones, at most
    `MAX_JOIN_VALUES + 1` - one past the cap, so `join_filter` refuses a
    traversal that starts too wide with its number rather than a join table
    quietly cut short."""
    wanted = sorted({str(k) for k in keys if k is not None})
    if len(wanted) > object_sets.MAX_JOIN_VALUES:
        # `join_filter`'s refusal, a step earlier: past the cap the table
        # would be read for a prefix of the keys, and the set would quietly
        # miss the links of the rest.
        raise ValueError(
            f"this traversal starts from {len(wanted)} objects and the limit is "
            f"{object_sets.MAX_JOIN_VALUES} - narrow the set it traverses from first"
        )
    # No early return for no keys: `join_keys` answers them with nothing
    # itself (a guard for it here survived the sweep as equivalent).
    row = await fetch_one(
        conn, "SELECT s3_location FROM datasets WHERE id = :id", {"id": join["dataset_id"]}
    )
    if row is None:
        # RLS: the reader cannot see the dataset the pairs live in. Said, since
        # "nothing linked" and "not allowed to know" look the same as a count.
        raise ValueError(
            "the join table behind this link is a dataset you cannot read, so the "
            "link cannot be followed"
        )
    path = await anyio.to_thread.run_sync(storage.current().local_path, str(row["s3_location"]))
    try:
        return await anyio.to_thread.run_sync(
            engine.join_keys, path, join["near_column"], join["far_column"],
            wanted, object_sets.MAX_JOIN_VALUES + 1,
        )
    except engine.DatasetEngineError as exc:
        raise ValueError(str(exc)) from exc
