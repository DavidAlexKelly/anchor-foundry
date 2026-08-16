"""Validating a property's value formatter (Foundry `object-link-types`
p.94-101).

The formatter itself runs in the browser and is tested there
(`apps/web/src/lib/value-format.test.ts`). What the server owes is the
**refusals** - and each one here is a page that would otherwise render wrongly
or not at all, which is why they are worth a test that can make them fail.
"""
from __future__ import annotations

import pytest

from src.services import value_format as vf


def parse(raw, data_type="float"):
    return vf.parse(raw, data_type=data_type, property_name="weight")


# ---- nothing at all ---------------------------------------------------------
def test_no_formatting_is_the_default_and_stays_none() -> None:
    """Every property that has never been configured. Worth stating because
    `None` has to survive the round trip - a formatter invented for an
    unformatted property would change how existing object types render."""
    assert parse(None) is None


def test_a_formatter_that_is_not_an_object_is_refused() -> None:
    with pytest.raises(vf.FormatError, match="must be an object"):
        parse("currency")


def test_an_unknown_kind_is_refused() -> None:
    with pytest.raises(vf.FormatError, match="kind must be one of"):
        parse({"kind": "colour"})


# ---- the formatter has to match the base type (p.95) ------------------------
def test_number_formatting_needs_a_numeric_property() -> None:
    """p.95: "you will see a type of formatting depending on the base type of
    the property". A number formatter on a string is not an error anybody sees
    - it is a setting that does nothing, forever."""
    with pytest.raises(vf.FormatError, match="needs a numeric property; this one is string"):
        parse({"kind": "number"}, data_type="string")
    assert parse({"kind": "number"}, data_type="integer") == {
        "kind": "number", "style": "plain",
    }


def test_date_formatting_needs_a_date_or_timestamp_property() -> None:
    with pytest.raises(vf.FormatError, match="needs a date or timestamp"):
        parse({"kind": "datetime", "style": "date"}, data_type="float")
    for ok in ("date", "timestamp"):
        assert parse({"kind": "datetime", "style": "date"}, data_type=ok)["style"] == "date"


# ---- number styles ----------------------------------------------------------
def test_a_currency_needs_a_currency_code_and_it_is_normalised() -> None:
    with pytest.raises(vf.FormatError, match="three-letter currency code"):
        parse({"kind": "number", "style": "currency"})
    with pytest.raises(vf.FormatError, match="three-letter currency code"):
        parse({"kind": "number", "style": "currency", "currency": "dollars"})
    assert parse({"kind": "number", "style": "currency", "currency": "usd"}) == {
        "kind": "number", "style": "currency", "currency": "USD",
    }


def test_a_unit_needs_a_unit() -> None:
    with pytest.raises(vf.FormatError, match="needs a unit"):
        parse({"kind": "number", "style": "unit", "unit": "   "})
    assert parse({"kind": "number", "style": "unit", "unit": " kilogram "})["unit"] == (
        "kilogram"
    )


def test_prefix_suffix_formatting_needs_one_of_them() -> None:
    """p.97 calls the style "Prefix/Suffix". Neither is `plain` with extra
    steps - and an editor showing a style whose effect is nothing is worse
    than one that refused to save it."""
    with pytest.raises(vf.FormatError, match="needs a prefix or a suffix"):
        parse({"kind": "number", "style": "affix"})
    assert parse({"kind": "number", "style": "affix", "suffix": " kg"}) == {
        "kind": "number", "style": "affix", "prefix": "", "suffix": " kg",
    }


def test_an_unknown_style_is_refused() -> None:
    with pytest.raises(vf.FormatError, match="style must be one of"):
        parse({"kind": "number", "style": "roman"})


# ---- digits (p.98) ----------------------------------------------------------
def test_digit_options_are_kept_and_bounded() -> None:
    """`Intl.NumberFormat`'s own ranges. Outside them it throws, and a
    formatter that throws is a component that renders nothing - the property
    disappears rather than looking wrong."""
    assert parse({
        "kind": "number", "grouping": True, "notation": "compact",
        "maximum_fraction_digits": 2, "minimum_fraction_digits": 1,
    }) == {
        "kind": "number", "style": "plain", "grouping": True, "notation": "compact",
        "maximum_fraction_digits": 2, "minimum_fraction_digits": 1,
    }
    with pytest.raises(vf.FormatError, match="between 0 and 100"):
        parse({"kind": "number", "maximum_fraction_digits": 101})
    with pytest.raises(vf.FormatError, match="between 1 and 21"):
        parse({"kind": "number", "minimum_significant_digits": 0})


def test_a_minimum_above_its_maximum_is_refused() -> None:
    """The pair `Intl` throws a RangeError on. Refused at save, because the
    alternative is a saved object type whose property is blank on every screen
    that draws it."""
    with pytest.raises(vf.FormatError, match="minimum_fraction_digits cannot be more"):
        parse({"kind": "number", "minimum_fraction_digits": 3,
               "maximum_fraction_digits": 2})
    with pytest.raises(vf.FormatError, match="minimum_significant_digits cannot be more"):
        parse({"kind": "number", "minimum_significant_digits": 5,
               "maximum_significant_digits": 2})
    # Equal is fine, and is the ordinary way to ask for exactly N digits.
    assert parse({"kind": "number", "minimum_fraction_digits": 2,
                  "maximum_fraction_digits": 2})["maximum_fraction_digits"] == 2


def test_a_digit_count_that_is_not_a_whole_number_is_refused() -> None:
    """`True` is an `int` in Python and would quietly become "1 digit"."""
    for bad in (2.5, "2", True, None):
        with pytest.raises(vf.FormatError, match="must be a whole number"):
            parse({"kind": "number", "maximum_fraction_digits": bad})


def test_grouping_and_notation_are_checked() -> None:
    with pytest.raises(vf.FormatError, match="grouping must be true or false"):
        parse({"kind": "number", "grouping": "yes"})
    with pytest.raises(vf.FormatError, match="notation must be one of"):
        parse({"kind": "number", "notation": "roman"})


# ---- date and time (p.99, p.100) -------------------------------------------
def test_every_style_p99_lists_is_accepted() -> None:
    for style in ("date", "datetime_long", "datetime_short", "iso", "relative", "time"):
        got = parse({"kind": "datetime", "style": style}, data_type="timestamp")
        assert got == {"kind": "datetime", "style": style}
    with pytest.raises(vf.FormatError, match="date and time style must be one of"):
        parse({"kind": "datetime", "style": "sundial"}, data_type="timestamp")


def test_a_timezone_applies_to_a_timestamp_and_not_to_a_date() -> None:
    """p.100 is specific: "If you are formatting a **timestamp**, you can
    specify which timezone". A date has no instant to place in a zone -
    shifting one by an offset moves it to a different day, which is a wrong
    answer rather than a differently-presented one."""
    assert parse({"kind": "datetime", "style": "date", "timezone": "Europe/London"},
                 data_type="timestamp")["timezone"] == "Europe/London"
    with pytest.raises(vf.FormatError, match="applies to a timestamp, not to a date"):
        parse({"kind": "datetime", "style": "date", "timezone": "Europe/London"},
              data_type="date")


def test_an_absent_timezone_is_not_defaulted_to_utc() -> None:
    """p.100 offers "the application user's current timezone", which only the
    browser knows. A stored "UTC" is an author's choice and an absent one is
    "wherever the reader is" - collapsing the two takes the choice away."""
    got = parse({"kind": "datetime", "style": "datetime_short"}, data_type="timestamp")
    assert "timezone" not in got


# ---- typos ------------------------------------------------------------------
def test_an_unknown_option_is_refused_rather_than_dropped() -> None:
    """A misspelled option that is silently ignored is a setting somebody
    believes they turned on - and they will believe it every time they reopen
    the editor and see it there."""
    with pytest.raises(vf.FormatError, match="unknown number formatting option currancy"):
        parse({"kind": "number", "style": "plain", "currancy": "USD"})
    with pytest.raises(vf.FormatError, match="unknown date and time formatting option tz"):
        parse({"kind": "datetime", "style": "date", "tz": "UTC"}, data_type="timestamp")


def test_the_property_is_named_in_every_message() -> None:
    """A type is saved with all of its properties at once, so a message
    without a name leaves somebody hunting through fifteen of them."""
    with pytest.raises(vf.FormatError, match="^total: "):
        vf.parse({"kind": "number"}, data_type="string", property_name="total")
