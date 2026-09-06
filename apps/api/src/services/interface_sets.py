"""A set of objects across every type that implements one interface.

Foundry `ontology` p.61: *"Target the interface directly. A single workflow
covers all implementing types."* And p.62 item 3: *"Build actions, functions,
and applications against interfaces where possible."* §251 built the interface,
§252 made it findable and §253 gave it screens - and all three of those are
metadata, which p.61 says plainly is still worth having. This is the first
thing that *reads* an interface, and it is what turns the row from a
description into a feature.

**`object_sets.ObjectSet` stays one type, and its docstring's objection stays
true.** It says a set spanning types "has no coherent property vocabulary to
filter on", which was correct when nothing supplied one. An interface is
exactly that vocabulary, so this is not a wider `ObjectSet` - it is a *fan-out*
over several one-type sets whose results are re-keyed onto the shared shape.
Nothing here parses or evaluates a set: it translates names on the way in and
on the way out, and the existing store does the work in between, once per
implementing type. That is deliberate, and it is the reason an interface set
behaves identically on Postgres and OpenSearch without a line of store code:
there is no second evaluator to disagree with the first.

**Two refusals, and both are about not offering a wrong answer.**

*A property sort is refused.* Ordering by a property means comparing in the
property's declared type (§221), which is a rule the stores implement and this
module would have to re-implement to merge two types' pages into one order. A
second copy of that comparison is the drift this whole area is built to avoid,
so the ordering an interface set offers is the ones every row carries
verbatim - when it was last updated, and its primary key.

*Paging is bounded.* Serving rows `[offset, offset + limit)` of the merged
order needs each implementing type's first `offset + limit` rows, because any
of them could supply the whole page. That bound is stated (`MAX_DEPTH`) and
refused past rather than silently returning a short page, which is decision
0002's rule: a set that quietly returns fewer rows than it should is the
failure that is invisible until somebody counts.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

#: How many object types one interface may fan out over in a single read.
#:
#: p.53 puts no limit on how many types implement an interface, and this is not
#: a claim that there is one - it is a limit on *one query*, because a read is a
#: store call per type and an interface twenty types wide is twenty round trips
#: to answer one page. Refused rather than truncated: an interface set that
#: silently covered the first ten of thirty types would be the wrong answer with
#: no way to tell.
MAX_IMPLEMENTATIONS = 12

#: How deep an interface set pages. `offset + limit` must fit inside this,
#: because each implementing type has to be asked for that many rows before the
#: merge can know which of them are on the page.
#:
#: **One store page**, and that is a hard ceiling rather than a policy: both
#: stores clamp a read to `INSTANCE_PAGE_SIZE` (`instance_store` lines 653 and
#: 1100), so asking one type for 60 rows returns 50 and the merge would drop
#: real members off the end of the order without knowing it. Restated here so
#: this module keeps importing nothing - the two are asserted equal by a test,
#: which is the shape `object_sets.PRIMARY_KEY_FILTER` already uses.
MAX_DEPTH = 50

#: The orderings an interface set may use.
#:
#: **`object_sets.SORTS` exactly**, spelled out here so this module keeps
#: importing nothing, and asserted equal by a test - the same shape
#: `PRIMARY_KEY_FILTER` already uses one module over. Naming them differently
#: would be a second vocabulary for the same four orderings, which is a
#: translation table nobody would remember to keep in step.
#:
#: All four are orderings whose key every row carries as a value, which is what
#: makes merging several types' pages a comparison of data rather than a second
#: implementation of the stores' rule. A *property* sort is not on the list for
#: exactly that reason, and `parse_sort` says so.
SORTS = ("key", "-key", "recent", "oldest")

#: Which field each of those reads, and in which direction.
_SORT_KEYS: dict[str, tuple[str, bool]] = {
    "recent": ("updated_at", True),
    "oldest": ("updated_at", False),
    "key": ("primary_key", False),
    "-key": ("primary_key", True),
}


class InterfaceSetError(ValueError):
    """Refused, in a sentence somebody building a workflow can act on."""


class _Unanswered(Exception):
    """Raised inside `translate_filters` when the type being translated for
    answers nothing to a filtered property.

    Not an `InterfaceSetError`, because it is not a refusal: it is "no object
    of this type can match", which `filters_for` turns into an answer. Private
    for that reason - a caller that let it escape would report a filter as
    invalid when it is merely unsatisfiable here.
    """

    def __init__(self, property_name: str) -> None:
        super().__init__(property_name)
        self.property_name = property_name


@dataclass(frozen=True)
class Member:
    """One implementing type, and how its properties answer the interface's."""

    object_type_id: UUID
    #: `{interface property: this type's property}` - p.66's mapping, exactly
    #: as `object_type_interfaces.property_mapping` stores it.
    property_mapping: dict[str, str]


def check_fan_out(members: list[Member], *, interface_name: str) -> None:
    """Refuse a read that would be too many store calls to be one read."""
    if not members:
        raise InterfaceSetError(
            f"nothing implements {interface_name}, so it has no objects - "
            "implement it on an object type first"
        )
    if len(members) > MAX_IMPLEMENTATIONS:
        raise InterfaceSetError(
            f"{interface_name} is implemented by {len(members)} object types "
            f"and an interface set reads at most {MAX_IMPLEMENTATIONS} at once"
        )


def check_depth(*, limit: int, offset: int) -> None:
    """Refuse a page the merge cannot serve correctly.

    Stated as a refusal rather than a clamp because the two are different
    answers: a clamped read returns a page from the wrong place in the order
    and says nothing about it.
    """
    if offset + limit > MAX_DEPTH:
        raise InterfaceSetError(
            f"an interface set pages to {MAX_DEPTH} objects "
            f"(asked for {offset} + {limit}) - narrow it with a filter"
        )


def parse_sort(raw: Any) -> str:
    """One of `SORTS`, or a refusal naming what a property sort would need."""
    key = "recent" if raw is None else str(raw)
    if key in SORTS:
        return key
    raise InterfaceSetError(
        f"an interface set cannot sort by {key!r} "
        f"(supported: {', '.join(SORTS)}) - ordering by a property means "
        "comparing in that property's declared type, which each implementing "
        "type would answer differently"
    )


def translate_filters(
    raw_filters: Any, *, member: Member, declared: dict[str, str], interface_name: str
) -> list[dict[str, Any]]:
    """Rewrite filters written against the interface onto one type's names.

    `declared` is the interface's own `{api_name: data_type}` - its *effective*
    properties, since an inherited one is part of the shape an implementation
    answers.

    **A filter naming something the interface does not declare is refused**,
    not passed through. Passing it through would let a workflow written against
    `Inspectable` reach into a Vehicle's `mileage` on the types that happen to
    have one and silently match nothing on the types that do not - a set whose
    membership depends on which type a row came from, which is the opposite of
    what an interface set is for.
    """
    if raw_filters is None:
        return []
    if not isinstance(raw_filters, list):
        raise InterfaceSetError("filters must be a list")
    out: list[dict[str, Any]] = []
    for entry in raw_filters:
        if not isinstance(entry, dict):
            raise InterfaceSetError("each filter must be an object")
        name = entry.get("property")
        if not name or not isinstance(name, str):
            raise InterfaceSetError("each filter needs a property name")
        if name not in declared:
            raise InterfaceSetError(
                f"{interface_name} does not declare {name!r} "
                f"(it declares {', '.join(sorted(declared)) or 'nothing'})"
            )
        target = member.property_mapping.get(name)
        if not target:
            # An *optional* interface property this type answers nothing to.
            # Filtering on it cannot match here, and the honest reading of that
            # is that this type contributes nothing - which the caller handles
            # by skipping the member, not by dropping the filter.
            raise _Unanswered(name)
        out.append({**entry, "property": target})
    return out


def filters_for(
    raw_filters: Any, *, member: Member, declared: dict[str, str], interface_name: str
) -> list[dict[str, Any]] | None:
    """`translate_filters`, with "this type is not in the set" as an answer.

    `None` means the filter names an optional property this type maps nothing
    to. p.62's "design interfaces around capabilities" makes that an ordinary
    shape - a capability with one mandatory field and two optional ones - and
    the only correct reading of `notes eq "x"` on a type with no notes is that
    no object of that type matches. Returning an empty filter list instead
    would return **every** object of that type, which is decision 0002's silent
    widening: more rows than asked for, because something was unset.
    """
    try:
        return translate_filters(
            raw_filters, member=member, declared=declared,
            interface_name=interface_name,
        )
    except _Unanswered:
        return None


def project(
    properties: dict[str, Any], *, member: Member, declared: dict[str, str]
) -> dict[str, Any]:
    """One row's properties, re-keyed onto the interface's vocabulary.

    **Everything else is dropped**, and that is the feature rather than a
    limitation: a workflow written against `Inspectable` gets
    `last_inspection_date` from a Vehicle and from a Facility, and does not get
    a Vehicle's `mileage` on some rows and a Facility's `capacity` on others.
    Carrying the extras through would make a set whose columns depend on which
    type each row happens to be, which is what p.61's single workflow is
    defined against.

    An optional property this type answers nothing to is absent rather than
    null: absent is what "this object has no such value" already means
    everywhere else that reads a property bag.
    """
    out: dict[str, Any] = {}
    for name in declared:
        target = member.property_mapping.get(name)
        if target and target in properties:
            out[name] = properties[target]
    return out


def merge(
    pages: list[list[dict[str, Any]]], *, sort: str, limit: int, offset: int
) -> list[dict[str, Any]]:
    """One page of the combined order, from each type's already-ordered page.

    The merge key is a value each row carries - `updated_at` or `primary_key` -
    which is why `parse_sort` refuses everything else. Sorted rather than
    heap-merged because the input is bounded by `MAX_DEPTH` per type and a
    correct twelve-way merge is more code than a sort of at most 2,400 rows is
    worth.

    **Ties are broken by primary key**, so two objects updated in the same
    transaction do not swap places between two reads of the same page. Without
    it the order is only as stable as the store's own tie-breaking, which is
    two different answers on two stores.
    """
    field, descending = _SORT_KEYS[sort]
    rows = [row for page in pages for row in page]
    rows.sort(key=lambda r: str(r.get("primary_key") or ""))
    rows.sort(key=lambda r: _key(r.get(field)), reverse=descending)
    return rows[offset : offset + limit]


def _key(value: Any) -> str:
    """A comparable form of a merge key.

    Text, because the two fields are a timestamp and a primary key, and the
    stores hand the first back as a `datetime` on Postgres and an ISO string on
    OpenSearch.

    **The guarantee is within one read, not across the two stores**, and the
    difference matters enough to write down: every page merged here comes from
    one store, so every key is in that store's own shape and they sort against
    each other. Two ISO renderings of the same instant can differ in their
    offset spelling, so this would be the wrong comparison for keys from *both*
    stores at once - which nothing does, and nothing should.
    """
    if value is None:
        return ""
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else str(value)
