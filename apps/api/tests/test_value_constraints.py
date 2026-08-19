"""Value type constraints (parity `docs/parity/ontology.md` §1.2; Foundry
`object-link-types` p.233-234).

> "Each value type may optionally define a constraint to enforce data
> validation." (p.233)

**Two claims per constraint, and both matter.** A constraint has to *refuse*
what it should refuse, and it has to *accept* what it should accept - and the
second is the one that gets skipped, which is how a regex ends up rejecting
every row because somebody anchored it wrong. Every kind here is tested from
both sides.

The module is pure, so this file needs no database. That is the whole reason
it is pure: the worker evaluates these during a sync, and a rule that could
only be checked through an HTTP request would be a rule the worker's copy
could quietly disagree with.
"""
from __future__ import annotations

import pytest

from src.services import value_constraints as vc


def parse(raw, base_type="string"):
    return vc.parse(raw, base_type=base_type)


def fails(constraint, value, base_type="string") -> str | None:
    return vc.violation(constraint, base_type, value)


# ---- what a constraint may be attached to (p.233's base type lists) ---------
def test_a_regex_is_refused_on_anything_but_a_string() -> None:
    """p.233 lists Regex under String only. Attaching one to an integer would
    be a check that could never pass, discovered on a screen full of rejected
    rows rather than on the save."""
    with pytest.raises(vc.ConstraintError, match="does not apply to a integer"):
        parse({"kind": "regex", "pattern": "^x$"}, "integer")


def test_an_enum_is_refused_on_a_type_that_cannot_carry_one() -> None:
    with pytest.raises(vc.ConstraintError, match="does not apply to a date"):
        parse({"kind": "enum", "values": ["a"]}, "date")


def test_an_unknown_kind_is_refused_by_name() -> None:
    with pytest.raises(vc.ConstraintError, match="constraint kind must be one of"):
        parse({"kind": "handwave"}, "string")


def test_no_constraint_is_a_legitimate_value_type() -> None:
    """p.224 step 6 marks the constraint "(Optional)". A value type that only
    says "this string is an email address" still carries meaning, which is
    p.222's first argument for having them at all."""
    assert parse(None) is None
    assert fails(None, "anything at all") is None


# ---- enum (p.233) ------------------------------------------------------------
def test_an_enum_accepts_a_listed_value_and_refuses_an_unlisted_one() -> None:
    rule = parse({"kind": "enum", "values": ["draft", "live"]})
    assert fails(rule, "draft") is None
    assert "not one of" in fails(rule, "retired")


def test_an_enum_is_case_sensitive_unless_told_otherwise() -> None:
    """p.233: "For String properties, the enum values may optionally be
    case-sensitive or case-insensitive." Sensitive is the default, because a
    default that quietly accepted `DRAFT` would make the option meaningless in
    the direction somebody actually cares about."""
    strict = parse({"kind": "enum", "values": ["draft"]})
    assert fails(strict, "DRAFT") is not None
    loose = parse({"kind": "enum", "values": ["draft"], "case_sensitive": False})
    assert fails(loose, "DRAFT") is None
    assert fails(loose, "retired") is not None


def test_case_insensitivity_is_offered_only_where_it_means_something() -> None:
    """Not on integers or booleans. An option that silently does nothing is
    worse than one that is absent, because somebody will set it and believe
    it."""
    assert "case_sensitive" not in parse({"kind": "enum", "values": [1]}, "integer")


def test_an_enum_needs_values_and_refuses_duplicates() -> None:
    with pytest.raises(vc.ConstraintError, match="at least one value"):
        parse({"kind": "enum", "values": []})
    with pytest.raises(vc.ConstraintError, match="same value twice"):
        parse({"kind": "enum", "values": ["a", "a"]})


def test_an_enums_values_have_to_be_the_base_type() -> None:
    with pytest.raises(vc.ConstraintError, match="whole number"):
        parse({"kind": "enum", "values": [1, "two"]}, "integer")


def test_true_is_not_the_integer_one() -> None:
    """`bool` is a subclass of `int` in Python, and `1 == True`, so a boolean
    sails through an unguarded integer check both when the enum is *defined*
    and when a value is *tested*. Both directions are checked here because a
    dataset column can legitimately produce either."""
    with pytest.raises(vc.ConstraintError, match="whole number"):
        parse({"kind": "enum", "values": [True]}, "integer")
    rule = parse({"kind": "enum", "values": [1, 2]}, "integer")
    assert fails(rule, True, "integer") is not None


# ---- range (p.233) -----------------------------------------------------------
def test_a_numeric_range_bounds_both_ends() -> None:
    rule = parse({"kind": "range", "minimum": 1, "maximum": 5}, "integer")
    assert fails(rule, 1, "integer") is None
    assert fails(rule, 5, "integer") is None, "the bounds are inclusive"
    assert "below the minimum" in fails(rule, 0, "integer")
    assert "above the maximum" in fails(rule, 6, "integer")


def test_a_range_may_bound_only_one_end() -> None:
    at_least = parse({"kind": "range", "minimum": 0}, "float")
    assert fails(at_least, 1000.0, "float") is None
    assert fails(at_least, -0.5, "float") is not None


def test_a_range_with_neither_end_is_refused() -> None:
    with pytest.raises(vc.ConstraintError, match="needs a minimum"):
        parse({"kind": "range"}, "integer")


def test_a_range_that_nothing_could_satisfy_is_refused() -> None:
    """A minimum above the maximum is a constraint that rejects every row, and
    the only sign of it would be an object type that stops indexing."""
    with pytest.raises(vc.ConstraintError, match="nothing could satisfy"):
        parse({"kind": "range", "minimum": 10, "maximum": 1}, "integer")


def test_a_string_range_bounds_its_length() -> None:
    """p.233: "For String properties, the length of the string is
    constrained." Not its alphabetical position, which is the other reading and
    is nobody's intention."""
    rule = parse({"kind": "range", "minimum": 2, "maximum": 3}, "string")
    assert fails(rule, "GB") is None
    assert "characters" in fails(rule, "G")
    assert fails(rule, "GBRX") is not None


def test_a_negative_string_length_is_refused() -> None:
    with pytest.raises(vc.ConstraintError, match="cannot be negative"):
        parse({"kind": "range", "minimum": -1}, "string")


def test_a_temporal_range_compares_as_time_not_as_text() -> None:
    """`"2026-1-5" < "2026-01-31"` is false as strings and true as dates, so a
    range that compared text would pass and fail the wrong rows around every
    single-digit month."""
    rule = parse({"kind": "range", "minimum": "2026-01-01", "maximum": "2026-12-31"}, "date")
    assert fails(rule, "2026-06-15", "date") is None
    assert fails(rule, "2025-12-31", "date") is not None
    assert fails(rule, "2027-01-01", "date") is not None


def test_a_timestamp_range_survives_a_mix_of_offsets() -> None:
    """A naive and an aware datetime cannot be compared in Python, and writing
    one bound with a `Z` and testing a value without one is ordinary. Raising
    `TypeError` here would be a 500 on an ordinary sync."""
    rule = parse(
        {"kind": "range", "minimum": "2026-01-01T00:00:00Z"}, "timestamp"
    )
    assert fails(rule, "2026-06-01T12:00:00", "timestamp") is None
    assert fails(rule, "2025-06-01T12:00:00+02:00", "timestamp") is not None


def test_an_offset_is_converted_rather_than_discarded() -> None:
    """**The mutation that survived first, and the bug it found.** Normalising
    an aware timestamp by dropping its tzinfo makes
    `2026-01-01T05:00:00+06:00` sort as 05:00, when the instant it names is
    23:00 the day before. Both readings compare cleanly and only one is right,
    so nothing raises - a range simply accepts and rejects the wrong rows for
    every value carrying an offset.

    This value is *after* the bound as text and as a stripped naive time, and
    *before* it as an instant, so it can only pass if the offset is applied.
    """
    rule = parse({"kind": "range", "minimum": "2026-01-01T00:00:00Z"}, "timestamp")
    assert fails(rule, "2026-01-01T05:00:00+06:00", "timestamp") is not None
    # And the mirror: an instant just after the bound, written with an offset
    # that makes it look earlier as text.
    assert fails(rule, "2026-01-01T01:00:00+00:30", "timestamp") is None


def test_a_date_range_disagrees_with_text_ordering_and_the_dates_win() -> None:
    """The claim the previous version of this test only *asserted*: every value
    it used was zero-padded, so string and date ordering agreed and a
    text-comparing implementation passed it. A two-digit year-month boundary is
    where the two orderings actually diverge.

    `"2026-1-05"` is not valid ISO 8601, so it is a *malformed* date rather
    than an early one - which is its own answer, and not "below the minimum".
    """
    rule = parse({"kind": "range", "minimum": "2026-02-01"}, "date")
    assert "not a valid date" in fails(rule, "2026-1-5", "date")


def test_a_value_that_is_not_the_type_at_all_is_a_violation_not_a_crash() -> None:
    """Instance properties are stored untyped (§52), so a `date` property can
    hold "not a date" and a sync must report that rather than raise."""
    rule = parse({"kind": "range", "minimum": "2026-01-01"}, "date")
    assert "not a valid date" in fails(rule, "sometime", "date")
    numeric = parse({"kind": "range", "minimum": 1}, "integer")
    assert "not a number" in fails(numeric, "seven", "integer")


# ---- regex (p.233) -----------------------------------------------------------
def test_a_regex_matches_the_whole_value_by_default() -> None:
    """p.233 offers substring matching as an *option*, so the default is the
    other thing. Somebody writing `[a-z]+@example\\.com` means the value is an
    address, not that one is hiding inside it."""
    rule = parse({"kind": "regex", "pattern": r"[a-z]+@example\.com"})
    assert fails(rule, "ada@example.com") is None
    assert fails(rule, "send to ada@example.com now") is not None


def test_a_substring_regex_is_the_documented_opt_in() -> None:
    rule = parse({"kind": "regex", "pattern": "urgent", "substring": True})
    assert fails(rule, "this is urgent, please read") is None
    assert fails(rule, "nothing to see") is not None


def test_a_regex_that_does_not_compile_is_refused_on_the_save() -> None:
    """Not at sync time, on every row, in a log nobody is reading."""
    with pytest.raises(vc.ConstraintError, match="does not compile"):
        parse({"kind": "regex", "pattern": "([unclosed"})


def test_an_enormous_regex_is_refused() -> None:
    """A pattern somebody posts is a pattern this platform runs on every synced
    row. The length cap is not a validation nicety - it is the one lever
    against catastrophic backtracking written as configuration."""
    with pytest.raises(vc.ConstraintError, match="at most"):
        parse({"kind": "regex", "pattern": "a" * (vc.MAX_REGEX_LENGTH + 1)})


def test_a_regex_needs_a_pattern() -> None:
    with pytest.raises(vc.ConstraintError, match="needs a pattern"):
        parse({"kind": "regex"})


# ---- uuid (p.233) ------------------------------------------------------------
def test_a_uuid_constraint_accepts_a_uuid_and_refuses_a_near_miss() -> None:
    rule = parse({"kind": "uuid"})
    assert fails(rule, "3f2504e0-4f89-11d3-9a0c-0305e82c3301") is None
    assert "not a UUID" in fails(rule, "3f2504e0-4f89-11d3-9a0c")


# ---- what a constraint is *not* ---------------------------------------------
@pytest.mark.parametrize("empty", [None, "", "   "])
def test_a_missing_value_is_not_a_violation(empty) -> None:
    """**Deliberately not `required`'s job** (p.116). Two separate rules, so
    that an optional property does not silently become compulsory the moment
    somebody gives it an email value type."""
    rule = parse({"kind": "regex", "pattern": r"[a-z]+@example\.com"})
    assert fails(rule, empty) is None


def test_zero_and_false_are_values() -> None:
    """The classic false negative in a check written with `if not value`. A
    range of 1-5 must reject 0 as *out of range*, not skip it as absent."""
    numeric = parse({"kind": "range", "minimum": 1, "maximum": 5}, "integer")
    assert fails(numeric, 0, "integer") is not None
    boolean = parse({"kind": "enum", "values": [True]}, "boolean")
    assert fails(boolean, False, "boolean") is not None


# ---- the human-readable form -------------------------------------------------
def test_describe_shows_the_pattern_somebody_wrote() -> None:
    """A listing has no room for the shape, and "a regex constraint" tells a
    reader nothing they did not already know from the kind."""
    assert vc.describe(parse({"kind": "regex", "pattern": "^[A-Z]{2}$"})) == (
        "matches ^[A-Z]{2}$"
    )
    assert vc.describe(parse({"kind": "enum", "values": ["a", "b"]})) == "one of a, b"
    assert vc.describe(
        parse({"kind": "range", "minimum": 1, "maximum": 5}, "integer")
    ) == "between 1 and 5"
    assert vc.describe(parse({"kind": "range", "minimum": 1}, "integer")) == "at least 1"
    assert vc.describe(None) == "no constraint"
