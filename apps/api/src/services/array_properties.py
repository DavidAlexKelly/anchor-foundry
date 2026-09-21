"""An array property's element type (`object-link-types` p.86, p.116; db 0087).

> "Array — valid as title key: Yes. Valid as primary key: No. **Array
>  properties cannot contain null elements.** If the inner type of the Array is
>  not a valid title property, the Array property also cannot be used as the
>  title property." (p.86)

> "**Array properties cannot be empty**: Setting an array property to required
>  ensures the presence of at least one item." (p.116)

**An array is the first property type whose label does not name its type.**
`integer` says everything there is to know about what an `integer` property
holds; `array` says nothing at all until it says of what. So the declaration
carries a second field, which is the shape db 0064 gave `struct` for the same
reason — and this module is `struct_fields`' counterpart: it validates a
*declaration* and never coerces a value. Coercing lives in `property_values`,
because the sync path and the action path both write and a rule enforced on one
is not a rule.

**Three of p.86's four sentences land here and the fourth has nothing to land
on.** The null rule and the emptiness rule are `property_values`'; the element
type is this module's; and the title rule is *not implemented*, deliberately.
p.86 makes an array's title validity derive from its element type's — but this
platform has no table of which types may be a title at all, so any property may
be one today. Implementing the derived rule alone would be a single special
case standing on a general rule that does not exist, which is a worse state
than the gap. It is named on the roadmap row instead.

p.86's primary-key column has no surface here either: a primary key in this
platform is a *dataset column* (`object_type_sources.primary_key_column`), not
a property, so "this property may not be the primary key" is not a sentence
this schema can say.
"""
from __future__ import annotations

from typing import Any

#: What an array may hold. Foundry's own scope is "arrays of any base type
#: except Vector and Time series"; this platform has no `Vector` (out of scope
#: unless semantic search is), so two are excluded and each has its own reason —
#: stated separately, because a reader comparing this with `PROPERTY_TYPES` will
#: otherwise read the gaps as an oversight:
#:
#: * `array` — Foundry's list does not include arrays, and nesting would make
#:   `array_of` a recursive declaration that one column cannot hold. Refused
#:   with its own message rather than as an unknown type, because it is the
#:   first thing somebody tries.
#: * `time_series` — a time series property's value is already a *pointer to a
#:   table* (decision 0009, db 0047): the scalar stored on the instance is a
#:   series id and `object_type_series` says where the points are. A list of
#:   series ids is not something p.127 describes, and the one thing it could
#:   plausibly mean — several series on one object — is a different feature
#:   with a different table.
#:
#: Everything else is allowed, `struct` included: p.140 names "Struct Array"
#: in as many words, and `struct_fields` already describes the *element* rather
#: than the property, so an array of structs needs nothing new to say.
INNER_TYPES = frozenset({
    "string", "integer", "float", "boolean", "date", "timestamp", "geopoint",
    "json", "attachment", "struct",
    # **`geoshape` is allowed** (§425), which p.127 settles in one clause:
    # "All base types may be used in arrays... excluding the Vector and Time
    # series types." An array of shapes is an ordinary thing — a route's legs,
    # a district's parcels — and it is *not* in tension with p.132 listing
    # Geoshape among the types a reducer cannot take: an array may hold them,
    # and there is simply no single one of them to call highest.
    "geoshape",
})


def parse(
    array_of: Any, *, data_type: str, property_name: str
) -> str | None:
    """The element type of one property, normalised, or `None`.

    **The pairing is checked in both directions**, because each is a different
    mistake with a different fix: an array with no element type is a
    declaration that says nothing, and an element type on a `string` is a claim
    nothing reads — the same "a type on a string is a claim nothing reads"
    argument db 0083 makes about an object parameter's type.
    """
    if data_type != "array":
        if array_of not in (None, ""):
            raise ValueError(
                f"{property_name!r} is a {data_type}, so it cannot say what it "
                "is an array of; only an `array` property has an element type"
            )
        return None

    named = str(array_of or "").strip()
    if not named:
        raise ValueError(
            f"{property_name!r} is an array and does not say what of; an array "
            "property needs an element type (object-link-types p.86)"
        )
    if named == "array":
        raise ValueError(
            f"{property_name!r} is an array of arrays, which this platform "
            "does not have: an element type is a base type, and Foundry's own "
            "scope is arrays of base types (p.86)"
        )
    if named not in INNER_TYPES:
        raise ValueError(
            f"{property_name!r} cannot be an array of {named!r}; an array holds "
            "one of " + ", ".join(sorted(INNER_TYPES))
        )
    return named
