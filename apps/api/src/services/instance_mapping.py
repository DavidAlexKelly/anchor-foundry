"""One index per object type, mapped from the ontology's declared types
(`docs/decisions/0006-typed-instance-properties.md` §1 and §2).

**The problem this exists to remove**, stated once by the decision and repeated
here because this module is where the answer lives:

> "So the same filter reads `250 > 40` on one store and `"250" < "40"` on the
> other. The first implementation shipped both and the cross-store test caught
> them disagreeing on the first run, which is why the operators were withdrawn
> rather than picked."

Instance properties are stored untyped, and until now **one index served every
object type in a workspace** — so a workspace holding an Order whose `status` is
a string and a Reading whose `status` is an integer could not have one mapping
for `properties.status`. That is not a hard mapping to write; it is one that
cannot be expressed. Hence 0006 §1: an object type *is* a schema, and two
schemas are two mappings.

**This module is pure.** It answers "what index, and what mapping" and knows
nothing about clients, connections or clusters, so every rule below is
checkable without either store — which is the whole reason the type decisions
are here rather than inline in `instance_store`.

**What is deliberately not here yet.** No ordered operator, numeric
aggregation, property sort or map box ships in this unit. 0006 §6 refuses to
ship any of them on one store before the other, and this is the structural half
that both stores need first. `ORDERABLE_TYPES` is stated below because the
mapping is what makes it true — a `date` field is orderable *because* it is
mapped `date` — and having it stated is what lets the next unit be an
implementation rather than another design.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

# Every declared type (`property_data_type`, db 0003 widened by db 0029), and
# the OpenSearch field it becomes.
#
# The judgement per type, stated once:
#
# - `string` is **`text` with a `keyword` subfield**, not plain `keyword`. Both
#   are needed and for different readers: the workspace explorer searches words
#   inside a value, and link traversal needs exact equality on the whole value.
#   `ignore_above` is 8192 rather than the 256 a dynamic mapping would give,
#   because a keyword silently stops being indexed past the limit — so a long
#   join key would traverse to nothing, for a reason invisible from outside.
# - `integer` is **`long`**. `integer` in OpenSearch is 32-bit, and an id
#   column past two billion is an ordinary thing for a source dataset to hold.
# - `float` is **`double`**, for the same reason in the other direction:
#   single-precision silently rounds values a source held exactly.
# - `date` and `timestamp` are both **`date`** with an explicit format list.
#   One field type for two declared types is right — a date *is* a timestamp at
#   midnight — and the format list is what stops the cluster guessing: db 0029
#   says both are "ISO-8601 text, with an offset preserved when the source has
#   one", so the mapping accepts a date, a datetime, and epoch millis.
# - `geopoint` is **`geo_point`**, which is 0006 §3's whole argument: a bounding
#   box expressed as four comparisons on two numbers gets the antimeridian
#   silently wrong, and `geo_point` does not.
# - `json` and `attachment` are **`object` with `enabled: false`**. Both are
#   composite values nothing filters on, and indexing them would map whatever
#   keys the first document happened to carry — a mapping written by data
#   rather than by a declaration, which is the failure this file exists to end.
FIELD_TYPES: dict[str, dict[str, Any]] = {
    "string": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 8192}}},
    "integer": {"type": "long"},
    "float": {"type": "double"},
    "boolean": {"type": "boolean"},
    "date": {"type": "date", "format": "strict_date_optional_time||epoch_millis"},
    "timestamp": {"type": "date", "format": "strict_date_optional_time||epoch_millis"},
    "geopoint": {"type": "geo_point"},
    "json": {"type": "object", "enabled": False},
    "attachment": {"type": "object", "enabled": False},
}

# What an ordered comparison may be asked of (0006 §2). Not used by anything in
# this unit; stated here because this file is what makes it true.
#
# **`string` is absent permanently, not pending.** Lexicographic order is the
# database collation on Postgres and byte order on OpenSearch, so `'Z' < 'a'`
# differs between them — the same disagreement this whole file removes, one
# layer down and much harder to see. `boolean` is absent because "greater than
# false" is not a question; `json` and `attachment` because composite values
# have no order anybody would agree on.
ORDERABLE_TYPES = ("integer", "float", "date", "timestamp")

# A declared type this platform has never heard of — a row written by a future
# migration against an older API, or a hand-edited database. Mapped as a string
# rather than refused: an index that cannot be created makes every instance of
# that type unreadable, and the property is still *findable* this way even
# though it will not be orderable.
FALLBACK_TYPE = "string"


def field_for(data_type: Any) -> dict[str, Any]:
    """One property's mapping, from its declared type."""
    if isinstance(data_type, str) and data_type in FIELD_TYPES:
        return dict(FIELD_TYPES[data_type])
    return dict(FIELD_TYPES[FALLBACK_TYPE])


def index_name(search_prefix: str, object_type_id: UUID | str) -> str:
    """The index one object type's instances live in.

    `search_prefix` already ends in `-` (db 0002: `f"{slug}-{short_id}-"`) and
    is lowercase-slug-derived, so the result satisfies OpenSearch's name rules
    without re-validating. The type id is a UUID, which is lowercase hex and
    hyphens — also always legal.
    """
    return f"{search_prefix}objects-{object_type_id}"


def all_types_pattern(search_prefix: str) -> str:
    """Every object type's index in one workspace, for the explorer (§98).

    A pattern rather than a list, so a search does not have to know which types
    exist before it can run — and so a type created between the two calls is
    not silently missing from the results.

    **It must not match `{prefix}object-instances`**, the single index this
    replaces: a half-migrated workspace would otherwise return each instance
    twice, once from each shape. `objects-` and `object-instances` differ at
    the character after `object`, which is what makes the two nameable apart.
    """
    return f"{search_prefix}objects-*"


LEGACY_INDEX_SUFFIX = "object-instances"


def legacy_index_name(search_prefix: str) -> str:
    """The one-index-per-workspace name this replaces.

    Kept nameable because the migration has to read it, and because a
    deployment that has not run the migration still has one.
    """
    return f"{search_prefix}{LEGACY_INDEX_SUFFIX}"


def mapping_for(properties: list[dict[str, Any]] | None) -> dict[str, Any]:
    """The index body for one object type.

    `properties` is `ontology.list_properties`'s shape — each row carrying an
    `api_name` and a `data_type`. A type with none declared still gets an
    index: instances can exist before properties do, and an index that appears
    only once somebody declares a property would make the first sync fail for a
    reason nobody could act on.

    **`dynamic: "strict"` on the properties object**, which is the point of the
    whole exercise. A value whose property is not declared is refused by the
    cluster rather than mapped by guess — 0006 §5's rule that it is better to
    be loudly broken than quietly wrong, applied at write time instead of at
    reindex time. Left dynamic, the first document carrying an undeclared
    property would decide its type for every document after it, and the
    declaration would have been for nothing.
    """
    fields: dict[str, Any] = {}
    for row in properties or []:
        if not isinstance(row, dict):
            continue
        name = row.get("api_name")
        if not isinstance(name, str) or not name:
            continue
        fields[name] = field_for(row.get("data_type"))
    return {
        "mappings": {
            "properties": {
                "object_type_id": {"type": "keyword"},
                "source_id": {"type": "keyword"},
                "primary_key": {"type": "keyword"},
                "updated_at": {"type": "date"},
                "properties": {
                    "type": "object",
                    "dynamic": "strict",
                    "properties": fields,
                },
            },
        }
    }


def added_fields(
    existing: dict[str, Any] | None, properties: list[dict[str, Any]] | None
) -> dict[str, Any]:
    """Fields in the wanted mapping that the live one does not have.

    Declaring a *new* property is not a reindex: OpenSearch adds a field to an
    existing mapping happily, and the documents already indexed simply have no
    value for it. Only a **changed** type needs 0006 §4's reindex, and telling
    the two apart is what keeps the ordinary case — somebody adding a column —
    from rewriting a type's instances.

    Returns only additions. A field whose mapping *differs* is deliberately not
    reported here: it is a different operation with a different cost, and
    lumping them together is how a reindex gets run by accident.
    """
    live = _mapped_properties(existing)
    wanted = mapping_for(properties)["mappings"]["properties"]["properties"]["properties"]
    return {name: field for name, field in wanted.items() if name not in live}


def retyped_fields(
    existing: dict[str, Any] | None, properties: list[dict[str, Any]] | None
) -> list[str]:
    """Properties whose declared type no longer matches the live mapping.

    0006 §4: "OpenSearch cannot change a field's mapping in place, so a type
    change is a reindex of that object type" — and this is what says whether
    one is needed. Compared on the **field type alone**, not the whole
    dictionary: a mapping OpenSearch echoes back carries defaults nobody wrote,
    so comparing dictionaries would report a reindex for every index on every
    check.
    """
    live = _mapped_properties(existing)
    wanted = mapping_for(properties)["mappings"]["properties"]["properties"]["properties"]
    return sorted(
        name for name, field in wanted.items()
        if name in live and live[name].get("type") != field.get("type")
    )


def _mapped_properties(existing: dict[str, Any] | None) -> dict[str, Any]:
    """The `properties.*` field mappings out of what a cluster returned.

    Tolerant of every shape a get-mapping answer arrives in — keyed by index
    name or not, with or without the `mappings` wrapper — because this reads a
    response rather than a document we wrote, and a missing key here would mean
    reporting every field as new and adding them all again.
    """
    node = existing
    if not isinstance(node, dict):
        return {}
    if "mappings" not in node and len(node) == 1:
        node = next(iter(node.values()))
    if not isinstance(node, dict):
        return {}
    node = node.get("mappings", node)
    if not isinstance(node, dict):
        return {}
    node = node.get("properties", {})
    if not isinstance(node, dict):
        return {}
    node = node.get("properties", {})
    if not isinstance(node, dict):
        return {}
    fields = node.get("properties", {})
    return fields if isinstance(fields, dict) else {}
