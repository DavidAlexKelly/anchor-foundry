"""Value formatting on a property (Foundry ``object-link-types`` p.94-101).

> "Value formatting refers to applying a special formatter to the value of a
> property, transforming the raw value to a more readable version." (p.94)

**This module validates a formatter; it does not apply one.** Applying happens
in the browser (``apps/web/src/lib/value-format.ts``), and it has to: p.100
offers "the application user's current timezone" as a legitimate choice, and a
server has no idea what that is. Formatting on the way out would also mean the
API returning `"$100K"` where it used to return `100000`, which would make
every non-screen consumer - filters, actions, aggregations, exports - wrong at
the same time.

What the server owes is a *refusal*, and the refusals are the point of the
file. Every one of them is a page that would otherwise render wrongly or throw:

* a formatter that does not match the property's base type (p.95: "you will see
  a type of formatting depending on the base type of the property"), which
  would be a number formatter quietly doing nothing to a string forever;
* digit bounds `Intl.NumberFormat` throws a `RangeError` on, which in a browser
  is a blank component and a console message nobody reads;
* a style missing the thing that style is *for* - a currency with no currency
  code, a unit with no unit.

The alternative to refusing here is discovering all three by looking at a
screen, which is exactly the trade `STATUS.md` keeps making the other way.
"""
from __future__ import annotations

from typing import Any

# The base types each family of formatter may be attached to (p.95).
NUMERIC_TYPES = ("integer", "float")
TEMPORAL_TYPES = ("date", "timestamp")

KINDS = ("number", "datetime")

#: p.97's "Base type" dropdown, minus Fixed Values - a value-to-label map is a
#: lookup rather than a formatter, and it is named in the parity doc instead of
#: being half-built here.
NUMBER_STYLES = ("plain", "currency", "unit", "percent", "affix")

#: p.99's table, one style per row.
DATETIME_STYLES = ("date", "datetime_long", "datetime_short", "iso", "relative", "time")

#: `Intl.NumberFormat`'s own ranges. Outside them it throws, and a formatter
#: that throws is a component that does not render.
DIGIT_BOUNDS = {
    "minimum_integer_digits": (1, 21),
    "minimum_fraction_digits": (0, 100),
    "maximum_fraction_digits": (0, 100),
    "minimum_significant_digits": (1, 21),
    "maximum_significant_digits": (1, 21),
}

NOTATIONS = ("standard", "compact", "scientific", "engineering")

_NUMBER_FIELDS = (
    "style", "currency", "unit", "prefix", "suffix", "grouping", "notation",
    *DIGIT_BOUNDS,
)
_DATETIME_FIELDS = ("style", "timezone")


class FormatError(ValueError):
    """A formatter that would not render. Surfaced as a 422 with its message."""


def parse(raw: Any, *, data_type: str, property_name: str) -> dict[str, Any] | None:
    """Validate one property's ``value_format``, or refuse it by name.

    Returns the normalised formatter, or ``None`` for "no formatting" - which
    is what every property that has never been configured means, and what
    clearing one means too.

    `property_name` is in every message on purpose: a type is saved with all of
    its properties at once, so "value_format: unknown style" would leave
    somebody hunting through fifteen of them for the one that was wrong.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise FormatError(f"{property_name}: value_format must be an object")

    kind = raw.get("kind")
    if kind not in KINDS:
        raise FormatError(
            f"{property_name}: value_format kind must be one of {', '.join(KINDS)}"
        )
    if kind == "number":
        return _number(raw, data_type=data_type, property_name=property_name)
    return _datetime(raw, data_type=data_type, property_name=property_name)


def _unknown_fields(raw: dict[str, Any], allowed: tuple[str, ...]) -> list[str]:
    return sorted(k for k in raw if k != "kind" and k not in allowed)


def _number(
    raw: dict[str, Any], *, data_type: str, property_name: str
) -> dict[str, Any]:
    if data_type not in NUMERIC_TYPES:
        raise FormatError(
            f"{property_name}: number formatting needs a numeric property; "
            f"this one is {data_type}"
        )
    extra = _unknown_fields(raw, _NUMBER_FIELDS)
    if extra:
        # Refused rather than dropped. A misspelled option that is silently
        # ignored is a setting somebody believes they turned on.
        raise FormatError(
            f"{property_name}: unknown number formatting option "
            f"{', '.join(extra)}"
        )

    style = raw.get("style", "plain")
    if style not in NUMBER_STYLES:
        raise FormatError(
            f"{property_name}: number style must be one of "
            f"{', '.join(NUMBER_STYLES)}"
        )
    out: dict[str, Any] = {"kind": "number", "style": style}

    if style == "currency":
        # A three-letter ISO 4217 code, which is what `Intl` takes. Checked for
        # shape rather than against a list: the list changes and this does not
        # need to be the place that tracks it.
        code = raw.get("currency")
        if not isinstance(code, str) or not code.isalpha() or len(code) != 3:
            raise FormatError(
                f"{property_name}: currency formatting needs a three-letter "
                "currency code, like USD"
            )
        out["currency"] = code.upper()
    elif style == "unit":
        unit = raw.get("unit")
        if not isinstance(unit, str) or not unit.strip():
            raise FormatError(
                f"{property_name}: unit formatting needs a unit, like kilogram"
            )
        out["unit"] = unit.strip()
    elif style == "affix":
        prefix = raw.get("prefix") or ""
        suffix = raw.get("suffix") or ""
        for name, value in (("prefix", prefix), ("suffix", suffix)):
            if not isinstance(value, str):
                raise FormatError(f"{property_name}: {name} must be text")
        if not prefix and not suffix:
            # p.97 calls this option "Prefix/Suffix". Neither is not a style,
            # it is `plain` with extra steps, and saving it would make the
            # editor show a style whose effect is nothing.
            raise FormatError(
                f"{property_name}: prefix/suffix formatting needs a prefix or "
                "a suffix"
            )
        out["prefix"], out["suffix"] = prefix, suffix

    if "grouping" in raw:
        if not isinstance(raw["grouping"], bool):
            raise FormatError(f"{property_name}: grouping must be true or false")
        out["grouping"] = raw["grouping"]
    if "notation" in raw:
        if raw["notation"] not in NOTATIONS:
            raise FormatError(
                f"{property_name}: notation must be one of {', '.join(NOTATIONS)}"
            )
        out["notation"] = raw["notation"]

    for field, (low, high) in DIGIT_BOUNDS.items():
        if field not in raw:
            continue
        value = raw[field]
        # `bool` is an `int` in Python and `True` would become 1 digit.
        if not isinstance(value, int) or isinstance(value, bool):
            raise FormatError(f"{property_name}: {field} must be a whole number")
        if not low <= value <= high:
            raise FormatError(
                f"{property_name}: {field} must be between {low} and {high}"
            )
        out[field] = value

    for lo_name, hi_name in (
        ("minimum_fraction_digits", "maximum_fraction_digits"),
        ("minimum_significant_digits", "maximum_significant_digits"),
    ):
        lo, hi = out.get(lo_name), out.get(hi_name)
        if lo is not None and hi is not None and lo > hi:
            # `Intl` throws on this pair, so the component renders nothing at
            # all - the property disappears rather than looking wrong.
            raise FormatError(
                f"{property_name}: {lo_name} cannot be more than {hi_name}"
            )
    return out


def _datetime(
    raw: dict[str, Any], *, data_type: str, property_name: str
) -> dict[str, Any]:
    if data_type not in TEMPORAL_TYPES:
        raise FormatError(
            f"{property_name}: date and time formatting needs a date or "
            f"timestamp property; this one is {data_type}"
        )
    extra = _unknown_fields(raw, _DATETIME_FIELDS)
    if extra:
        raise FormatError(
            f"{property_name}: unknown date and time formatting option "
            f"{', '.join(extra)}"
        )

    style = raw.get("style")
    if style not in DATETIME_STYLES:
        raise FormatError(
            f"{property_name}: date and time style must be one of "
            f"{', '.join(DATETIME_STYLES)}"
        )
    out: dict[str, Any] = {"kind": "datetime", "style": style}

    if "timezone" in raw and raw["timezone"] is not None:
        zone = raw["timezone"]
        if not isinstance(zone, str) or not zone.strip():
            raise FormatError(
                f"{property_name}: timezone must be a zone name, like "
                "Europe/London"
            )
        if data_type != "timestamp":
            # p.100 is specific: "If you are formatting a *timestamp*, you can
            # specify which timezone to render the timestamp". A date has no
            # instant to place in a zone - shifting one by an offset moves it
            # to a different day, which is a wrong answer rather than a
            # differently-presented one.
            raise FormatError(
                f"{property_name}: a timezone applies to a timestamp, not to "
                "a date"
            )
        out["timezone"] = zone.strip()
    # Absent timezone means the viewer's own (p.100), which only the browser
    # knows. Not defaulted to UTC here: a stored "UTC" is an author's choice
    # and an absent one is "wherever the reader is", and collapsing the two
    # would take the choice away.
    return out
