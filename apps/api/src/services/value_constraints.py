"""Value type constraints (Foundry ``object-link-types`` p.233-234).

> "Each value type may optionally define a constraint to enforce data
> validation." (p.233)

**This module both validates a constraint and applies one**, which makes it
different from ``value_format`` (validates, never applies) and
``conditional_format`` (validates, applied in the browser). The difference is
not an inconsistency: a formatter decides how a value *looks*, so the browser
is the right place; a constraint decides whether a value is *allowed*, and that
has to be answered where the data is, by the same code every time. A second
implementation in the browser could disagree, and the disagreement would be a
row the screen accepted and the sync rejected.

It is kept apart from ``value_types`` (the CRUD service) for the reason
``property_values`` is kept apart from ``ontology``: the **worker** needs to
evaluate these during a sync, and a module that reaches for a database
connection cannot be lifted into that context.

Which of p.233's constraints are built
--------------------------------------
Everything whose base type exists here:

* **enum** - p.233's "Enum (one of)", with its case-insensitive option for
  strings;
* **range** - min/max, on numbers and on temporal types, and on a *string's
  length*, which is p.233's own reading ("For String properties, the length of
  the string is constrained");
* **regex** - string only, with p.233's "may optionally pass when matching only
  a substring";
* **uuid** - string only.

* p.234's **array** constraints (§681): **range** on its *size* ("For Array
  properties, the size of the array is constrained"), **unique** ("All
  elements of the array must be unique") and **nested** ("A value type
  constraint can be applied to the elements of the array");
* p.234's **struct** constraint, **elements**: "A mapping between a struct
  field identifier and a value type reference, where the struct field
  identifier indicates the struct component to which the referenced value
  type should be applied."

**Nested and elements both name another value type**, by id. p.234 says so
for a struct in as many words, and for an array a "value type constraint" is
one a value type already holds: naming it keeps one definition of `email`
rather than a copy inside every list of emails. p.230's propagation follows -
the referenced type's *current* version applies - so a reference is resolved
where properties are read (`resolve`), not frozen here. **What is referenced
must be a scalar value type**: an array of arrays does not exist, and a
reference to an array or struct value type would be a chain for every read to
follow.

Absent, and for a reason rather than by omission:

* **rid** - p.233's "must be a valid rid" is a Foundry resource identifier.
  This platform's resource ids are UUIDs (db 0032), so `uuid` already covers
  the only shape there is one of; a `rid` that meant "uuid" would be a second
  name for the same check.
"""
from __future__ import annotations

import json
import re
import uuid as uuid_module
from datetime import date, datetime, timezone
from typing import Any

#: p.233's base type lists, narrowed to the types this platform has.
ENUM_TYPES = ("string", "boolean", "integer", "float")
#: Numbers and temporals directly; a string's *length* (p.233).
#: And an array's *size* (p.234).
RANGE_TYPES = ("integer", "float", "date", "timestamp", "string", "array")
STRING_ONLY = ("string",)
ARRAY_ONLY = ("array",)
STRUCT_ONLY = ("struct",)
#: What a nested or elements constraint may name (§681): a scalar.
REFERENCE_TYPES = ("string", "integer", "float", "boolean", "date", "timestamp")

KINDS = ("enum", "range", "regex", "uuid", "unique", "nested", "elements")

#: A regex somebody can post is a regex the API will run on every synced row.
#: Catastrophic backtracking is a denial of service written as configuration,
#: so the pattern is length-capped and compiled once at save time - a pattern
#: that will not compile is refused where somebody can still fix it.
MAX_REGEX_LENGTH = 500
MAX_ENUM_VALUES = 500
MAX_ELEMENT_FIELDS = 100
_FIELD_RE = re.compile(r"^[a-z][a-z0-9_]{0,99}$")


class ConstraintError(ValueError):
    """A constraint that cannot be saved, named so a person can fix it."""


def parse(raw: Any, *, base_type: str) -> dict[str, Any] | None:
    """Validate one constraint against the base type it will guard.

    Returns the normalised constraint, or ``None`` for "no constraint" - which
    p.224 step 6 marks optional, and which a value type that exists only to
    carry meaning legitimately has.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConstraintError("constraint must be an object")

    kind = raw.get("kind")
    if kind not in KINDS:
        raise ConstraintError(
            f"constraint kind must be one of {', '.join(KINDS)}"
        )
    if kind == "enum":
        return _parse_enum(raw, base_type)
    if kind == "range":
        return _parse_range(raw, base_type)
    if kind == "regex":
        return _parse_regex(raw, base_type)
    if kind == "unique":
        _require_type("unique", base_type, ARRAY_ONLY)
        return {"kind": "unique"}
    if kind == "nested":
        _require_type("nested", base_type, ARRAY_ONLY)
        return {"kind": "nested", "value_type": _reference(raw.get("value_type"), "nested")}
    if kind == "elements":
        return _parse_elements(raw, base_type)
    return _parse_uuid(base_type)


def _reference(raw: Any, what: str) -> str:
    """A value type id, as text. Whether it names one this workspace has is
    `value_types`' question, since answering it needs the database."""
    try:
        return str(uuid_module.UUID(str(raw)))
    except ValueError:
        raise ConstraintError(f"a {what} constraint names a value type by id") from None


def _parse_elements(raw: dict[str, Any], base_type: str) -> dict[str, Any]:
    _require_type("elements", base_type, STRUCT_ONLY)
    fields = raw.get("fields")
    if not isinstance(fields, dict) or not fields:
        raise ConstraintError("an elements constraint maps at least one struct field to a value type")
    if len(fields) > MAX_ELEMENT_FIELDS:
        raise ConstraintError(f"an elements constraint may map at most {MAX_ELEMENT_FIELDS} fields")
    out: dict[str, str] = {}
    for field, ref in fields.items():
        if not isinstance(field, str) or not _FIELD_RE.match(field):
            raise ConstraintError(f"{field!r} is not a struct field identifier")
        out[field] = _reference(ref, "elements")
    return {"kind": "elements", "fields": out}


def references(constraint: dict[str, Any] | None) -> list[str]:
    """The value type ids a constraint names (§681), in a stable order."""
    if not constraint:
        return []
    if constraint.get("kind") == "nested":
        return [str(constraint["value_type"])]
    if constraint.get("kind") == "elements":
        return sorted(set(map(str, constraint["fields"].values())))
    return []


def resolve(
    constraint: dict[str, Any] | None, found: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    """The constraint with each reference's current rule beside it.

    `found` maps an id to `{"base_type", "constraint"}` as the value type is
    now (p.230). A reference that no longer resolves is left out, and checks
    nothing - the value type it named has gone, as a deleted value type
    unbinds a property (db 0054's `ON DELETE SET NULL`).
    """
    if not constraint or not references(constraint):
        return constraint
    if constraint["kind"] == "nested":
        held = found.get(str(constraint["value_type"]))
        return {**constraint, **({"items": held} if held else {})}
    return {**constraint, "resolved": {
        field: found[ref] for field, ref in constraint["fields"].items() if ref in found}}


def _require_type(kind: str, base_type: str, allowed: tuple[str, ...]) -> None:
    if base_type not in allowed:
        raise ConstraintError(
            f"a {kind} constraint does not apply to a {base_type} value type; "
            f"it is available on {', '.join(allowed)}"
        )


def _parse_enum(raw: dict[str, Any], base_type: str) -> dict[str, Any]:
    _require_type("enum", base_type, ENUM_TYPES)
    values = raw.get("values")
    if not isinstance(values, list) or not values:
        raise ConstraintError("an enum constraint needs at least one value")
    if len(values) > MAX_ENUM_VALUES:
        raise ConstraintError(f"an enum may list at most {MAX_ENUM_VALUES} values")
    coerced = [_coerce(v, base_type, "enum value") for v in values]
    if len(set(map(_hashable, coerced))) != len(coerced):
        raise ConstraintError("an enum lists the same value twice")
    out: dict[str, Any] = {"kind": "enum", "values": coerced}
    # p.233: "For String properties, the enum values may optionally be
    # case-sensitive or case-insensitive." Only for strings, because it means
    # nothing anywhere else - and an option that silently does nothing is
    # worse than one that is absent.
    if base_type == "string":
        out["case_sensitive"] = bool(raw.get("case_sensitive", True))
    return out


def _parse_range(raw: dict[str, Any], base_type: str) -> dict[str, Any]:
    _require_type("range", base_type, RANGE_TYPES)
    minimum = raw.get("minimum")
    maximum = raw.get("maximum")
    if minimum is None and maximum is None:
        raise ConstraintError("a range constraint needs a minimum, a maximum, or both")
    # A string's range constrains its *length* (p.233) and an array's its
    # *size* (p.234), so the bounds are integers whatever the base type is
    # called.
    bound_type = "integer" if base_type in ("string", "array") else base_type
    out: dict[str, Any] = {"kind": "range"}
    if minimum is not None:
        out["minimum"] = _coerce(minimum, bound_type, "minimum")
    if maximum is not None:
        out["maximum"] = _coerce(maximum, bound_type, "maximum")
    if "minimum" in out and "maximum" in out:
        low, high = out["minimum"], out["maximum"]
        if _comparable(low, bound_type) > _comparable(high, bound_type):
            raise ConstraintError(
                f"the range minimum ({minimum}) is above its maximum ({maximum}), "
                "so nothing could satisfy it"
            )
    if base_type in ("string", "array") and out.get("minimum", 0) < 0:
        raise ConstraintError(
            "a string length cannot be negative" if base_type == "string"
            else "an array size cannot be negative")
    return out


def _parse_regex(raw: dict[str, Any], base_type: str) -> dict[str, Any]:
    _require_type("regex", base_type, STRING_ONLY)
    pattern = raw.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        raise ConstraintError("a regex constraint needs a pattern")
    if len(pattern) > MAX_REGEX_LENGTH:
        raise ConstraintError(
            f"a regex pattern may be at most {MAX_REGEX_LENGTH} characters"
        )
    try:
        re.compile(pattern)
    except re.error as exc:
        # The library's message names the position, which is the only useful
        # thing to say about a broken pattern.
        raise ConstraintError(f"that regex does not compile: {exc}") from exc
    return {
        "kind": "regex",
        "pattern": pattern,
        # p.233: "The regex validation may optionally pass when matching only a
        # substring of the property value." Default false - anchored matching
        # is what somebody writing `^[a-z]+@example\.com$` expects, and a
        # default that silently accepted `nonsense a@example.com nonsense`
        # would make the constraint look like it was working.
        "substring": bool(raw.get("substring", False)),
    }


def _parse_uuid(base_type: str) -> dict[str, Any]:
    _require_type("uuid", base_type, STRING_ONLY)
    return {"kind": "uuid"}


def _hashable(value: Any) -> Any:
    return value if not isinstance(value, list) else tuple(value)


def _coerce(value: Any, base_type: str, what: str) -> Any:
    """One literal, as the base type wants it, or a refusal naming the field."""
    if base_type == "boolean":
        if not isinstance(value, bool):
            raise ConstraintError(f"{what} must be true or false")
        return value
    if base_type == "integer":
        # `bool` is an `int` in Python and would sail through untouched, which
        # would put `true` in an integer enum.
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConstraintError(f"{what} must be a whole number")
        return value
    if base_type == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConstraintError(f"{what} must be a number")
        return float(value)
    if base_type in ("date", "timestamp"):
        if not isinstance(value, str) or _temporal(value, base_type) is None:
            raise ConstraintError(
                f"{what} must be an ISO 8601 "
                + ("date (2026-01-31)" if base_type == "date" else "timestamp")
            )
        return value
    if not isinstance(value, str):
        raise ConstraintError(f"{what} must be text")
    return value


def _temporal(value: str, base_type: str) -> date | datetime | None:
    try:
        if base_type == "date":
            return date.fromisoformat(value[:10])
        # `Z` is legal ISO 8601 and not something `fromisoformat` accepted
        # before 3.11; normalised so a stored `...Z` bound behaves the same on
        # every interpreter this runs on.
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _comparable(value: Any, base_type: str) -> Any:
    if base_type in ("date", "timestamp"):
        parsed = _temporal(str(value), base_type)
        if parsed is None:
            raise ConstraintError(f"{value!r} is not a valid {base_type}")
        # A naive and an aware datetime cannot be compared at all, and a bound
        # of each kind is an ordinary thing for somebody to write - so
        # everything is normalised to UTC and compared naive.
        #
        # **Converted, not stripped.** Dropping the offset would make
        # `2026-01-01T05:00+06:00` sort as 05:00 when the instant it names is
        # 23:00 the previous day - so a range would accept and reject the wrong
        # rows for every value that carries an offset, silently. A naive value
        # is read as UTC, which is the only assumption available and the one
        # every other timestamp in this platform already makes.
        if isinstance(parsed, datetime) and parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    return value


# ---- applying one (p.227's indexing failure, p.222's "enforce data validation")
def violation(
    constraint: dict[str, Any] | None,
    base_type: str,
    value: Any,
) -> str | None:
    """Why `value` fails `constraint`, as a sentence, or None if it passes.

    **Absent is not a violation.** p.222 describes a constraint as validating
    what a value *is*, and "there is no value" is what `required` is for
    (p.116) - two rules, deliberately separate, so that an optional email
    property does not become compulsory by acquiring an email value type.
    """
    if constraint is None:
        return None
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    kind = constraint["kind"]
    if kind == "enum":
        return _enum_violation(constraint, value)
    if kind == "range":
        return _range_violation(constraint, base_type, value)
    if kind == "regex":
        return _regex_violation(constraint, value)
    if kind == "unique":
        return _unique_violation(value)
    if kind == "nested":
        return _nested_violation(constraint, value)
    if kind == "elements":
        return _elements_violation(constraint, value)
    return _uuid_violation(value)


def _unique_violation(value: Any) -> str | None:
    if not isinstance(value, list):
        return f"{value!r} is not a list"
    seen: set[str] = set()
    for item in value:
        # By JSON text, so `1` and `1.0` differ as a dataset writes them and a
        # struct item compares by its contents.
        key = json.dumps(item, sort_keys=True)
        if key in seen:
            return f"{item!r} appears more than once"
        seen.add(key)
    return None


def _nested_violation(constraint: dict[str, Any], value: Any) -> str | None:
    held = constraint.get("items")
    if held is None:
        return None
    if not isinstance(value, list):
        return f"{value!r} is not a list"
    for index, item in enumerate(value):
        why = violation(held["constraint"], held["base_type"], item)
        if why is not None:
            return f"item {index + 1}: {why}"
    return None


def _elements_violation(constraint: dict[str, Any], value: Any) -> str | None:
    if not isinstance(value, dict):
        return f"{value!r} is not a struct"
    for field, held in sorted((constraint.get("resolved") or {}).items()):
        why = violation(held["constraint"], held["base_type"], value.get(field))
        if why is not None:
            return f"{field}: {why}"
    return None


def _enum_violation(constraint: dict[str, Any], value: Any) -> str | None:
    values = constraint["values"]
    if constraint.get("case_sensitive") is False and isinstance(value, str):
        folded = {str(v).casefold() for v in values}
        if value.casefold() in folded:
            return None
    elif value in values:
        # `1 == True` in Python, so an integer enum could accept a boolean
        # through this branch. The types are pinned at parse time, but a value
        # arriving from a dataset is not, so the check is made explicit.
        if isinstance(value, bool) == any(isinstance(v, bool) for v in values):
            return None
    shown = ", ".join(str(v) for v in values[:5])
    if len(values) > 5:
        shown += f", … ({len(values)} in all)"
    return f"{value!r} is not one of {shown}"


def _range_violation(
    constraint: dict[str, Any], base_type: str, value: Any
) -> str | None:
    if base_type == "string":
        if not isinstance(value, str):
            return f"{value!r} is not text"
        subject: Any = len(value)
        unit = " characters"
    elif base_type == "array":
        if not isinstance(value, list):
            return f"{value!r} is not a list"
        subject = len(value)
        unit = " items"
    else:
        subject = value
        unit = ""
        if base_type in ("integer", "float"):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return f"{value!r} is not a number"
        elif _temporal(str(value), base_type) is None:
            return f"{value!r} is not a valid {base_type}"

    bound_type = "integer" if base_type in ("string", "array") else base_type
    here = _comparable(subject, bound_type)
    if "minimum" in constraint:
        low = _comparable(constraint["minimum"], bound_type)
        if here < low:
            return f"{subject}{unit} is below the minimum of {constraint['minimum']}"
    if "maximum" in constraint:
        high = _comparable(constraint["maximum"], bound_type)
        if here > high:
            return f"{subject}{unit} is above the maximum of {constraint['maximum']}"
    return None


def _regex_violation(constraint: dict[str, Any], value: Any) -> str | None:
    if not isinstance(value, str):
        return f"{value!r} is not text"
    pattern = re.compile(constraint["pattern"])
    hit = pattern.search(value) if constraint.get("substring") else pattern.fullmatch(value)
    if hit:
        return None
    return f"{value!r} does not match {constraint['pattern']}"


def _uuid_violation(value: Any) -> str | None:
    if not isinstance(value, str):
        return f"{value!r} is not text"
    try:
        uuid_module.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return f"{value!r} is not a UUID"
    return None


def describe(
    constraint: dict[str, Any] | None, names: dict[str, str] | None = None
) -> str:
    """One line a person can read, for a listing that has no room for the
    shape. Deliberately not a re-serialisation: `^[A-Z]{2}$` is what the author
    wrote, and showing it back is more use than "a regex constraint"."""
    if constraint is None:
        return "no constraint"
    kind = constraint["kind"]
    if kind == "enum":
        values = constraint["values"]
        shown = ", ".join(str(v) for v in values[:4])
        if len(values) > 4:
            shown += f", … ({len(values)})"
        insensitive = constraint.get("case_sensitive") is False
        return f"one of {shown}" + (" (any case)" if insensitive else "")
    if kind == "range":
        low = constraint.get("minimum")
        high = constraint.get("maximum")
        if low is not None and high is not None:
            return f"between {low} and {high}"
        return f"at least {low}" if low is not None else f"at most {high}"
    if kind == "regex":
        return f"matches {constraint['pattern']}" + (
            " (anywhere)" if constraint.get("substring") else ""
        )
    if kind == "unique":
        return "no item twice"
    known = names or {}
    if kind == "nested":
        ref = str(constraint["value_type"])
        return f"each item is {known.get(ref, 'a deleted value type')}"
    if kind == "elements":
        return ", ".join(
            f"{field} is {known.get(str(ref), 'a deleted value type')}"
            for field, ref in sorted(constraint["fields"].items()))
    return "a UUID"
