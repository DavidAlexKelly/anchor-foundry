"""A multiple-choice parameter's allowed values (§335; db 0086;
`action-types` p.33).

    "Adding filters to non-object reference **multiple choice** or single object
     reference parameters will determine the allowed values that are selectable
     in the parameter's dropdown." (p.33)

    "…action editors can reduce allowed values to just those that are properties
     of an object set… select the property that includes all allowed values for
     the parameter dropdown. **If only one linked object is available in the
     resulting object set and the parameter is required, the parameter dropdown
     will automatically prefill with the corresponding property value.** The
     resulting multiple choice options will be derived from the set of objects
     that the user has permission to view." (p.33)

**p.33's first sentence names two shapes and §330-§334 built one of them.** A
single object reference offers *objects*; a multiple-choice parameter offers
values — the values one property takes across a set of objects. "Which region"
is then answered by the regions that exist rather than by a list somebody
retyped, which is the whole reason p.33 describes deriving them.

**The distinct values come from the store, not from a page of objects.**
`group_object_set` returns one bucket per distinct value *and the true number of
distinct values*, so "there are more than fit" is a fact rather than an artefact
of how many rows were read. Collapsing a page of fifty objects would answer a
different question — the distinct values *of those fifty* — and nothing on
screen could say which was meant. That is §256's trap, and this is the one read
that does not fall into it.

**p.33's permission sentence is free**, as it was for §330: the read goes
through the caller's own connection, so RLS has already narrowed the objects
before this module sees a value.

**p.33's own word is "linked", and §337 is where that becomes true.**

    "…**ensure the parameter is set to display multiple choices, select Get
     options from an object set, configure the desired object set**, and select
     the property that includes all allowed values… If only one **linked**
     object is available in the resulting object set…" (p.33)

"Configure the desired object set" is three separate things, and they arrived
one unit at a time: a type and a property (§335), filters over it (§336), and
p.37's Search Around (§337). Until the last of them "the resulting object set"
was always every object of one type — nothing could be linked to anything, so
p.33's prefill sentence described a condition this platform could not produce.
The walk arrives here already compiled, as the same nested `ObjectSet` an object
dropdown is handed, and is collapsed by the same resolver: one answer to "which
objects", asked by two shapes.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from . import instance_store
from . import object_set_eval
from . import instances as instances_service

#: How many options a dropdown offers, and the store's own page size for
#: §330's reason: a larger number here would be a promise overruled one call
#: down. Past it the form says so rather than silently offering a slice.
MAX_OPTIONS = instance_store.INSTANCE_PAGE_SIZE

#: The parameter types p.33's multiple choice applies to. **Not `object`** —
#: that shape is p.33's *other* one and has had its own dropdown since §330, so
#: a parameter carrying both would be two answers to "what may I pick".
#: `json` and `attachment` are out for a plainer reason: a dropdown of them is
#: not a thing anybody can read.
OPTIONABLE_TYPES = (
    "string", "integer", "float", "boolean", "date", "timestamp", "geopoint",
)


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def options_of(parameter: dict[str, Any]) -> dict[str, Any] | None:
    """The options document on one parameter, or `None` for a plain input.

    `None` and `{}` mean the same thing and both arrive: NULL is what db 0086
    writes for every parameter that predates it, and a dialog that saved an
    untouched panel could send the empty object.
    """
    raw = _json(parameter.get("options_from"))
    return raw if isinstance(raw, dict) and raw else None


def check_options(
    parameter: dict[str, Any],
    *,
    properties: dict[str, set[str]],
) -> dict[str, Any] | None:
    """Refuse an options document that could not produce a dropdown.

    Returns the normalised document, or `None`. `properties` is
    `{object type id: property names}` for the types this caller resolved;
    **its absence for a named type is a refusal rather than a permission**,
    which is `notifications.parse_notify`'s rule and §334's.
    """
    options = options_of(parameter)
    if options is None:
        return None
    name = str(parameter.get("api_name", ""))
    data_type = str(parameter.get("data_type", ""))

    unknown = sorted(k for k in options if k not in ("object_type_id", "property"))
    if unknown:
        raise ValueError(f"{name!r}: unknown options option {', '.join(unknown)}")

    if data_type == "object":
        # p.33's other shape, which §330 built. A parameter with both would be
        # two answers to "what may I pick" and no way to say which won.
        raise ValueError(
            f"{name!r} holds an object, so its dropdown is the object one "
            "(p.33's single object reference) — options from a property are "
            "p.33's multiple choice, which is for parameters that are not "
            "objects"
        )
    if data_type not in OPTIONABLE_TYPES:
        raise ValueError(
            f"{name!r} is a {data_type}, which cannot be offered as a list of "
            f"values; this build offers {', '.join(OPTIONABLE_TYPES)}"
        )

    type_id = str(options.get("object_type_id") or "")
    offers = properties.get(type_id)
    if offers is None:
        raise ValueError(
            f"{name!r} takes its options from an object type this workspace "
            "does not have"
        )
    prop = str(options.get("property") or "").strip()
    if not prop:
        raise ValueError(
            f"{name!r} takes its options from an object set without saying "
            "which property holds them"
        )
    if prop not in offers:
        raise ValueError(
            f"{name!r} takes its options from {prop!r}, which is not a "
            "property of the object type it names"
        )
    return {"object_type_id": type_id, "property": prop}


def set_type_of(parameter: dict[str, Any]) -> str | None:
    """Which object type this parameter's *options* are read from, or `None`.

    `action_choices.type_of`'s sibling for p.33's other shape (§336). The two
    answer the same question — "whose objects does this dropdown read" — for
    the two kinds of parameter p.33's first sentence names, and they are
    separate because a parameter is one or the other: an object parameter has
    db 0083's column and refuses an options document, and a multiple-choice
    parameter is refused the column.
    """
    declared = options_of(parameter)
    return str(declared["object_type_id"]) if declared else None


async def options(
    conn: AsyncConnection,
    parameter: dict[str, Any],
    *,
    workspace_id: UUID,
    filters: tuple[Any, ...] = (),
    definition: Any = None,
    limit: int = MAX_OPTIONS,
) -> tuple[list[str], bool]:
    """The values this parameter may be set to, and whether there were more.

    Returns `(values, truncated)`. **Truncated against the distinct total the
    store reports**, not against how many rows were read — see the module
    docstring on why that distinction is the whole design.

    `definition` is p.36-37's set, already compiled by
    `action_search_arounds.build` and already carrying `filters` on its
    outermost. It is passed *as well as* `filters` rather than instead of them
    because a parameter with no walk has no definition to build and the plain
    filters are the whole answer — which is the arrangement `action_choices`
    already uses, and the reason the two shapes cannot drift.

    Ordered alphabetically for display and truncated by *frequency*, which are
    two different orderings on purpose. `group_object_set` returns the most
    common values first, so a cap keeps the ones somebody is most likely to
    want; sorting what survives means the control does not reshuffle when the
    data shifts underneath it.
    """
    declared = options_of(parameter)
    if declared is None:
        # Returns before the connection is touched, which is what lets this be
        # asked without one — and is why it is a guard rather than a contract
        # note. Both callers check `options_of` first, so nothing reaches it in
        # this build; a `TypeError` would be a poor answer for the one that
        # eventually does not.
        return [], False
    prefix = await instances_service.workspace_search_prefix(conn, workspace_id)
    store = instance_store.store_for(conn)
    # p.33's own first sentence — "**adding filters** to non-object reference
    # multiple choice… parameters will determine the allowed values" — narrowing
    # the set before the property is read off it (§336). The same compiled
    # `Filter`s an object dropdown uses, because p.33 describes one filter
    # vocabulary over two shapes and a second one here would be free to
    # disagree.
    #
    # And p.33's "**configure the desired object set**" in full (§337): a walk
    # is how that sentence is answered for the set p.37 describes, and it
    # arrives here as the same nested `ObjectSet` an object dropdown is handed,
    # collapsed by the same resolver. "The region of the offices *this customer*
    # is served by" is not a property comparison on Office at all — it is p.37's
    # Search Around with a property read off the far end.
    if definition is not None and definition.via is not None:
        filters, empty = await object_set_eval.resolve_traversal(
            conn, store, prefix, workspace_id, definition
        )
        if empty:
            # The set below linked to nothing, so there is nothing to read a
            # property off. Reading the type unfiltered would offer every value
            # in the workspace, which is the opposite of what a walk narrowing
            # to none means — the same widening `action_choices` refuses.
            return [], False
    buckets, distinct = await store.group_object_set(
        search_prefix=prefix,
        object_type_id=UUID(str(declared["object_type_id"])),
        filters=filters,
        property_name=str(declared["property"]),
        limit=limit,
    )
    # **Not deduplicated here.** `group_object_set` is "one number per distinct
    # value of a property" — the set comprehension this line used to build was
    # a second copy of a promise the store makes, and a sweep removed it with
    # nothing failing (§213). Sorting is this module's own, for the reason
    # below.
    values = sorted(str(value) for value, _count, _metric in buckets)
    return values, distinct > len(values)


def prefill(values: list[str], *, required: bool) -> str | None:
    """p.33's automatic prefill, or `None`.

    > "If only one linked object is available in the resulting object set and
    > the parameter is required, the parameter dropdown will automatically
    > prefill with the corresponding property value." (p.33)

    **One distinct *value*, where p.33 says one object**, and the difference is
    deliberate. Two objects that share a region leave exactly one region to
    choose, so p.33's condition is met in the sense that matters: there is one
    answer and the person filling the form has no decision to make. Reading it
    as "one object" would leave that form with a single-item dropdown somebody
    has to open, which is the letter of p.33 defeating its own sentence.

    Only when the parameter is **required**, which is p.33's own qualifier and
    worth keeping: an optional parameter left blank means something, and
    filling it in for somebody would be choosing on their behalf.
    """
    if not required or len(values) != 1:
        return None
    return values[0]


def confirming(
    parameter: dict[str, Any], value: Any, *, filters: tuple[Any, ...] = (),
) -> tuple[Any, ...]:
    """`filters`, plus one asking whether *this* value is in the set (§338).

    **The difference between asking a question and reading an answer.** The
    check used to evaluate the narrowed set at `MAX_OPTIONS` and look for the
    submitted value in what came back, so "is this value allowed" depended on
    how many the *control* can hold: `group_object_set` truncates by frequency,
    and a legitimate value that happened to be the fifty-first most common was
    refused with a sentence saying it is not one of the values offered. It was
    one of them. §256's trap arriving through the back door, and the same one
    §331 shipped for the object shape and §333 removed by key.

    An equality on the property being grouped makes it a set of one bucket, so
    the page size stops deciding. **Text equality is the same comparison the
    check does**: `Filter`'s `data_type` is `None` for every equality-shaped
    operator because they compare the text of a value, and `check_option_values`
    compares `str(value)` against the text of a bucket — one rule, asked twice,
    rather than a store-side comparison free to disagree with a Python one.

    A blank value adds nothing, because there is no value to ask about; the
    caller skips the read entirely and `check_option_values` returns anyway.

    **The caller's `limit=1` is a statement, not the mechanism.** This equality
    leaves at most one bucket, so asking for one and asking for fifty return the
    same list and a sweep could not make the limit matter — worth writing down
    rather than rediscovering, because the obvious reading is that the two
    together are what removes the page size and only one of them is.
    """
    declared = options_of(parameter)
    if declared is None or value is None or value == "":
        return filters
    from . import object_sets

    return (*filters, object_sets.Filter(
        property=str(declared["property"]), op="eq", value=str(value),
    ))


def check_option_values(
    parameter: dict[str, Any], value: Any, *, allowed: list[str]
) -> None:
    """Refuse a submission that is not one of the offered values.

    **p.33 does not say this and it belongs anyway** (§214). A dropdown
    narrowed to three regions beside a check that accepts any string is a
    control that looks like it works: the form is a convenience and the rule
    has to hold for a caller that never drew one. It is the same argument p.34
    makes out loud for the object dropdown one section along, applied to the
    shape p.33 describes without repeating it.

    **`allowed` is an answer, not the offer** (§338). Its caller narrows the
    read to this one value with `confirming` and asks for one bucket, so what
    arrives is `[value]` or `[]` — "does the set contain it" rather than "here
    are fifty of them, look". The membership test is unchanged and still reads
    the same either way, which is why this function did not have to know: what
    changed is that the list it is handed is no longer truncated by frequency,
    and so no longer refuses a value for being unpopular.
    """
    if value is None or value == "":
        return
    if str(value) not in allowed:
        name = str(parameter.get("api_name", ""))
        raise ValueError(
            f"{str(value)!r} is not one of the values {name!r} offers"
        )
