"""Workshop's math operations and numeric comparisons on variables (§564;
`workshop` p.140-141).

    "Math operations: Add: Returns the sum of given numeric values or
     variables. Subtract … Multiply … Divide … Absolute … Negate … Round Up
     (Ceil): Returns the rounded up value to a specified precision … Round
     Down (Floor) … Round Nearest … Max: Returns the maximum value from a
     collection of numeric, date, or timestamp values or variables. Min …"
     (p.140)

    "Numeric comparisons: Equal to … Not equal to … Less than: Runs a boolean
     check on if the first given numeric value or variable is less than the
     second given numeric value(s) or variable(s). …" (p.141)

Each is a variable transformation over other variables, evaluated with the
rest in `workshop_variables.evaluate`. A constant is a static number variable,
as it is everywhere else a derivation reads one.

**Nothing yet is nothing**: an input that has no value makes the result none,
as `object_property` does for a property not set. A comparison with nothing
to compare is not false - `if_else` reads none as false anyway, and a
boolean shown in a widget should say it does not know rather than "no".
Max and Min are the exception, being over "a collection": a gap in one is
left out, as SQL's `max` leaves out a null.

**Something that is not a number is refused**, saying which variable, rather
than coerced: a text box's "12" is `cast`'s to convert (p.138), and reading
"12a" as nothing would look like an empty input. The one text read as a
number is a number variable's own (`of_number_variable`).
"""
from __future__ import annotations

import math
from datetime import date, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Any

#: p.140's math operations and p.141's numeric comparisons, with the inputs
#: each takes: at least `low`, at most `high` (None for any number).
ARITY: dict[str, tuple[int, int | None]] = {
    "add": (1, None),
    "subtract": (2, None),
    "multiply": (1, None),
    "divide": (2, 2),
    "absolute": (1, 1),
    "negate": (1, 1),
    "round_up": (1, 1),
    "round_down": (1, 1),
    "round_nearest": (1, 1),
    "max": (1, None),
    "min": (1, None),
    # p.141: "the first given numeric value … the second given numeric
    # value(s)": the first against each of the rest.
    "equal_to": (2, None),
    "not_equal_to": (2, None),
    "less_than": (2, None),
    "less_or_equal": (2, None),
    "greater_than": (2, None),
    "greater_or_equal": (2, None),
}
TRANSFORMS = tuple(ARITY)
#: Ours: more inputs than this is a document nobody built by hand.
MAX_INPUTS = 20
#: p.140's "specified precision", in decimal places either side of the point.
MAX_PRECISION = 10

_ROUNDING = {"round_up": ROUND_CEILING, "round_down": ROUND_FLOOR, "round_nearest": ROUND_HALF_UP}
_COMPARE = {
    "equal_to": lambda a, b: a == b,
    "not_equal_to": lambda a, b: a != b,
    "less_than": lambda a, b: a < b,
    "less_or_equal": lambda a, b: a <= b,
    "greater_than": lambda a, b: a > b,
    "greater_or_equal": lambda a, b: a >= b,
}


class MathError(ValueError):
    """An input that is not what the operation takes."""


def check(transform: str, inputs: int, config: dict[str, Any]) -> str | None:
    """Why this derivation cannot run, or None: a save-time check, for the
    reason `_check_arity` gives."""
    low, high = ARITY[transform]
    if inputs < low:
        return f"{transform} needs at least {low} input{'s' if low > 1 else ''}"
    if high is not None and inputs > high:
        return f"{transform} takes {high} input{'s' if high > 1 else ''}"
    if inputs > MAX_INPUTS:
        return f"{transform} takes at most {MAX_INPUTS} inputs"
    if transform in _ROUNDING:
        precision = config.get("precision", 0)
        if (isinstance(precision, bool) or not isinstance(precision, int)
                or abs(precision) > MAX_PRECISION):
            return (f"{transform}'s precision must be a whole number of decimal places "
                    f"from -{MAX_PRECISION} to {MAX_PRECISION}")
    return None


def of_number_variable(value: Any) -> Any:
    """A number variable's value as a number. The Variables panel keeps a
    default as the text typed, so "1." can be typed on the way to "1.5"; for
    a variable declared a number that text is the number it spells. Anything
    else is left as it is, to be refused as not a number."""
    if isinstance(value, str):
        try:
            n = float(value.strip())
        except ValueError:
            return value
        if math.isfinite(n):
            return _whole(n)
    return value


def _number(value: Any, label: str) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MathError(
            f"{label!r} does arithmetic on {value!r}, which is not a number - convert it "
            "with a cast first"
        )
    return value


def _whole(n: float) -> float | int:
    """An integral float as an int, so 2 + 3 is 5 rather than 5.0 in a label."""
    return int(n) if isinstance(n, float) and n.is_integer() and abs(n) < 2**53 else n


def _instant(value: Any) -> datetime | date | None:
    if isinstance(value, (datetime, date)):
        return value
    if not isinstance(value, str):
        return None
    try:
        if len(value) == 10:
            return date.fromisoformat(value)
        # A trailing Z is read by `fromisoformat` itself (a replace of it
        # survived the sweep as equivalent).
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment


def _extreme(values: list[Any], label: str, pick: Any) -> Any:
    """p.140's Max and Min: over numbers, or over dates or timestamps, which
    are compared as instants and returned as given."""
    present = [v for v in values if v is not None]
    if not present:
        return None
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in present):
        return pick(present)
    instants = [_instant(v) for v in present]
    if all(isinstance(i, datetime) for i in instants) or all(
            isinstance(i, date) and not isinstance(i, datetime) for i in instants):
        try:
            chosen = pick(range(len(present)), key=lambda n: instants[n])
        except TypeError:
            # A timestamp with a zone beside one without has no order.
            raise MathError(f"{label!r} compares timestamps with and without a time zone") from None
        return present[chosen]
    raise MathError(
        f"{label!r} takes the {'largest' if pick is max else 'smallest'} of numbers, "
        "dates or timestamps, one kind at a time"
    )


def apply(transform: str, inputs: list[Any], config: dict[str, Any], label: str) -> Any:
    """The operation over its inputs' values, in order."""
    if transform in ("max", "min"):
        return _extreme(inputs, label, max if transform == "max" else min)
    if any(v is None for v in inputs):
        return None
    numbers = [_number(v, label) for v in inputs]
    first, rest = numbers[0], numbers[1:]
    if transform in _COMPARE:
        return all(_COMPARE[transform](first, other) for other in rest)
    if transform == "add":
        # Python's own `sum` compensates for what a float drops, as `fsum`
        # does (a choice between them survived the sweep as equivalent).
        result: float | int = sum(numbers)
    elif transform == "subtract":
        result = first - sum(rest)
    elif transform == "multiply":
        result = math.prod(numbers)
    elif transform == "divide":
        # Nothing rather than infinity: a card showing "∞" is a figure somebody
        # acts on (§411's rule for column math).
        if rest[0] == 0:
            return None
        result = first / rest[0]
    elif transform == "absolute":
        result = abs(first)
    elif transform == "negate":
        result = -first
    else:
        # Decimal, so 2.675 to two places is 2.68 as written rather than the
        # 2.67 its binary float rounds to.
        places = int(config.get("precision", 0))
        step = Decimal(1).scaleb(-places)
        result = float(Decimal(repr(first)).quantize(step, rounding=_ROUNDING[transform]))
    if isinstance(result, float) and not math.isfinite(result):
        return None
    return _whole(result)
