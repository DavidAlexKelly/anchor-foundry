"""Conditional formatting rules on a property (Foundry ``object-link-types``
p.102-109).

> "Conditional formatting enables the configuration of rules for any property
> and dictates how that property's values will be rendered (e.g. coloring,
> alignment, etc.) in user facing applications." (p.102)

**Validated here, evaluated in the browser** - the same split as
``value_format`` (p.94-101) and for a stronger reason: a rule's answer depends
on the *instance*, so evaluating on the server would mean colouring every row
of every page before sending it, for a decision that is entirely about how
something looks.

**The rules compare the raw value, never the formatted text.** A property can
carry both a formatter and a rule, and p.102's own example does: a number shown
compactly and coloured by a threshold. If a rule were handed ``"$100K"`` to
compare it would never be greater than 50000, because a string never was
greater than anything. Two settings on one property, reading the same stored
number, deciding different things about it.

**This is not the ordered-comparison rule the stores refuse.** ``OPERATORS``
excludes ordered operators because instance properties are stored untyped and
Postgres and OpenSearch would disagree about whether "250" sorts before "40".
Nothing here touches a store: the comparison happens in a browser, on a value
already fetched, against a property the object type *declares* as numeric. The
declaration is what makes it safe, and it is why a numeric rule is allowed on a
numeric property and refused on a string one.
"""
from __future__ import annotations

from typing import Any

MAX_RULES = 20

#: p.105 label A. "Math rule" is deliberately absent - it runs arithmetic over
#: properties, which is an expression language rather than a comparison, and
#: half of one would be worse than none. Named in the parity doc instead.
RULE_KINDS = ("standard", "always")

#: p.105 label C, keyed by what the compared property's base type allows.
COMPARISONS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "string": ("string", "is_null"),
    "integer": ("numeric_range", "numeric_exact", "is_null"),
    "float": ("numeric_range", "numeric_exact", "is_null"),
    "boolean": ("boolean", "is_null"),
    "date": ("is_null",),
    "timestamp": ("is_null",),
}

#: p.105 label D. "Is exactly, Contains, Starts with, etc."
STRING_OPERATORS = ("is_exactly", "contains", "starts_with", "ends_with")

ALIGNMENTS = ("left", "center", "right")

_RULE_FIELDS = (
    "kind", "property", "comparison", "operator", "value", "min", "max",
    "value_property", "negate", "colour", "background", "align",
)


class RuleError(ValueError):
    """A rule that cannot be evaluated. Surfaced as a 422 with its message."""


def parse(
    raw: Any,
    *,
    property_name: str,
    types_by_property: dict[str, str],
) -> list[dict[str, Any]] | None:
    """Validate one property's rule list, or refuse it by name.

    `types_by_property` is the base type of every property on the object type
    being saved - not of the one property - because p.105's own example paints
    `Type` using the value of `Performance factor`. A rule naming a property
    that is not on the type is refused here, which is the only place that can
    see both.

    Returns `None` for "no rules", which is what every property means today.
    """
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise RuleError(f"{property_name}: conditional_format must be a list of rules")
    if not raw:
        # An empty list and no rules are the same thing to every reader, so
        # they are stored the same way. Two spellings of "none" is two things
        # to compare in every test that touches this column.
        return None
    if len(raw) > MAX_RULES:
        raise RuleError(
            f"{property_name}: at most {MAX_RULES} conditional formatting rules"
        )

    out: list[dict[str, Any]] = []
    for index, rule in enumerate(raw):
        out.append(
            _rule(
                rule,
                where=f"{property_name}: rule {index + 1}",
                default_property=property_name,
                types_by_property=types_by_property,
            )
        )
        if out[-1]["kind"] == "always" and index != len(raw) - 1:
            # p.105: "Use Always true as a fallback in case your other rules
            # don't match." First match wins, so anything after an always-true
            # rule can never fire - and an unreachable rule is worse than a
            # missing one, because it is on screen looking configured.
            raise RuleError(
                f"{property_name}: rule {index + 1} always matches, so the rules "
                "after it can never apply; move it last"
            )
    return out


def _rule(
    raw: Any,
    *,
    where: str,
    default_property: str,
    types_by_property: dict[str, str],
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise RuleError(f"{where}: must be an object")
    extra = sorted(k for k in raw if k not in _RULE_FIELDS)
    if extra:
        raise RuleError(f"{where}: unknown option {', '.join(extra)}")

    kind = raw.get("kind", "standard")
    if kind not in RULE_KINDS:
        raise RuleError(f"{where}: kind must be one of {', '.join(RULE_KINDS)}")

    out: dict[str, Any] = {"kind": kind, **_formatting(raw, where=where)}
    if kind == "always":
        # No comparison to check, and none accepted: a rule that says both
        # "always" and "when the value is 3" is two intentions, and guessing
        # which one somebody meant is worse than asking.
        for field in ("comparison", "operator", "value", "min", "max", "value_property"):
            if field in raw and raw[field] is not None:
                raise RuleError(
                    f"{where}: an always-true rule takes no {field}"
                )
        return out

    # p.105 label B: the rule reads this property, and paints the one it is on.
    subject = raw.get("property") or default_property
    if not isinstance(subject, str):
        raise RuleError(f"{where}: property must be a name")
    if subject not in types_by_property:
        raise RuleError(
            f"{where}: no property named {subject!r} on this object type"
        )
    out["property"] = subject
    subject_type = types_by_property[subject]

    allowed = COMPARISONS_BY_TYPE.get(subject_type, ("is_null",))
    comparison = raw.get("comparison")
    if comparison not in allowed:
        # p.105 label C: "Types of comparisons available are based on the type
        # of the property." A numeric range on a string is not a rule that
        # never matches - it is a rule whose author believes it does.
        raise RuleError(
            f"{where}: {subject!r} is {subject_type}, so its comparison must be "
            f"one of {', '.join(allowed)}"
        )
    out["comparison"] = comparison

    if comparison == "string":
        operator = raw.get("operator")
        if operator not in STRING_OPERATORS:
            raise RuleError(
                f"{where}: string comparison needs one of "
                f"{', '.join(STRING_OPERATORS)}"
            )
        out["operator"] = operator
        out.update(_comparand(raw, where=where, types_by_property=types_by_property))
    elif comparison == "numeric_exact":
        out.update(_comparand(raw, where=where, types_by_property=types_by_property))
    elif comparison == "numeric_range":
        low, high = raw.get("min"), raw.get("max")
        for name, bound in (("min", low), ("max", high)):
            if bound is not None and not isinstance(bound, (int, float)):
                raise RuleError(f"{where}: {name} must be a number")
            if isinstance(bound, bool):
                raise RuleError(f"{where}: {name} must be a number")
        if low is None and high is None:
            # An unbounded range matches every non-null value, which is an
            # always-true rule wearing a comparison. p.105 has a kind for that.
            raise RuleError(
                f"{where}: a numeric range needs a min, a max, or both"
            )
        if low is not None and high is not None and low > high:
            raise RuleError(f"{where}: min cannot be more than max")
        if low is not None:
            out["min"] = low
        if high is not None:
            out["max"] = high
    elif comparison == "boolean":
        value = raw.get("value")
        if not isinstance(value, bool):
            raise RuleError(f"{where}: a boolean comparison needs true or false")
        out["value"] = value

    if "negate" in raw:
        # p.105 label F, "Toggle between a True or False rule".
        if not isinstance(raw["negate"], bool):
            raise RuleError(f"{where}: negate must be true or false")
        out["negate"] = raw["negate"]
    return out


def _comparand(
    raw: dict[str, Any], *, where: str, types_by_property: dict[str, str]
) -> dict[str, Any]:
    """p.105 label E: "Compare against a constant or a property reference."."""
    reference = raw.get("value_property")
    if reference is not None:
        if raw.get("value") is not None:
            raise RuleError(
                f"{where}: compare against a constant or another property, "
                "not both"
            )
        if not isinstance(reference, str) or reference not in types_by_property:
            raise RuleError(
                f"{where}: no property named {reference!r} on this object type"
            )
        return {"value_property": reference}
    value = raw.get("value")
    if value is None:
        raise RuleError(f"{where}: needs a value to compare against")
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise RuleError(f"{where}: the value must be text or a number")
    return {"value": value}


def _formatting(raw: dict[str, Any], *, where: str) -> dict[str, Any]:
    """p.105's Formatting column: colour, background, alignment.

    A rule that matches and then does nothing is the one outcome nobody can
    debug from a screen, so at least one of the three is required.
    """
    out: dict[str, Any] = {}
    for field in ("colour", "background"):
        value = raw.get(field)
        if value is None:
            continue
        if not isinstance(value, str) or not _is_hex(value):
            # Hex only. p.105 offers "Blueprint colors and intents or add your
            # own custom color" - there is no Blueprint here, and a named
            # palette we do not have would be a name that renders as nothing.
            raise RuleError(
                f"{where}: {field} must be a hex colour like #1a7f37"
            )
        out[field] = value.lower()
    align = raw.get("align")
    if align is not None:
        if align not in ALIGNMENTS:
            raise RuleError(
                f"{where}: align must be one of {', '.join(ALIGNMENTS)}"
            )
        out["align"] = align
    if not out:
        raise RuleError(
            f"{where}: needs a colour, a background or an alignment - a rule "
            "that matches and changes nothing cannot be seen"
        )
    return out


def _is_hex(value: str) -> bool:
    if not value.startswith("#") or len(value) not in (4, 7):
        return False
    return all(c in "0123456789abcdefABCDEF" for c in value[1:])
