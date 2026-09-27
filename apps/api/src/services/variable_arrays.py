"""Workshop's array operations and checks on variables (§567; `workshop`
p.142-143).

    "Array operations: Compose: Returns an array containing all values of the
     given arrays. Intersection: Returns an array containing only common
     values between the given arrays. Update element at: Returns an array
     with a specific element in the given array updated. A builder may
     specify the element to be updated by specifying the index representing
     the element's position within the array. Get element at: Returns a
     value corresponding to the element at a specified index within the
     given array and matching the array's type. Length: Returns a numeric
     value representing the number of elements within the given array."
     (p.142-143)

    "Array checks: Contains: Runs a boolean check for the presence of given
     values within a given array. Does not contain … Is subset of: Runs a
     boolean check on if a given array is a subset of another given array.
     Is null … Note: This transform will evaluate and display as "is empty"
     if an array variable reference is selected for the value. Is not null
     …" (p.143)

p.143's Is null and Is not null on an array are, by its own note, "is
empty" and "is not empty", which `is_empty` and `is_not_empty` already are;
they are not added twice.

**An index is a position from 0**, set on the transform as p.142 says ("a
builder may specify … the index"). One past the end gets nothing and updates
nothing, rather than failing the page.

**Values are compared as they are**: 1 and "1" are different entries, as
they are different values in the array.
"""
from __future__ import annotations

import json
from typing import Any

#: Each transform and its inputs: at least `low`, at most `high`.
ARITY: dict[str, tuple[int, int | None]] = {
    "array_compose": (1, None),
    "array_intersection": (1, None),
    "array_update_element": (2, 2),
    "array_get_element": (1, 1),
    "array_length": (1, 1),
    "array_contains": (2, None),
    "array_does_not_contain": (2, None),
    "array_is_subset_of": (2, 2),
}
TRANSFORMS = tuple(ARITY)
#: The two that take p.142-143's "specified index".
INDEXED = ("array_update_element", "array_get_element")
MAX_INPUTS = 20
MAX_INDEX = 10_000


class ArrayError(ValueError):
    """An input that is not what the operation takes."""


def check(transform: str, inputs: int, config: dict[str, Any]) -> str | None:
    """Why this derivation cannot run, or None."""
    low, high = ARITY[transform]
    if inputs < low:
        return f"{transform} needs at least {low} input{'s' if low > 1 else ''}"
    if high is not None and inputs > high:
        return f"{transform} takes {high} input{'s' if high > 1 else ''}"
    if inputs > MAX_INPUTS:
        return f"{transform} takes at most {MAX_INPUTS} inputs"
    if transform in INDEXED:
        index = config.get("index", 0)
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index <= MAX_INDEX:
            return f"{transform}'s index must be a whole number from 0 to {MAX_INDEX}"
    return None


def of_array_variable(value: Any) -> Any:
    """An array variable's value as a list. The Variables panel keeps a typed
    default as text, and an array's is its JSON; anything else is left as it
    is, to be refused as not a list."""
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return value
        if isinstance(parsed, list):
            return parsed
    return value


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ArrayError(f"{label!r} takes an array, and was given {value!r}")
    return value


def apply(transform: str, inputs: list[Any], config: dict[str, Any], label: str) -> Any:
    """The operation over its inputs' values, in order. The first input is
    the array, except for Compose and Intersection, where every input is."""
    if inputs[0] is None:
        return None
    first = _list(inputs[0], label)
    if transform == "array_length":
        return len(first)
    if transform == "array_get_element":
        index = int(config.get("index", 0))
        return first[index] if index < len(first) else None
    if transform == "array_update_element":
        index = int(config.get("index", 0))
        if index >= len(first):
            return list(first)
        return [inputs[1] if n == index else value for n, value in enumerate(first)]
    if transform in ("array_contains", "array_does_not_contain"):
        # An array given as the values to look for is each of its entries: a
        # multi-select's choices, say.
        wanted = [entry for v in inputs[1:] if v is not None
                  for entry in (v if isinstance(v, list) else [v])]
        if not wanted:
            return None
        found = [v in first for v in wanted]
        return all(found) if transform == "array_contains" else not any(found)
    if any(v is None for v in inputs[1:]):
        return None
    rest = [_list(v, label) for v in inputs[1:]]
    if transform == "array_compose":
        return [value for array in [first, *rest] for value in array]
    if transform == "array_intersection":
        out: list[Any] = []
        for value in first:
            if all(value in other for other in rest) and value not in out:
                out.append(value)
        return out
    return all(value in rest[0] for value in first)
