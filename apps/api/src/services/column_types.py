"""What a dataset column's type says a property should be (§735;
`object-link-types` p.149, p.160).

> "Struct properties are created from struct type dataset columns." (p.149)

> "Automapping allows users to map all columns automatically rather than
> manually. … If the object has already been created, users can automap all
> columns by using the Automap all feature." (p.160)

A dataset's schema is DuckDB's `DESCRIBE`, and a nested column's type is a
sentence: `STRUCT(a INTEGER, "First Name" VARCHAR)`, `VARCHAR[]`,
`STRUCT(d DATE)[]`, `MAP(VARCHAR, INTEGER)`. Until this module the suggestion
read that sentence by looking for a scalar's name anywhere in it, so a struct
holding an integer was suggested as an `integer` and a list of integers as one
too - the first type name found won. This reads the sentence instead.

**Automapping is reading the struct's members as fields.** p.160's automap
pairs each struct field with the backing column's member of the same name. A
struct here is read from one column by field name (`property_values.
_coerce_struct`), so that pairing is already how every struct is read, and
what is left for "Automap all" to do is declare a field for each member. A
member that cannot be a field is skipped with the reason, not renamed: the
field's name *is* how its value is found, so a renamed field would read
nothing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import struct_fields as struct_fields_service

#: A scalar DuckDB type's property type, by the name it contains. No name
#: here contains another, so their order is not a rule (swapping two survived
#: the sweep as equivalent); `TIME` and `INTERVAL` are strings.
_SCALARS = [
    ("BOOLEAN", "boolean"),
    ("TINYINT", "integer"), ("SMALLINT", "integer"), ("INTEGER", "integer"),
    ("BIGINT", "integer"), ("HUGEINT", "integer"),
    ("DOUBLE", "float"), ("FLOAT", "float"), ("DECIMAL", "float"),
    ("TIMESTAMP", "timestamp"), ("DATE", "date"),
    ("JSON", "json"),
]


@dataclass(frozen=True)
class Scalar:
    name: str


@dataclass(frozen=True)
class Struct:
    members: tuple[tuple[str, "Node"], ...]


@dataclass(frozen=True)
class ListOf:
    element: "Node"


@dataclass(frozen=True)
class Other:
    """A `MAP`, a `UNION`, or anything else with no property of its own."""
    name: str


Node = Scalar | Struct | ListOf | Other


def _split_top(text: str) -> list[str]:
    """`text` split at the commas outside any parentheses or quotes."""
    parts: list[str] = []
    depth, quoted, start = 0, False, 0
    i = 0
    while i < len(text):
        c = text[i]
        if quoted:
            # A doubled quote inside a name closes and reopens it, which
            # leaves the comma count the same.
            if c == '"':
                quoted = False
        elif c == '"':
            quoted = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == "," and depth == 0:
            parts.append(text[start:i])
            start = i + 1
        i += 1
    parts.append(text[start:])
    return [p.strip() for p in parts]


def _member(text: str) -> tuple[str, str]:
    """A struct member's name and type: `"First Name" VARCHAR` or `a INTEGER`."""
    if text.startswith('"'):
        i, name = 1, []
        while i < len(text):
            if text[i] == '"':
                if i + 1 < len(text) and text[i + 1] == '"':
                    name.append('"')
                    i += 2
                    continue
                break
            name.append(text[i])
            i += 1
        return "".join(name), text[i + 1:].strip()
    name, _, rest = text.partition(" ")
    return name, rest.strip()


def parse(text: str) -> Node:
    """A DuckDB type, as `DESCRIBE` writes it, read into its shape."""
    t = text.strip()
    if t.endswith("]"):
        # `X[]` and DuckDB's fixed-size `X[3]` are both a list of X; the
        # brackets that close the type are the last ones.
        return ListOf(parse(t[: t.rindex("[")]))
    upper = t.upper()
    if upper.startswith("STRUCT(") and t.endswith(")"):
        members = []
        for part in _split_top(t[len("STRUCT("):-1]):
            name, rest = _member(part)
            members.append((name, parse(rest)))
        return Struct(tuple(members))
    if upper.startswith(("MAP(", "UNION(")):
        return Other(upper.split("(", 1)[0])
    return Scalar(t)


def scalar_type(name: str) -> str:
    """A scalar DuckDB type's property type: `string` for what is not named."""
    upper = name.upper()
    for needle, prop in _SCALARS:
        if needle in upper:
            return prop
    return "string"


def _field_name_problem(name: str) -> str | None:
    if struct_fields_service._FIELD_API_RE.match(name):
        return None
    return (f"{name!r} is not a name a field can have, and a field is read "
            "from the column by its name")


def automap(node: Struct) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """p.160's Automap all: a field for each member that can be one, and each
    member that cannot, with why."""
    fields: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for name, member in node.members:
        problem = _field_name_problem(name)
        if problem is None:
            if isinstance(member, Struct):
                problem = ("structs have a depth of one and cannot be nested "
                           "(object-link-types p.149)")
            elif isinstance(member, ListOf):
                problem = "a struct field cannot be an array"
            elif isinstance(member, Other):
                problem = f"a struct field cannot hold a {member.name}"
            else:
                data_type = scalar_type(member.name)
                if data_type not in struct_fields_service.FIELD_TYPES:
                    problem = f"a struct field cannot hold {data_type}"
                else:
                    fields.append({
                        "api_name": name,
                        "display_name": name.replace("_", " ").title(),
                        "description": "",
                        "data_type": data_type,
                    })
                    continue
        skipped.append({"field": name, "reason": problem})
    return fields, skipped


def suggest(text: str) -> dict[str, Any]:
    """What a column of this type should be declared as: a property type, and
    for an array its element and for a struct its fields - plus the members
    that could not be fields.

    A struct none of whose members can be a field is `json`, which holds it
    as it is: p.149's "at least 1 field" means there is no struct to declare.
    """
    node = parse(text)
    element = node.element if isinstance(node, ListOf) else None
    target = element if element is not None else node
    out: dict[str, Any]
    if isinstance(target, Struct):
        fields, skipped = automap(target)
        if fields:
            out = {"data_type": "struct", "struct_fields": fields}
        else:
            out = {"data_type": "json"}
        out["skipped_fields"] = skipped
    elif isinstance(target, Scalar):
        out = {"data_type": scalar_type(target.name)}
    else:
        # A list of lists, a map, a union: held as it is.
        return {"data_type": "json"}
    if element is None:
        return out
    return {**out, "data_type": "array", "array_of": out["data_type"]}


def struct_column(text: str) -> Struct | None:
    """The struct a column holds, itself or as an array's element."""
    node = parse(text)
    if isinstance(node, ListOf):
        node = node.element
    return node if isinstance(node, Struct) else None

