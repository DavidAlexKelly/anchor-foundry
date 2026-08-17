"""Validating conditional formatting rules (Foundry `object-link-types`
p.102-109).

Evaluation is the browser's and is tested there
(`apps/web/src/lib/conditional-format.test.ts`). Here: the refusals, and each
is a rule that would otherwise sit in an editor looking configured while doing
nothing anybody can see.
"""
from __future__ import annotations

import pytest

from src.services import conditional_format as cf

# p.102's own example type: a string, a boolean, and a number to compare
# against - because p.105-106's whole point is that a rule can paint one
# property using the value of another.
TYPES = {
    "type": "string",
    "wifi": "boolean",
    "performance": "float",
    "seen_at": "timestamp",
}


def parse(rules, property_name="type"):
    return cf.parse(rules, property_name=property_name, types_by_property=TYPES)


GREEN = {"colour": "#1a7f37"}


# ---- nothing at all ---------------------------------------------------------
def test_no_rules_is_the_default() -> None:
    assert parse(None) is None


def test_an_empty_list_is_stored_as_no_rules() -> None:
    """Two spellings of "none" is two things to compare in every test that
    touches this column, and they mean the same thing to every reader."""
    assert parse([]) is None


def test_rules_must_be_a_list() -> None:
    with pytest.raises(cf.RuleError, match="must be a list of rules"):
        parse({"kind": "always", **GREEN})


# ---- p.103's own two examples ----------------------------------------------
def test_p103s_wifi_rule() -> None:
    """"For property wifi, we assign green if the value of the property is
    'true' for each object in the table, and red if it is 'false'.\""""
    got = parse(
        [
            {"property": "wifi", "comparison": "boolean", "value": True, **GREEN},
            {"property": "wifi", "comparison": "boolean", "value": False,
             "colour": "#B91C1C"},
        ],
        property_name="wifi",
    )
    assert got == [
        {"kind": "standard", "colour": "#1a7f37", "property": "wifi",
         "comparison": "boolean", "value": True},
        {"kind": "standard", "colour": "#b91c1c", "property": "wifi",
         "comparison": "boolean", "value": False},
    ]


def test_a_boolean_comparison_needs_a_real_boolean() -> None:
    """p.103 writes the value as "true" in prose, and a rule that stored the
    *string* would never match the stored boolean - a rule that is on screen,
    looks right, and colours nothing."""
    for bad in ("true", 1, None):
        with pytest.raises(cf.RuleError, match="needs true or false"):
            parse([{"property": "wifi", "comparison": "boolean", "value": bad, **GREEN}],
                  property_name="wifi")


def test_p103s_type_rule_and_p106s_starts_with() -> None:
    """"assign colors based on exact match between A320, A321 and A330", and
    p.106's "color all plane type values that Start with 'A32'"."""
    got = parse([
        {"comparison": "string", "operator": "is_exactly", "value": "A320", **GREEN},
        {"comparison": "string", "operator": "starts_with", "value": "A32",
         "colour": "#1d4ed8"},
    ])
    assert [r["operator"] for r in got] == ["is_exactly", "starts_with"]
    # The property defaults to the one the rules are on (p.105 label B).
    assert {r["property"] for r in got} == {"type"}


# ---- the comparison has to fit the property (p.105 label C) -----------------
def test_a_numeric_comparison_on_a_string_is_refused() -> None:
    """"Types of comparisons available are based on the type of the property."
    A numeric range on a string is not a rule that never matches - it is a rule
    whose author believes it does."""
    with pytest.raises(cf.RuleError, match="'type' is string, so its comparison"):
        parse([{"comparison": "numeric_range", "min": 1, **GREEN}])


def test_a_string_comparison_on_a_number_is_refused() -> None:
    with pytest.raises(cf.RuleError, match="'performance' is float"):
        parse([{"property": "performance", "comparison": "string",
                "operator": "contains", "value": "x", **GREEN}])


def test_is_null_is_available_on_every_type() -> None:
    """p.106: "To color the type in grey if the value is null, select this
    dropdown and choose Is null instead of String comparison." Available on a
    timestamp too, which has no other comparison at all."""
    for name in TYPES:
        got = parse([{"property": name, "comparison": "is_null", **GREEN}])
        assert got[0]["comparison"] == "is_null"


# ---- painting one property using another (p.105-106 label B) ---------------
def test_a_rule_can_read_another_property() -> None:
    """"assume we want to color the value for Type in red when the value of
    Performance factor drops underneath a certain threshold. We would choose
    Performance factor in our logic instead of Type; however, the color would
    still show on Type.\""""
    got = parse([{"property": "performance", "comparison": "numeric_range",
                  "max": 0.8, "colour": "#B91C1C"}])
    assert got[0]["property"] == "performance"
    assert got[0]["max"] == 0.8


def test_a_rule_naming_a_property_that_is_not_there_is_refused() -> None:
    """The check only exists because the whole object type is being saved at
    once - nowhere else can see both the rule and its subject."""
    with pytest.raises(cf.RuleError, match="no property named 'altitude'"):
        parse([{"property": "altitude", "comparison": "is_null", **GREEN}])


def test_comparing_against_another_property_rather_than_a_constant() -> None:
    """p.105 label E: "Compare against a constant or a property reference.\""""
    got = parse([{"comparison": "string", "operator": "is_exactly",
                  "value_property": "type", **GREEN}])
    assert got[0]["value_property"] == "type"
    with pytest.raises(cf.RuleError, match="no property named 'nope'"):
        parse([{"comparison": "string", "operator": "is_exactly",
                "value_property": "nope", **GREEN}])
    with pytest.raises(cf.RuleError, match="not both"):
        parse([{"comparison": "string", "operator": "is_exactly",
                "value": "A320", "value_property": "type", **GREEN}])


# ---- always-true, and where it has to sit (p.105 label A) ------------------
def test_an_always_true_rule_must_be_last() -> None:
    """p.105: "Use Always true as a fallback in case your other rules don't
    match." First match wins, so a rule after it can never fire - and an
    unreachable rule is worse than a missing one, because it is on screen
    looking configured."""
    ok = parse([
        {"comparison": "string", "operator": "is_exactly", "value": "A320", **GREEN},
        {"kind": "always", "colour": "#6b7280"},
    ])
    assert ok[-1]["kind"] == "always"
    with pytest.raises(cf.RuleError, match="rule 1 always matches"):
        parse([
            {"kind": "always", "colour": "#6b7280"},
            {"comparison": "string", "operator": "is_exactly", "value": "A320", **GREEN},
        ])


def test_an_always_true_rule_takes_no_comparison() -> None:
    """Both at once is two intentions, and guessing which was meant is worse
    than asking."""
    with pytest.raises(cf.RuleError, match="takes no comparison"):
        parse([{"kind": "always", "comparison": "is_null", **GREEN}])


def test_an_unbounded_numeric_range_is_refused() -> None:
    """It matches every non-null value, which is an always-true rule wearing a
    comparison - and p.105 has a kind for that."""
    with pytest.raises(cf.RuleError, match="needs a min, a max, or both"):
        parse([{"property": "performance", "comparison": "numeric_range", **GREEN}])
    with pytest.raises(cf.RuleError, match="min cannot be more than max"):
        parse([{"property": "performance", "comparison": "numeric_range",
                "min": 5, "max": 1, **GREEN}])


# ---- the formatting itself (p.105's Formatting column) ---------------------
def test_a_rule_that_changes_nothing_is_refused() -> None:
    """The one outcome nobody can debug from a screen: the rule matched, and
    then did nothing."""
    with pytest.raises(cf.RuleError, match="cannot be seen"):
        parse([{"comparison": "is_null"}])


def test_colours_are_hex_and_are_normalised() -> None:
    """There is no Blueprint palette here, and a named colour we do not have
    would be a name that renders as nothing."""
    got = parse([{"comparison": "is_null", "colour": "#ABC", "background": "#FFEEDD",
                  "align": "right"}])
    assert got[0]["colour"] == "#abc"
    assert got[0]["background"] == "#ffeedd"
    assert got[0]["align"] == "right"
    for bad in ("green", "#12", "#12345", "rgb(1,2,3)"):
        with pytest.raises(cf.RuleError, match="must be a hex colour"):
            parse([{"comparison": "is_null", "colour": bad}])
    with pytest.raises(cf.RuleError, match="align must be one of"):
        parse([{"comparison": "is_null", "align": "middle", **GREEN}])


# ---- the rest ---------------------------------------------------------------
def test_negation_is_a_toggle(_=None) -> None:
    """p.105 label F: "Toggle between a True or False rule … To color all
    planes in blue that are not A320, switch this to False.\""""
    got = parse([{"comparison": "string", "operator": "is_exactly", "value": "A320",
                  "negate": True, "colour": "#1d4ed8"}])
    assert got[0]["negate"] is True
    with pytest.raises(cf.RuleError, match="negate must be true or false"):
        parse([{"comparison": "is_null", "negate": "yes", **GREEN}])


def test_an_unknown_string_operator_is_refused() -> None:
    with pytest.raises(cf.RuleError, match="string comparison needs one of"):
        parse([{"comparison": "string", "operator": "sounds_like", "value": "A",
                **GREEN}])


def test_an_unknown_option_is_refused_rather_than_dropped() -> None:
    with pytest.raises(cf.RuleError, match="unknown option colur"):
        parse([{"comparison": "is_null", "colur": "#abc", **GREEN}])


def test_there_is_a_cap_on_rules() -> None:
    many = [{"comparison": "is_null", **GREEN}] * (cf.MAX_RULES + 1)
    with pytest.raises(cf.RuleError, match=f"at most {cf.MAX_RULES}"):
        parse(many)


def test_the_property_and_the_rule_number_are_in_every_message() -> None:
    """A type is saved with all of its properties and all of their rules at
    once. "invalid comparison" would leave somebody counting rows."""
    with pytest.raises(cf.RuleError, match="^wifi: rule 2: "):
        parse(
            [
                {"comparison": "is_null", **GREEN},
                {"comparison": "string", "operator": "is_exactly", "value": "x", **GREEN},
            ],
            property_name="wifi",
        )
