"""Workshop's date and time math and comparisons on variables (§565;
`workshop` p.140-141).

    "Date/time math: Relative date: Returns a calculated date given a numeric
     value or variable, specifying the number of days, weeks, months or years
     to add or subtract, and a date value or variable. Relative time: … the
     number of seconds, minutes, hours, days, weeks, months or years to add
     or subtract, and a time value or variable. Between dates: Returns the
     numeric difference between two given date values or variables. The
     returned difference can be calculated in days, weeks, months, or years.
     Between times: … in seconds, minutes, hours, days, weeks, months, or
     years. Current date: Returns the current date." (p.140)

    "Date comparisons: Is on or after … Is after … Is on or before … Is
     before … Is equal … Time comparisons: [the same five]" (p.140-141)

**A date is a day and a time is an instant.** A date is `YYYY-MM-DD`, the
form a date variable holds; a time is an ISO timestamp, and one that names no
zone is read as UTC, which is how every timestamp here is drawn. A date given
where a time is wanted, or the other way, is refused rather than guessed at:
midnight in which zone?

**Months and years are the calendar's**: a month after 31 January is the last
day of February, and a difference counts whole months as java.time does, a
month once the day of the month comes round again. A difference is the
second minus the first, in whole units, truncated toward zero.

**Nothing yet is nothing**, as for §564's math: an input with no value makes
the result none.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
from typing import Any

#: The units each kind of value is counted in.
DATE_UNITS = ("days", "weeks", "months", "years")
TIME_UNITS = ("seconds", "minutes", "hours", "days", "weeks", "months", "years")
_SECONDS = {"seconds": 1, "minutes": 60, "hours": 3600, "days": 86400, "weeks": 604800}

_COMPARE = {
    "is_on_or_after": lambda a, b: a >= b,
    "is_after": lambda a, b: a > b,
    "is_on_or_before": lambda a, b: a <= b,
    "is_before": lambda a, b: a < b,
    "is_equal": lambda a, b: a == b,
}

#: Every transform here and its inputs: exactly this many.
ARITY: dict[str, int] = {
    "relative_date": 2,
    "relative_time": 2,
    "between_dates": 2,
    "between_times": 2,
    "current_date": 0,
    **{f"date_{name}": 2 for name in _COMPARE},
    **{f"time_{name}": 2 for name in _COMPARE},
}
TRANSFORMS = tuple(ARITY)
DIRECTIONS = ("add", "subtract")


class DateError(ValueError):
    """An input that is not what the operation takes."""


def _units_for(transform: str) -> tuple[str, ...] | None:
    if transform in ("relative_date", "between_dates"):
        return DATE_UNITS
    if transform in ("relative_time", "between_times"):
        return TIME_UNITS
    return None


def check(transform: str, inputs: int, config: dict[str, Any]) -> str | None:
    """Why this derivation cannot run, or None."""
    wanted = ARITY[transform]
    if inputs != wanted:
        return f"{transform} takes {wanted} input{'' if wanted == 1 else 's'}"
    units = _units_for(transform)
    if units is not None and config.get("unit", "days") not in units:
        return f"{transform}'s unit must be one of {', '.join(units)}"
    if transform in ("relative_date", "relative_time") and \
            config.get("direction", "add") not in DIRECTIONS:
        return f"{transform}'s direction must be add or subtract"
    return None


def _date(value: Any, label: str) -> date:
    if isinstance(value, str) and len(value) == 10:
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise DateError(f"{label!r} takes a date, as YYYY-MM-DD, and was given {value!r}")


def _time(value: Any, label: str) -> datetime:
    if isinstance(value, str) and len(value) > 10:
        try:
            moment = datetime.fromisoformat(value)
        except ValueError:
            pass
        else:
            return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    raise DateError(f"{label!r} takes a timestamp, and was given {value!r}")


def _amount(value: Any, label: str, unit: str, *, whole: bool) -> float | int:
    """How far to move. A date moves by whole units, and so does a time by
    months or years: a calendar has no half month."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DateError(f"{label!r} moves by {value!r}, which is not a number")
    if (whole or unit in ("months", "years")) and not float(value).is_integer():
        raise DateError(f"{label!r} moves by {value} {unit}, and only whole {unit} can be counted")
    return value


def _plus_months(day: date, months: int) -> date:
    """`months` calendar months on: the same day of the month, or the last
    day of a shorter month."""
    index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    return day.replace(year=year, month=month,
                       day=min(day.day, calendar.monthrange(year, month)[1]))


def _whole_months(start: date, end: date, start_rest: timedelta = timedelta(),
                  end_rest: timedelta = timedelta()) -> int:
    """Whole calendar months from `start` to `end`, truncated toward zero.
    The rests are the times of day, for two instants."""
    if (end, end_rest) < (start, start_rest):
        return -_whole_months(end, start, end_rest, start_rest)
    months = (end.year - start.year) * 12 + (end.month - start.month)
    # A month is counted once the end's day of the month (and time of day)
    # reaches the start's, as java.time counts it: 31 January to 28 February
    # is no whole month, though 31 January plus a month is 28 February.
    if (end.day, end_rest) < (start.day, start_rest):
        months -= 1
    return months


def _utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def apply(transform: str, inputs: list[Any], config: dict[str, Any], label: str,
          *, today: date | None = None) -> Any:
    """The operation over its inputs' values, in order. `today` is the date
    Current date answers with, UTC's unless a caller says otherwise."""
    if transform == "current_date":
        return (today or datetime.now(timezone.utc).date()).isoformat()
    if any(v is None for v in inputs):
        return None
    unit = str(config.get("unit", "days"))
    if transform in ("relative_date", "relative_time"):
        sign = -1 if config.get("direction", "add") == "subtract" else 1
        amount = _amount(inputs[1], label, unit, whole=transform == "relative_date") * sign
        if transform == "relative_date":
            day = _date(inputs[0], label)
            if unit in ("months", "years"):
                return _plus_months(day, int(amount) * (12 if unit == "years" else 1)).isoformat()
            return (day + timedelta(days=int(amount) * (7 if unit == "weeks" else 1))).isoformat()
        moment = _time(inputs[0], label).astimezone(timezone.utc)
        if unit in ("months", "years"):
            day = _plus_months(moment.date(), int(amount) * (12 if unit == "years" else 1))
            return _utc(datetime.combine(day, moment.timetz()))
        return _utc(moment + timedelta(seconds=amount * _SECONDS[unit]))
    if transform == "between_dates":
        start, end = _date(inputs[0], label), _date(inputs[1], label)
        if unit in ("months", "years"):
            months = _whole_months(start, end)
            return months if unit == "months" else int(months / 12)
        return int((end - start).days / (7 if unit == "weeks" else 1))
    if transform == "between_times":
        first, second = _time(inputs[0], label), _time(inputs[1], label)
        if unit in ("months", "years"):
            a, b = first.astimezone(timezone.utc), second.astimezone(timezone.utc)
            months = _whole_months(
                a.date(), b.date(),
                a - datetime.combine(a.date(), datetime.min.time(), timezone.utc),
                b - datetime.combine(b.date(), datetime.min.time(), timezone.utc))
            return months if unit == "months" else int(months / 12)
        return int((second - first).total_seconds() / _SECONDS[unit])
    kind, _, name = transform.partition("_")
    read = _date if kind == "date" else _time
    return _COMPARE[name](read(inputs[0], label), read(inputs[1], label))
