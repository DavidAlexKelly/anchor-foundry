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
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from . import instance_store
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


async def options(
    conn: AsyncConnection,
    parameter: dict[str, Any],
    *,
    workspace_id: UUID,
    limit: int = MAX_OPTIONS,
) -> tuple[list[str], bool]:
    """The values this parameter may be set to, and whether there were more.

    Returns `(values, truncated)`. **Truncated against the distinct total the
    store reports**, not against how many rows were read — see the module
    docstring on why that distinction is the whole design.

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
    buckets, distinct = await instance_store.store_for(conn).group_object_set(
        search_prefix=prefix,
        object_type_id=UUID(str(declared["object_type_id"])),
        filters=(),
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
    """
    if value is None or value == "":
        return
    if str(value) not in allowed:
        name = str(parameter.get("api_name", ""))
        raise ValueError(
            f"{str(value)!r} is not one of the values {name!r} offers"
        )
