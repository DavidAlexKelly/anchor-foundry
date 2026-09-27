"""The rest of Workshop's casts, and Object RID (§569; `workshop` p.138-139).

    "String → Date: Pass in a string type containing a validly formatted date
     value and select the corresponding date format used in the Parser field.
     For example, if passing in a string variable with the value 06/26/24,
     select M/dd/yyyy as the corresponding parser format to cast to a date
     type. String → Timestamp: … The timezone used when casting the outputted
     timestamp value may be defined either using the user's local timezone,
     set statically via options in a dropdown, or set dynamically using a
     string reference or variable. … String → GeoPoint … String → GeoShape …
     Timestamp → Date … Date → Timestamp: … converted to a timestamp
     representing start of day at the specified timezone." (p.138-139)

    "Object RID: Returns the object RID for a given object." (p.139)

**A parser is a pattern in the letters p.138 uses**, Java's: `yyyy` or `yy`
for the year, `M`/`MM` for the month as a number and `MMM`/`MMMM` as its
name, `d`/`dd`, `H`/`HH` (0-23), `h`/`hh` (1-12) with `a` for AM or PM,
`mm`, `ss`, and `SSS` for fractions of a second. Anything else is text to
match as written, and text in single quotes is matched as written too. A
year of two digits is this century's, which is how p.138's own example reads
"24" against `yyyy`.

**A time zone is named** (`Europe/Paris`), set on the cast, or is `local`:
p.138-139's "the user's local timezone" (§596), which the browser sends with
each resolve (`workshop_variables.evaluate`'s `time_zone`). With no viewer to
ask - or one whose zone this server does not know - `local` is UTC, as a cast
with no zone is.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .property_values import PropertyValueError, _coerce_geopoint, _coerce_geoshape

#: p.138-139's "the user's local timezone", as a cast's zone (§596).
LOCAL = "local"

#: The targets besides string, number and boolean, which `cast` has long taken.
TARGETS = ("date", "timestamp", "geopoint", "geoshape")
MAX_PATTERN = 60

_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december")
_FIELDS = {
    "y": ("year", r"\d{2}|\d{4}"),
    "d": ("day", r"\d{1,2}"),
    "H": ("hour", r"\d{1,2}"),
    "h": ("hour12", r"\d{1,2}"),
    "m": ("minute", r"\d{1,2}"),
    "s": ("second", r"\d{1,2}"),
    "S": ("fraction", r"\d{1,9}"),
    "a": ("half", r"[AaPp][Mm]"),
}


class CastError(ValueError):
    """A value or a pattern the cast cannot read."""


def _pattern(pattern: str) -> tuple[re.Pattern[str], list[str]]:
    """A Java-style pattern as a regular expression, and the fields it names
    in order."""
    parts, names, n = [], [], 0
    while n < len(pattern):
        char = pattern[n]
        if char == "'":
            end = pattern.find("'", n + 1)
            if end < 0:
                raise CastError(f"the parser {pattern!r} opens a quote it does not close")
            parts.append(re.escape(pattern[n + 1:end]))
            n = end + 1
            continue
        run = len(pattern[n:]) - len(pattern[n:].lstrip(char))
        if char == "M":
            name, rule = ("month_name", "[A-Za-z]+") if run >= 3 else ("month", r"\d{1,2}")
        elif char in _FIELDS:
            name, rule = _FIELDS[char]
        elif char.isalpha():
            raise CastError(f"the parser {pattern!r} uses {char!r}, which is not a date or time letter")
        else:
            parts.append(re.escape(pattern[n:n + run]))
            n += run
            continue
        if name in names:
            raise CastError(f"the parser {pattern!r} names the {name.replace('_', ' ')} twice")
        parts.append(f"({rule})")
        names.append(name)
        n += run
    return re.compile("".join(parts)), names


def check(target: str, config: dict[str, Any]) -> str | None:
    """Why a cast to `target` cannot run, or None."""
    if target in ("date", "timestamp") and config.get("format"):
        parser = config["format"]
        if not isinstance(parser, str) or len(parser) > MAX_PATTERN:
            return f"a parser is text of at most {MAX_PATTERN} characters"
        try:
            _, names = _pattern(parser)
        except CastError as exc:
            return str(exc)
        wanted = ("year", "day") if target == "date" else ("year", "day", "hour")
        missing = [n for n in wanted if n not in names and (n != "hour" or "hour12" not in names)]
        if "month" not in names and "month_name" not in names:
            missing.insert(1, "month")
        if missing:
            return f"a parser to a {target} needs the {', '.join(missing)}"
        if "hour12" in names and "half" not in names:
            return "a parser with a 12-hour clock (h) needs AM or PM (a)"
    zone = config.get("timezone")
    if zone is not None:
        try:
            _zone(zone)
        except CastError as exc:
            return str(exc)
    return None


def viewer_zone(name: Any) -> str | None:
    """The viewer's zone as the browser named it, or None when it names
    nothing this server knows - which `local` then reads as UTC rather than
    refusing a module over a setting the viewer cannot change."""
    if not isinstance(name, str) or not name or name == LOCAL:
        return None
    try:
        _zone(name)
    except CastError:
        return None
    return name


def _zone(name: Any) -> ZoneInfo | timezone:
    # None or nothing is UTC; "UTC" by name is the database's own, which
    # answers the same (a shortcut for it survived the sweep as equivalent).
    # `local` with no viewer's zone put in its place is UTC too.
    if name in (None, "", LOCAL):
        return timezone.utc
    if not isinstance(name, str):
        raise CastError(f"{name!r} is not a time zone")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise CastError(f"{name!r} is not a time zone - name one such as Europe/Paris") from None


def _parse(text: str, parser: str) -> dict[str, int]:
    regex, names = _pattern(parser)
    match = regex.fullmatch(text.strip())
    if not match:
        raise CastError(f"{text!r} does not match the parser {parser!r}")
    got = dict(zip(names, match.groups()))
    out: dict[str, int] = {}
    year = got["year"]
    out["year"] = 2000 + int(year) if len(year) == 2 else int(year)
    if "month_name" in got:
        word = got["month_name"].lower()
        month = next((n for n, m in enumerate(_MONTHS, 1) if m == word or m[:3] == word), None)
        if month is None:
            raise CastError(f"{got['month_name']!r} is not a month")
        out["month"] = month
    else:
        out["month"] = int(got["month"])
    out["day"] = int(got["day"])
    if "hour12" in got:
        hour = int(got["hour12"])
        if not 1 <= hour <= 12:
            raise CastError(f"{hour} is not an hour on a 12-hour clock")
        out["hour"] = hour % 12 + (12 if got["half"].lower() == "pm" else 0)
    else:
        out["hour"] = int(got.get("hour", 0))
    out["minute"] = int(got.get("minute", 0))
    out["second"] = int(got.get("second", 0))
    out["microsecond"] = int((got.get("fraction", "0") + "000000")[:6])
    return out


def _utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def cast(value: Any, target: str, config: dict[str, Any], label: str) -> Any:
    """`value` as `target`, or a CastError saying why not."""
    zone = _zone(config.get("timezone"))
    parser = config.get("format") or None
    if target == "geopoint":
        try:
            return _coerce_geopoint(value)
        except PropertyValueError as exc:
            raise CastError(str(exc)) from None
    if target == "geoshape":
        try:
            return _coerce_geoshape(value)
        except PropertyValueError as exc:
            raise CastError(str(exc)) from None
    if not isinstance(value, str):
        raise CastError(f"{value!r} is not text, a date or a timestamp")
    if parser:
        fields = _parse(value, parser)
        try:
            moment = datetime(tzinfo=zone, **fields)
        except ValueError as exc:
            raise CastError(f"{value!r} is not a real {target}: {exc}") from None
        return moment.date().isoformat() if target == "date" else _utc(moment)
    if target == "date":
        if len(value) == 10:
            try:
                return date.fromisoformat(value).isoformat()
            except ValueError:
                pass
        # p.139's Timestamp → Date: the instant's day in the zone chosen.
        try:
            moment = datetime.fromisoformat(value)
        except ValueError:
            raise CastError(f"{value!r} is not a date or a timestamp - give a parser") from None
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(zone).date().isoformat()
    # To a timestamp: p.139's Date → Timestamp is the start of that day in the
    # zone chosen; a timestamp with no zone is read in that zone too.
    if len(value) == 10:
        try:
            day = date.fromisoformat(value)
        except ValueError:
            raise CastError(f"{value!r} is not a date or a timestamp - give a parser") from None
        return _utc(datetime.combine(day, time(0), tzinfo=zone))
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        raise CastError(f"{value!r} is not a date or a timestamp - give a parser") from None
    return _utc(moment if moment.tzinfo else moment.replace(tzinfo=zone))


def object_rid(obj: Any, label: str) -> Any:
    """p.139's Object RID: the object's own id, which is what identifies an
    object here as a RID does in Foundry."""
    if obj is None or obj == "":
        return None
    if not isinstance(obj, dict) or not obj.get("id"):
        raise CastError(f"{label!r} reads the id of something that is not an object")
    return str(obj["id"])
