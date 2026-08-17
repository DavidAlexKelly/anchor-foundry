"""Derived properties (Foundry ``object-link-types`` p.143-148).

> "Derived properties are properties that are calculated at runtime based on
> values from linked objects." (p.143)

**A question, not a value.** Nothing is written under a derived property: the
declaration says which links to follow, what to do with what it finds, and
which property at the far end to read, and the answer is worked out when
somebody reads the object. Materialising it would create a second answer, free
to disagree with the first the moment a linked object changed.

**This module validates the question; `instances`/`instance_store` answer it.**
The split is `value_format`'s and `conditional_format`'s: refusals belong where
the whole object type is visible, and evaluation belongs where the data is.

Every refusal here is a declaration that would otherwise produce a column of
blanks, or an error on a page rather than on a save:

* a chain longer than p.147's three hops, or one whose links do not join up;
* an aggregation missing where a hop is "many" (p.145) - without one there is
  no single value to show, so the property would be silently empty on exactly
  the objects it is for;
* `count` carrying a property, or anything else missing one (p.146);
* a collection limit on an aggregation that collects nothing;
* p.148's own list of things a derived property cannot also be - a primary
  key, required, or formatted.
"""
from __future__ import annotations

from typing import Any

#: p.147: "Derived properties support traversing up to 3 levels of linked
#: objects."
MAX_HOPS = 3

#: p.145's list, in its order. `approx_cardinality` and `exact_cardinality` are
#: p.145's "Approximate/Exact cardinality"; the names here say which is which
#: without a reader having to know the OpenSearch spelling.
AGGREGATES = (
    "count",
    "avg",
    "sum",
    "min",
    "max",
    "approx_cardinality",
    "exact_cardinality",
    "collect_list",
    "collect_set",
)

#: The two that gather values rather than reduce them, and the only two p.146
#: gives a limit to.
COLLECTORS = ("collect_list", "collect_set")

#: The ones this platform cannot answer the same way on both stores, and so
#: refuses rather than guesses at.
#:
#: `sum`/`avg`/`min`/`max` need to know a property is a number, and instance
#: properties are stored untyped - the blocker §52 named for ordered filters,
#: §74 for numeric aggregations, §83 for property sorts and §86 for map area
#: selection. This is the fifth thing waiting behind it.
#:
#: `approx_cardinality` is refused for a sharper reason: OpenSearch's
#: cardinality aggregation is approximate and Postgres' `COUNT(DISTINCT)` is
#: exact, so "approximate" would be a promise one store keeps and the other
#: exceeds. `exact_cardinality` is the same question with an answer both can
#: give, so it is the one offered.
UNSUPPORTED_AGGREGATES = ("sum", "avg", "min", "max", "approx_cardinality")

#: p.146: "The default limit is 10 items."
DEFAULT_LIMIT = 10
MAX_LIMIT = 1000

#: `far_type_id` is in this list because `parse` *returns* it: an API that
#: cannot accept its own output back makes read-modify-write impossible, and
#: every client would have to know which fields to strip before saving. It is
#: still checked rather than trusted - see `parse`.
_FIELDS = ("links", "aggregate", "property", "limit", "far_type_id")


class DerivationError(ValueError):
    """A derived property that could not be answered. Surfaced as a 422."""


def parse(
    raw: Any,
    *,
    property_name: str,
    link_types: dict[str, dict[str, Any]],
    object_type_id: str,
) -> dict[str, Any] | None:
    """Validate one property's ``derivation``, or refuse it by name.

    `link_types` is every link type in the workspace, keyed by id, each with
    `from_object_type_id`, `to_object_type_id` and `cardinality` - because
    whether a chain joins up, and whether any hop is "many", are facts about
    the ontology rather than about this property.

    Returns the normalised derivation, or ``None`` for an ordinary property.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise DerivationError(f"{property_name}: derivation must be an object")
    extra = sorted(k for k in raw if k not in _FIELDS)
    if extra:
        raise DerivationError(
            f"{property_name}: unknown derivation option {', '.join(extra)}"
        )

    hops, far_type, many = _chain(
        raw.get("links"),
        property_name=property_name,
        link_types=link_types,
        object_type_id=object_type_id,
    )

    aggregate = raw.get("aggregate")
    if aggregate is not None and aggregate not in AGGREGATES:
        raise DerivationError(
            f"{property_name}: aggregate must be one of {', '.join(AGGREGATES)}"
        )
    if aggregate in UNSUPPORTED_AGGREGATES:
        raise DerivationError(
            f"{property_name}: {aggregate!r} is not available - instance "
            "properties are stored untyped, so this platform cannot promise "
            "the same answer on both stores. Use count or exact_cardinality, "
            "or collect the values and read them"
        )
    if many and aggregate is None:
        # p.145: "If any link in your chain has a 'many' cardinality … you must
        # select an Aggregation to combine the values." Without one there is no
        # single value to put in the cell, and the honest failure is here
        # rather than a blank on every object that has more than one.
        raise DerivationError(
            f"{property_name}: this link chain can reach more than one object, "
            "so it needs an aggregation"
        )

    declared_far = raw.get("far_type_id")
    if declared_far is not None and str(declared_far) != far_type:
        # Accepted back, never trusted: the chain decides where it lands, and
        # a caller saying otherwise is describing a different walk than the one
        # it sent. Same refusal §156 makes for a traversal's link/landing pair.
        raise DerivationError(
            f"{property_name}: this chain lands on a different object type "
            "than the derivation declares"
        )

    out: dict[str, Any] = {"links": hops, "far_type_id": far_type}
    if aggregate is not None:
        out["aggregate"] = aggregate

    prop = raw.get("property")
    if aggregate == "count":
        # p.146: "For Count aggregation, you do not need to select a property
        # as objects are automatically counted." Carrying one anyway is two
        # intentions, and guessing which was meant is worse than asking.
        if prop is not None:
            raise DerivationError(
                f"{property_name}: a count needs no property - it counts objects"
            )
    else:
        if not isinstance(prop, str) or not prop.strip():
            raise DerivationError(
                f"{property_name}: choose which property of the linked object "
                "to derive"
            )
        out["property"] = prop.strip()

    if "limit" in raw and raw["limit"] is not None:
        if aggregate not in COLLECTORS:
            raise DerivationError(
                f"{property_name}: a limit applies to collect_list and "
                "collect_set, which are the only aggregations that collect"
            )
        limit = raw["limit"]
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise DerivationError(f"{property_name}: limit must be a whole number above 0")
        if limit > MAX_LIMIT:
            raise DerivationError(f"{property_name}: limit must be at most {MAX_LIMIT}")
        out["limit"] = limit
    elif aggregate in COLLECTORS:
        out["limit"] = DEFAULT_LIMIT
    return out


def _chain(
    raw: Any,
    *,
    property_name: str,
    link_types: dict[str, dict[str, Any]],
    object_type_id: str,
) -> tuple[list[dict[str, str]], str, bool]:
    """The link chain, walked from the object type this property is on.

    Returns the normalised hops, the type at the far end, and whether any hop
    can reach more than one object. **The direction is derived, not declared**:
    a link touches this type from exactly one end, so naming the direction as
    well would be a second statement of the same fact, free to disagree with
    migration 0027's join.
    """
    if not isinstance(raw, list) or not raw:
        raise DerivationError(
            f"{property_name}: a derived property needs at least one link to follow"
        )
    if len(raw) > MAX_HOPS:
        raise DerivationError(
            f"{property_name}: at most {MAX_HOPS} links can be followed "
            f"({len(raw)} given)"
        )

    here = str(object_type_id)
    hops: list[dict[str, str]] = []
    many = False
    for index, hop in enumerate(raw):
        where = f"{property_name}: link {index + 1}"
        link_id = hop.get("link_type_id") if isinstance(hop, dict) else hop
        if not isinstance(link_id, str) or link_id not in link_types:
            raise DerivationError(f"{where}: this workspace has no such link type")
        link = link_types[link_id]
        from_id = str(link["from_object_type_id"])
        to_id = str(link["to_object_type_id"])
        if here == from_id:
            far, outbound = to_id, True
        elif here == to_id:
            far, outbound = from_id, False
        else:
            raise DerivationError(
                f"{where}: {link['display_name']!r} does not touch the object "
                "type this chain has reached"
            )
        if not link.get("from_property") or not link.get("to_property"):
            # A link type can be defined and not traversable (db 0027). There
            # is nothing to follow, so there is nothing to derive.
            raise DerivationError(
                f"{where}: {link['display_name']!r} has no join, so nothing "
                "can be followed along it"
            )
        many = many or _reaches_many(str(link["cardinality"]), outbound=outbound)
        hops.append({"link_type_id": link_id, "far_type_id": far})
        here = far
    return hops, here, many


def _reaches_many(cardinality: str, *, outbound: bool) -> bool:
    """Whether following this link *in this direction* can land on more than
    one object.

    **`one_to_many` is named from the `to` side**, and getting that backwards
    is the kind of mistake that produces a plausible answer: this repo's links
    put the foreign key on the `from` side (db 0027), so many `from` rows point
    at one `to` row. `works_in` is from Person to Department with the
    department id on the person - many people, one department. So the "many"
    is reached travelling **inbound**, from the `to` end back to the `from`
    end, and travelling outbound lands on exactly one.

    Written the other way round first, and three tests caught it: a department
    would have been allowed to derive "employee salary" with no aggregation,
    which is a single cell asked to hold every employee's salary.

    `many_to_many` reaches many either way; `one_to_one` never does.
    """
    if cardinality == "many_to_many":
        return True
    if cardinality == "one_to_many":
        return not outbound
    return False


def check_compatible(prop: dict[str, Any], *, property_name: str) -> None:
    """p.148's own list of what a derived property cannot also be.

    Checked beside the shape rather than inside it, because each of these is a
    fact about the *property* rather than about the derivation - and each would
    otherwise be a setting that quietly does nothing to a value nobody stores.
    """
    if prop.get("required"):
        # p.148: "Derived properties cannot be marked as required
        # (non-nullable)." Nothing writes one, so nothing could ever satisfy
        # the requirement - the sync report and the action check would both be
        # asking a question with no answer.
        raise DerivationError(
            f"{property_name}: a derived property cannot be required - "
            "nothing writes it, so nothing could satisfy the rule"
        )
    if prop.get("value_format") is not None or prop.get("conditional_format"):
        # p.148: "Derived properties cannot have rule set bindings or base
        # formatters."
        raise DerivationError(
            f"{property_name}: a derived property cannot carry formatting"
        )
    if prop.get("edit_only"):
        # Not p.148's, but the same kind of contradiction and ours to state:
        # edit-only means "written by an action, stored on the instance", and
        # derived means "written by nothing, stored nowhere".
        raise DerivationError(
            f"{property_name}: a property cannot be both edit-only and derived"
        )
