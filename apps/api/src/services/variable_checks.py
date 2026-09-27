"""Workshop's string and boolean comparisons on variables (§566;
`workshop` p.142).

    "String comparison: Is: Runs a boolean check comparing given string
     values or variables for equality. Is not … Contains: Runs a boolean
     check on if the second given string value(s) or variable(s) is a
     substring of the first given string value or variable. Does not contain
     … Starts with … a prefix of the first … Ends with … a suffix of the
     first …" (p.142)

    "Boolean comparisons: Is true: Runs a boolean check on if a given boolean
     variable is true. Is false (NOT) … Is null: Runs a boolean check on if a
     given variable is null. Is not null …" (p.142)

**The first against each of the rest**, as §564 reads p.141's "the second
given numeric value(s)": Contains is true when every one of the rest is in
the first, and Does not contain when none is. Case counts: "Paris" does not
contain "paris".

**Nothing yet**: a string comparison with an input that has no value is
none, as §564's are. The boolean checks are about exactly that, so they
answer it: nothing is null, is not true, and is not false.
"""
from __future__ import annotations

from typing import Any

_STRINGS = {
    "string_is": lambda a, b: a == b,
    "string_is_not": lambda a, b: a != b,
    "string_contains": lambda a, b: b in a,
    "string_does_not_contain": lambda a, b: b not in a,
    "string_starts_with": lambda a, b: a.startswith(b),
    "string_ends_with": lambda a, b: a.endswith(b),
}
_BOOLEANS = ("is_true", "is_false", "is_null", "is_not_null")

#: Each transform and its inputs: at least `low`, at most `high`.
ARITY: dict[str, tuple[int, int | None]] = {
    **{name: (2, None) for name in _STRINGS},
    **{name: (1, 1) for name in _BOOLEANS},
}
TRANSFORMS = tuple(ARITY)
MAX_INPUTS = 20


class CheckError(ValueError):
    """An input that is not what the check takes."""


def check(transform: str, inputs: int, config: dict[str, Any]) -> str | None:
    """Why this derivation cannot run, or None."""
    low, high = ARITY[transform]
    if inputs < low:
        return f"{transform} needs at least {low} input{'s' if low > 1 else ''}"
    if high is not None and inputs > high:
        return f"{transform} takes {high} input{'s' if high > 1 else ''}"
    if inputs > MAX_INPUTS:
        return f"{transform} takes at most {MAX_INPUTS} inputs"
    return None


def of_boolean_variable(value: Any) -> Any:
    """A boolean variable's value as a boolean. The Variables panel keeps a
    typed default as text, so "true" and "false" are what a boolean variable
    holds until something writes it; anything else is left as it is."""
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    return value


def apply(transform: str, inputs: list[Any], config: dict[str, Any], label: str) -> Any:
    """The check over its inputs' values, in order."""
    if transform in _BOOLEANS:
        value = inputs[0]
        if transform == "is_null":
            return value is None
        if transform == "is_not_null":
            return value is not None
        if value is not None and not isinstance(value, bool):
            raise CheckError(f"{label!r} checks {value!r}, which is not true or false")
        return value is (transform == "is_true")
    if any(v is None for v in inputs):
        return None
    for value in inputs:
        if not isinstance(value, str):
            raise CheckError(
                f"{label!r} compares {value!r}, which is not text - convert it with a cast first"
            )
    first, rest = inputs[0], inputs[1:]
    return all(_STRINGS[transform](first, other) for other in rest)
