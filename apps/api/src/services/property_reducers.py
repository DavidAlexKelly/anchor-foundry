"""Property reducers (Foundry ``object-link-types`` p.131-133; db 0088).

> "A property reducer enables you to transform an array property into a single
> value in the array for display and interface implementation purposes.
> **Reduction does not change the underlying property type or property data
> stored**; instead, it provides access to the reduced value in the array when
> reading the property value." (p.131)

> "You can also configure **multiple reducers** using different struct fields
> to handle tie-breaking scenarios." (p.133)

**Marked [Beta] upstream** (p.131), recorded on the roadmap row so that a later
divergence reads as the specification moving rather than as this platform
having got it wrong.

**A reducer is a question, and this module is both the question's grammar and
its answer** - which is one module more than `derivation` needed, and on
purpose. A derived property's answer is a *query*: it walks links, so it has to
be computed where the data is (`instance_store`), and `derived_properties` can
only validate. A reducer's answer costs no query at all, because the array is
already in the row that was read - so the answer is a pure function over a list
and belongs beside the rule that admitted it, where both can be tested without
a database.

That difference is also why reduction is **not** on `_with_derived`'s path.
That function is deliberately single-reads-only, in its own words, because
"each derived property costs a query per hop, so doing this for a page of a
table would be a silent N+1 on every list in the product". p.131 wants the
reduced value "in a table", and a reducer costs one comparison over a list
already in hand, so a page of them is a page of comparisons.

**The vocabulary carries the comparison.** p.132 gives each category its own
words - highest/lowest for numbers, latest/earliest for dates, first/last for
strings, true-first/false-first for booleans - rather than one max/min pair
over everything, and that turns out not to be decoration: `latest` means *later
in time* and `last` means *later in the alphabet*, and an array of ISO
timestamps sorted as text answers the first question with the second one's
method. Because the operation says which comparison it is, `reduce` needs no
type argument at all; `parse` is what guarantees the operation and the element
type agree.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

from . import struct_fields as struct_fields_service

#: p.132's supported table, in this platform's vocabulary, with each category's
#: own operations - **the order within each pair is p.132's order**, which is
#: what an editor's dropdown should read as.
#:
#: Foundry's numeric row names seven SQL widths (Byte, Short, Integer, Long,
#: Float, Double, Decimal); this platform collapses them to `integer` and
#: `float`, the same collapse `struct_fields.FIELD_TYPES` makes and for the
#: same reason.
OPERATIONS: dict[str, tuple[str, ...]] = {
    "integer": ("highest", "lowest"),
    "float": ("highest", "lowest"),
    "date": ("latest", "earliest"),
    "timestamp": ("latest", "earliest"),
    "string": ("first", "last"),
    "boolean": ("true_first", "false_first"),
}

#: Every operation this platform knows, for the reader who has one in hand and
#: wants to know whether it is a typo or a mismatch - those are two different
#: refusals and `parse` gives each its own sentence.
ALL_OPERATIONS: tuple[str, ...] = tuple(
    op for ops in OPERATIONS.values() for op in ops
)

#: Why a base type this platform *has* cannot be reduced, in its own words.
#:
#: p.132's unsupported table names Attachment, Cipher Text, Geohash, Geoshape,
#: Geotemporal Series Reference, Marking, Media Reference, Time Dependent and
#: Vector. Three of this platform's element types land there or just outside
#: it, and each gets its own sentence rather than a shared "not supported",
#: because a reader comparing this with `array_properties.INNER_TYPES` will
#: otherwise read the gaps as an oversight:
UNREDUCIBLE = {
    "attachment": (
        "an attachment is a reference to a stored blob, so there is no order "
        "to take the highest or latest of (object-link-types p.132 lists "
        "Attachment as unsupported)"
    ),
    "geopoint": (
        "a point is two coordinates with no agreed precedence between them, "
        "so there is no single value to call highest (p.132 lists Geohash and "
        "Geoshape as unsupported)"
    ),
    "geoshape": (
        "a shape has no single value to order by - area, perimeter and extent "
        "are three different answers (p.132 lists Geoshape as unsupported, "
        "and §425 gave this platform the type the entry was waiting for)"
    ),
    "json": (
        "a json value is this platform's untyped escape hatch, so nothing "
        "declares what shape its values have or how two of them compare"
    ),
}

#: Which way each operation points. `first` is lexicographically first, so it
#: is the *minimum*; `last` the maximum. `true_first` prefers True, which is
#: the maximum of a boolean.
_TAKES_MAX = frozenset({"highest", "latest", "last", "true_first"})

_KEYS = ("operation", "field")


class ReducerError(ValueError):
    """A reducer declaration that could not be stored. Surfaced as a 422."""


def parse(
    raw: Any,
    *,
    data_type: str,
    array_of: str | None,
    struct_fields: Any,
    property_name: str,
) -> list[dict[str, Any]] | None:
    """Normalise and check one property's ``reducers``, or refuse it by name.

    Returns the stored form - an ordered list of ``{operation, field}``, with
    ``field`` ``None`` for anything but an array of structs - or ``None`` for a
    property that declares no reducer. Normalised rather than passed through
    for `value_format.parse`'s reason: what is stored has to be what was
    checked, or the two are only accidentally the same.

    **The pairing is checked in both directions**, which is `array_properties`'
    rule one column over: a non-array carrying reducers is a claim nothing
    reads, and silently dropping it would leave somebody looking at a saved
    definition that does not contain what they typed.

    Runs *after* `array_properties.parse` and `struct_fields.parse`, because
    every question here is a question about their answers - which element type,
    and which of the element's fields.
    """
    if data_type != "array":
        if _stated(raw):
            raise ReducerError(
                f"{property_name!r} is {_an(data_type)}, so it cannot have a "
                "property reducer; reduction turns an array into one of its "
                "values (object-link-types p.131)"
            )
        return None
    if not _stated(raw):
        return None
    if not isinstance(raw, list):
        raise ReducerError(
            f"{property_name!r}: reducers must be a list, in the order they "
            "break ties (p.133)"
        )

    by_field = struct_fields_service.types_by_field(struct_fields)
    if array_of != "struct":
        _check_reducible(array_of, property_name=property_name)

    out: list[dict[str, Any]] = []
    seen: set[str | None] = set()
    for index, entry in enumerate(raw):
        where = f"reducer {index + 1} of {property_name!r}"
        if not isinstance(entry, dict):
            raise ReducerError(f"{where} is not an object")
        unknown = sorted(set(entry) - set(_KEYS))
        if unknown:
            raise ReducerError(f"{where} has unknown keys: " + ", ".join(unknown))

        field = entry.get("field")
        field = str(field).strip() if field not in (None, "") else None
        if array_of == "struct":
            # p.133: "Reducers function on struct arrays based on a specific
            # field within the struct, **not the struct itself**." So the field
            # is required here, and the base type whose operations apply is the
            # field's rather than the element's.
            if field is None:
                raise ReducerError(
                    f"{where} does not say which struct field to reduce by; a "
                    "struct array reduces by a field, not by the struct (p.133)"
                )
            if field not in by_field:
                raise ReducerError(
                    f"{where} names {field!r}, which is not a field of "
                    f"{property_name!r}; it has "
                    + ", ".join(sorted(by_field))
                )
            base = by_field[field]
            _check_reducible(base, property_name=property_name, field=field)
        else:
            if field is not None:
                raise ReducerError(
                    f"{where} names the struct field {field!r}, but "
                    f"{property_name!r} is an array of {array_of}; only a "
                    "struct array reduces by a field (p.133)"
                )
            base = str(array_of)

        operation = str(entry.get("operation") or "").strip()
        if operation not in ALL_OPERATIONS:
            raise ReducerError(
                f"{where} has no operation I know; expected one of "
                + ", ".join(ALL_OPERATIONS)
            )
        if operation not in OPERATIONS[base]:
            # **A different mistake from a typo, so a different sentence.**
            # `latest` on a string array is somebody who meant `last`, and a
            # list of every operation in the platform would not tell them that.
            raise ReducerError(
                f"{where} is {operation!r}, which is not something you can do "
                f"to {_an(base)}; that one takes "
                + " or ".join(OPERATIONS[base])
            )
        if field in seen:
            # p.133's own framing: a second reducer exists "to handle
            # tie-breaking scenarios". Two elements tied on a basis are tied on
            # it for every operation, so a second reducer over the *same* basis
            # cannot break anything the first one left - and on a non-struct
            # array there is only ever one basis, the element itself. Stored,
            # it would be a declaration that provably does nothing (§213); as a
            # refusal it is the one sentence that says why.
            raise ReducerError(
                f"{where} reduces by "
                + (f"{field!r} again" if field else "the element again")
                + ", which cannot break a tie the reducer before it left: "
                "tied values are tied whichever operation asks (p.133)"
            )
        seen.add(field)
        out.append({"operation": operation, "field": field})
    return out


def reduce(value: Any, reducers: Any) -> Any:
    """The one element p.131 shows in place of the array, or ``None``.

    **An element, not a field.** p.131 says a reducer surfaces "a single value
    *in* the array", and p.133 says a struct array reduces *by* a field - so
    reducing a list of inspections by `date` answers with the whole inspection,
    not with its date. A caller that wants only the field can read it off the
    element; a caller given only the field could never get back to the rest.

    **Nothing here raises.** This runs on a read path, where a single element
    that does not parse - a value hand-written into the store, a property
    retyped after the fact - would otherwise turn one bad row into a blank
    page. An element whose basis cannot be read is *ineligible* instead: it
    cannot be the latest anything, which is also the honest answer for the case
    that actually happens, a struct element missing the field entirely.

    A reducer no element is eligible for says nothing rather than picking
    arbitrarily, so an array of structs where nobody filled the field in
    reduces to ``None`` rather than to whichever element the store returned
    first.
    """
    if not isinstance(reducers, list) or not reducers:
        return None
    if not isinstance(value, list) or not value:
        # p.116 forbids an empty array and p.86 forbids a null element, so
        # neither should be here - but "should not" is not "cannot", and the
        # rule is enforced on write while this is a read.
        return None

    candidates = list(value)
    answered = False
    for reducer in reducers:
        if not isinstance(reducer, dict):
            continue
        operation = reducer.get("operation")
        if operation not in ALL_OPERATIONS:
            continue
        field = reducer.get("field")
        keyed = [
            (key, element)
            for element in candidates
            for key in (_key(element, operation, field),)
            if key is not None
        ]
        if not keyed:
            continue
        answered = True
        best = max(k for k, _ in keyed) if operation in _TAKES_MAX else min(
            k for k, _ in keyed
        )
        candidates = [element for key, element in keyed if key == best]
        if len(candidates) == 1:
            break
    return candidates[0] if answered else None


def implements_as(prop: dict[str, Any]) -> str:
    """The base type this property presents to an interface (p.131-132).

    > "A property reducer enables you to transform an array property into a
    >  single value in the array for display and **interface implementation
    >  purposes**." (p.131)

    > "Array properties require non-array types to satisfactorily implement
    >  interface properties." (p.132)

    **The element type, because `reduce` answers with an element.** p.131's
    words are "a single value *in* the array", so reducing a list of dates
    yields a date and the property can satisfy an interface property declared
    `date`. Not the struct field's type on a struct array: reducing *by* a
    field still answers with the whole struct (p.133), which is the same
    distinction `reduce` makes and the reason this is one line rather than a
    walk through the reducer list.

    **An array with no reducer presents as `array`**, which is p.132's sentence
    doing its work rather than a fallback: there is no single value, so there
    is nothing for a non-array interface property to be satisfied by. The
    refusal `interfaces.check_implementation` writes says which of the two it
    is, because "is array" and "is an array nobody said how to reduce" send a
    reader to different places.

    Every other property answers with its own base type, so this is safe to put
    in front of *every* implementing property rather than only the arrays.

    Takes a stored property row. It used to open with an `isinstance` guard
    answering `""` for anything else, and an adversarial sweep found that
    nothing could make it fail: every caller hands over a `list_properties`
    row. A guard that cannot fail is not a guard (§213), and a `TypeError` from
    a caller that invented a new shape is the louder, more useful failure.
    """
    data_type = str(prop.get("data_type") or "")
    if data_type != "array" or not prop.get("reducers"):
        return data_type
    # **`array_of` is never absent on an array**, so there is no third branch
    # here and nothing to test for one: db 0087's pairing is checked in both
    # directions by `array_properties.parse` on every write path. An adversarial
    # sweep found the fallback this line used to carry — `or data_type` — and
    # nothing could make it fail, which is the tell (§213). A row that reached
    # the database without going through that check answers `""`, and `""` and
    # `"array"` satisfy exactly the same set of interface properties: none.
    return str(prop.get("array_of") or "")


def reduce_all(
    values: Any, by_property: dict[str, Any] | None
) -> dict[str, Any]:
    """One object's reduced values, keyed by property (p.131).

    **Beside the properties rather than in place of them.** p.131 is explicit
    that reduction "does not change the underlying property type or property
    data stored" and that "the full array remains accessible for queries and
    other operations" - and p.131 again: applications "enable you to view the
    complete array on hover or in expanded views", which is only possible if
    the array arrived as well. Substituting the reduced value in `properties`
    would make the row smaller and the hover impossible, and every writer that
    read an object back would have to know which of its fields were real.

    A property with no reduced value is **absent** rather than present as null,
    so that `name in reduced` is the question a caller actually has: an array
    of structs where nobody filled the reduced field in has no answer, and a
    null would be indistinguishable from an element whose value is null - which
    p.86 forbids, but only on the way in.
    """
    if not isinstance(values, dict) or not by_property:
        return {}
    out: dict[str, Any] = {}
    for name, reducers in by_property.items():
        reduced = reduce(values.get(name), reducers)
        if reduced is not None:
            out[name] = reduced
    return out


def _stated(value: Any) -> bool:
    """Whether the caller said anything at all.

    ``None`` and ``[]`` both mean "no reducers", and neither is a mistake worth
    a refusal on a property that could not have had any - `struct_fields`'
    rule, for the reason it gives.
    """
    return value is not None and value != []


def _check_reducible(base: Any, *, property_name: str, field: str | None = None) -> None:
    """Refuse an element - or a struct field - p.132 cannot order."""
    named = str(base or "")
    if named in OPERATIONS:
        return
    what = (
        f"the field {field!r} of {property_name!r} is {_an(named)}"
        if field
        else f"{property_name!r} is an array of {named}"
    )
    reason = UNREDUCIBLE.get(named)
    if reason is None:
        raise ReducerError(f"{what}, which has no reducer operations")
    raise ReducerError(f"{what}, which cannot be reduced: {reason}")


def _key(element: Any, operation: str, field: Any) -> Any:
    """What this reducer compares, or ``None`` when this element has none."""
    if field:
        if not isinstance(element, dict):
            return None
        element = element.get(field)
    if element is None:
        return None
    if operation in ("highest", "lowest"):
        return _number(element)
    if operation in ("latest", "earliest"):
        return _instant(element)
    if operation in ("true_first", "false_first"):
        return element if isinstance(element, bool) else None
    return str(element)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        # `True` is not the highest number; a boolean here is a retyped
        # property rather than a value, and guessing would put it above 0.
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _instant(value: Any) -> _dt.datetime | None:
    """One temporal value as a comparable instant.

    **Dates and timestamps both become datetimes**, because Python refuses to
    compare a `date` with a `datetime` and one array is allowed to hold a value
    written before its property was retyped. A date is midnight, which is what
    ordering it against a timestamp on the same day means.

    **A value with no offset is read as UTC.** Migration 0029 kept one
    timestamp type and `property_values._coerce_temporal` preserves an offset
    when the value has one and leaves it absent when it does not - so a naive
    and an aware value can both turn up in the same list, and Python refuses to
    compare those too. UTC is the assumption the rest of the platform already
    makes when it has to make one; what matters here is that the comparison is
    over *instants* rather than over text, which is the difference between
    `latest` and `last`.
    """
    if isinstance(value, _dt.datetime):
        parsed: _dt.datetime = value
    elif isinstance(value, _dt.date):
        parsed = _dt.datetime.combine(value, _dt.time.min)
    else:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            parsed = _dt.datetime.fromisoformat(text)
        except ValueError:
            try:
                parsed = _dt.datetime.combine(
                    _dt.date.fromisoformat(text), _dt.time.min
                )
            except ValueError:
                return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed


def _an(data_type: str) -> str:
    """"a struct" or "an array" - `struct_fields._an`, for its reason: the
    message is the whole point of the refusal, and "is a array" is the kind of
    thing a reader stops on."""
    return f"an {data_type}" if data_type[:1] in "aeiou" else f"a {data_type}"
