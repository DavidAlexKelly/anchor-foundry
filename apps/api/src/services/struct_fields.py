"""The declared fields of a struct property (Foundry ``object-link-types``
p.149-150; db 0064).

> "A struct is an Ontology property base type that allows users to create
> schema-based properties with multiple fields." (p.149)

**The schema is the whole difference between a struct and a `json`.** This
platform has accepted a composite value in a property since 0003 - `json` is
the escape hatch, "deliberately unconstrained" in `property_values`' own words -
so a struct is not a new *value*, it is a new *claim about* a value. Everything
here exists to make that claim checkable: what fields there are, what each one
holds, and what a value must look like to satisfy it.

**This module validates a declaration; it does not coerce a value.** Coercing
lives in ``property_values``, because the sync path and the action path both
write struct values and that module is the one mirrored into the worker. The
split is the same one ``value_format`` makes for the same reason: a rule
enforced on one write path and not the other is not a rule.

p.149 states four constraints, and all four are refusals rather than
conventions:

* **depth of one** - "Structs have a depth of one and cannot be nested", so a
  field may not itself be a struct;
* **at least one field** - a struct with none is a `json` property with a more
  specific name;
* a fixed list of **field types**, narrower than this platform's property
  types (see ``FIELD_TYPES``);
* fields are ordered and named, and a name is unique within its struct.
"""
from __future__ import annotations

import re
from typing import Any

#: The same shape a property api_name has (`0003`), and deliberately the same
#: rule rather than a looser one: a field name is read the way a property name
#: is - typed into a transform, pasted out of an error - and two naming
#: conventions one level apart is a thing to get wrong rather than a freedom.
_FIELD_API_RE = re.compile(r"^[a-z][a-z0-9_]{0,99}$")

#: p.149's list, in this platform's vocabulary. Foundry names twelve SQL types
#: (BOOLEAN, BYTE, DATE, DECIMAL, DOUBLE, FLOAT, GEOPOINT, INTEGER, LONG,
#: SHORT, STRING, TIMESTAMP); this platform's property types collapse the four
#: integer widths to `integer` and the three float widths to `float`, which is
#: the same collapse `_DUCK_TO_PROPERTY` already makes when reading a dataset.
#:
#: **What is absent is absent for a reason, one reason each**, because a reader
#: comparing this list with ``PROPERTY_TYPES`` will otherwise read the gaps as
#: an oversight:
#:
#: * `struct` - p.149's own sentence. Nesting is refused, and refused with its
#:   own message rather than as an unknown type, because somebody who has read
#:   p.58's address example will try it.
#: * `json` - it is the untyped escape hatch, so a field holding one would be
#:   nesting with the type system switched off: the value could contain
#:   anything, including another struct, and nothing would say so.
#: * `attachment` - an attachment is a reference to a stored blob, and the
#:   upload path (`POST /attachments`, §39) hands back a reference for *a
#:   property*. Making one addressable inside a struct means a second answer to
#:   "which property does this file belong to", which is a storage question and
#:   not a schema one.
#: * `time_series` - its points live where `object_type_series` says, and that
#:   row names a `property_api_name`. A series inside a struct would need that
#:   table to grow a second identity for its target, which is the thing 0047's
#:   own comment declines to introduce.
FIELD_TYPES = (
    "boolean", "date", "float", "geopoint", "integer", "string", "timestamp",
)

_FIELD_KEYS = ("api_name", "display_name", "description", "data_type")


class StructFieldError(ValueError):
    """A struct declaration that could not be stored."""


def parse(value: Any, *, data_type: str, property_name: str) -> list[dict[str, Any]] | None:
    """Normalise and check one property's ``struct_fields``.

    Returns the stored form - an ordered list of
    ``{api_name, display_name, description, data_type}`` - or ``None`` for a
    property that is not a struct. Normalised rather than passed through for
    ``value_format.parse``'s reason: what is stored has to be what was checked,
    or the two are only accidentally the same.

    **A non-struct property carrying fields is refused, not ignored.** A schema
    on a `string` property is a claim nothing reads, and silently dropping it
    would leave somebody looking at a saved definition that does not contain
    what they typed.
    """
    if data_type != "struct":
        if _stated(value):
            raise StructFieldError(
                f"{property_name!r} is a {data_type} and cannot have struct fields"
            )
        return None
    if not isinstance(value, list) or not value:
        # p.149: "Structs must have at least 1 field."
        raise StructFieldError(
            f"struct property {property_name!r} needs at least one field"
        )

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise StructFieldError(
                f"field {index + 1} of {property_name!r} is not an object"
            )
        unknown = sorted(set(raw) - set(_FIELD_KEYS))
        if unknown:
            raise StructFieldError(
                f"field {index + 1} of {property_name!r} has unknown keys: "
                + ", ".join(unknown)
            )
        api = str(raw.get("api_name") or "")
        if not _FIELD_API_RE.match(api):
            raise StructFieldError(
                f"invalid struct field name {api!r} on {property_name!r}"
            )
        if api in seen:
            raise StructFieldError(
                f"duplicate struct field {api!r} on {property_name!r}"
            )
        seen.add(api)
        field_type = str(raw.get("data_type") or "")
        if field_type == "struct":
            # **Its own message, not "unknown type".** p.149 says structs
            # "have a depth of one and cannot be nested", and this platform
            # refusing it as a typo would read as the spec being wrong rather
            # than as the refusal it is.
            raise StructFieldError(
                f"struct field {api!r} on {property_name!r} cannot itself be a "
                "struct: structs have a depth of one and cannot be nested "
                "(object-link-types p.149)"
            )
        if field_type not in FIELD_TYPES:
            raise StructFieldError(
                f"struct field {api!r} on {property_name!r} has type "
                f"{field_type!r}; expected one of " + ", ".join(FIELD_TYPES)
            )
        out.append(
            {
                "api_name": api,
                "display_name": str(raw.get("display_name") or api),
                "description": str(raw.get("description") or ""),
                "data_type": field_type,
            }
        )
    return out


def _stated(value: Any) -> bool:
    """Whether the caller said anything at all.

    ``None`` and ``[]`` both mean "no fields", and neither is a mistake worth a
    refusal on a property that could not have had any.
    """
    return value is not None and value != []


def types_by_field(fields: Any) -> dict[str, str]:
    """``{field name: data type}`` for a stored declaration.

    The form every reader actually wants - coercion, rendering, the Workshop
    extract transform - built here rather than in each of them, so a stored
    declaration that has been hand-edited into a shape nobody planned for
    produces an empty mapping in one place instead of a different exception in
    three.
    """
    if not isinstance(fields, list):
        return {}
    out: dict[str, str] = {}
    for field in fields:
        if not isinstance(field, dict):
            continue
        api = field.get("api_name")
        data_type = field.get("data_type")
        if isinstance(api, str) and isinstance(data_type, str):
            out[api] = data_type
    return out
