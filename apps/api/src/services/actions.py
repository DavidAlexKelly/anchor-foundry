"""Actions - write-back (spec: "Canvas buttons/forms writing back to object
instances → source datasets").

Scope, flagged for review: write-back targets this platform's own Parquet
copy of the mapped dataset (the same dataset the object type source points
at), not the customer's original external system reached through a
connection. Connectors in this build only support test/discover, not
write - true write-through to a live external table needs its own connector
capability and is out of scope here. Every write-back still creates a new
dataset_versions row (produced_by_kind='action'), exactly like
uploads/syncs/model runs - nothing is silently overwritten.

An action type is **parameters and rules** (decision 0007; Foundry
`action-types` p.25 and p.75): parameters are what the caller supplies,
rules are what the action does with them. Until migration 0044 it was one
list of property names playing both parts, which left nowhere to put an
input that is not literally a property being overwritten - and every
remaining feature in `docs/parity/ontology.md` §5 needs one.

Executing one (routes/actions.py orchestrates; this module holds the
DB-only primitives) still requires the property a rule writes to appear in
its source's column_mappings - only properties with a known dataset column
can be written back.
"""
from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import ConflictError, NotFoundError

_API_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,99}$")

# Imported at module level rather than inside a function: this is a
# constant, and the lazy `from . import ontology` elsewhere in this file
# exists to break an import cycle that the type *set* is not part of.
from .ontology import PROPERTY_TYPES as _ONTOLOGY_PROPERTY_TYPES  # noqa: E402


def bind_parameters(
    values: dict[str, Any], *, parameters: list[dict[str, Any]]
) -> dict[str, Any]:
    """What the caller supplied, checked against what the action declares.

    The *first* half of executing an action, and the half that knows nothing
    about objects: p.25's parameters "are treated like variables that contain
    external values", so this asks only whether each value was asked for and
    whether everything required is present. What any of it *does* is the
    rules' business, below.

    **Missing is not the same as absent.** An unsupplied parameter with a
    default takes the default (p.27); one without a default is simply not
    bound, and a rule reading it does nothing - which is how a partial submit
    kept working across migration 0044. Required parameters are the exception
    and are refused by name.
    """
    declared = {str(p["api_name"]): p for p in parameters}
    bound: dict[str, Any] = {}
    for name, value in values.items():
        if name not in declared:
            raise ValueError(f"{name!r} is not a parameter of this action")
        bound[name] = value
    for name, parameter in declared.items():
        if name in bound:
            continue
        default = parameter.get("default_value")
        if default is not None:
            # **Used as it comes back, not re-parsed.** The repo's defensive
            # `json.loads(x) if isinstance(x, str)` is a no-op for a jsonb
            # object or array and *wrong* for a jsonb scalar: the driver
            # decodes `"triaged"` to the Python string `triaged`, and parsing
            # that again fails with "Expecting value: line 1 column 1". A
            # default is the only jsonb in this codebase that is routinely a
            # scalar, which is why the convention held everywhere until here.
            bound[name] = default
        elif parameter.get("required"):
            raise ValueError(f"{name!r} is required by this action")
    return bound


def apply_rules(
    bound: dict[str, Any],
    *,
    rules: list[dict[str, Any]],
    property_types: dict[str, str],
    mapped_properties: set[str],
    link_types: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """What the rules write, given the bound parameters.

    The second half. p.75: "rules define the ways objects should change when
    the action is applied" - so this is the only place that turns an input
    into a property write, and the only place that has to care whether the
    property has a dataset column behind it.

    Returns the values *normalised* (roadmap Objects item 4): the type check
    is `ontology.coerce_property_value`, shared with the sync path, so a
    geopoint submitted as "51.5,-0.12" is stored in the same shape as one
    that arrived from a Parquet struct.

    An unknown property still defaults to "string" rather than raising: the
    caller resolved these names from the type moments ago, so a miss means
    the type changed underneath (§38 makes that possible), and refusing the
    *write* is a worse answer than checking it loosely.
    """
    from . import ontology as ontology_service

    writes: dict[str, Any] = {}
    writes_elsewhere = False
    for rule in sorted(rules, key=lambda r: (r.get("sort_order") or 0)):
        kind = str(rule["kind"])
        config = _json(rule.get("config")) or {}
        if kind in ("create_object", "delete_object"):
            # A different shape of write: `object_creations` adds a row and
            # `deletes_the_subject` removes one, and neither is a property
            # value this function can put in `writes`.
            continue
        if kind in ("create_link", "delete_link"):
            # **A link here is a property value, not a row** (migration 0027):
            # "which instances of the far type have `to_property` equal to this
            # instance's `from_property`". So creating one is writing that
            # foreign key and deleting one is clearing it - the same write a
            # `modify_object` makes, arrived at from the ontology's side rather
            # than the dataset's.
            link = (link_types or {}).get(str(config.get("link_type", "")))
            if link is None:
                raise ValueError("this action names a link type this workspace does not have")
            if config.get("object"):
                # The join property is on the *other* object, which a parameter
                # names - `object_modifications` writes it, for the same reason
                # a named modify goes there: a different row, in a source this
                # function was never given.
                writes_elsewhere = True
                continue
            prop = str(link["from_property"] or "")
            if prop in ("", "$primary_key"):
                # Rewriting a primary key is not linking, it is replacing the
                # object; and a link type with no properties has no foreign key
                # to write at all.
                raise ValueError(
                    "this link type cannot be set by an action - it joins on the primary key "
                    "or on nothing"
                )
            if prop not in mapped_properties:
                raise ValueError(
                    f"{prop!r} has no dataset column mapped on this instance's source"
                )
            if kind == "delete_link":
                writes[prop] = None
                continue
            parameter = str(config.get("target", ""))
            if parameter not in bound:
                continue  # nothing supplied, so nothing to link to
            writes[prop] = ontology_service.coerce_property_value(
                property_types.get(prop, "string"), bound[parameter]
            )
            continue
        if kind != "modify_object":
            # Three kinds left, and nothing can create one yet. Refusing loudly
            # beats writing nothing and reporting success, which is what a
            # silent `continue` would do the day one appears.
            raise ValueError(f"this build cannot apply a {kind!r} rule yet")
        prop = str(config.get("property", ""))
        parameter = str(config.get("parameter", ""))
        if config.get("object"):
            # A modify of an object a *parameter* names, not of the subject:
            # a different row, in a source this function was never given, so
            # `object_modifications` writes it. Remembered rather than merely
            # skipped, because the emptiness refusal below asks whether this
            # action wrote anything at all - and this rule did.
            if parameter in bound:
                writes_elsewhere = True
            continue
        if parameter not in bound:
            continue  # not supplied, no default - the rule has nothing to write
        if prop not in mapped_properties:
            raise ValueError(
                f"{prop!r} has no dataset column mapped on this instance's source"
            )
        writes[prop] = ontology_service.coerce_property_value(
            property_types.get(prop, "string"), bound[parameter]
        )
    if not writes and not writes_elsewhere and not any(
        str(r["kind"]) in ("create_object", "delete_object") for r in rules
    ):
        raise ValueError("submit at least one value to write")
    return writes


def object_deletions(
    bound: dict[str, Any], *, rules: list[dict[str, Any]], default_object_type_id: UUID
) -> list[dict[str, Any]]:
    """The objects this action removes (p.75).

    Two shapes, and the difference is which object is meant:

      * `{}` - the object the action was run against, which is what every
        `delete_object` rule meant before parameters could name another one;
      * `{"object_type": <id>, "object": <parameter>}` - an object *named by a
        parameter*, which is p.25's `object` parameter type finally resolving
        to something.

    Returns `{object_type_id, instance_id}` with `instance_id` None for the
    subject, because the caller already knows which instance that is and
    looking it up again would be a second answer to a settled question.
    """
    deletions: list[dict[str, Any]] = []
    for rule in sorted(rules, key=lambda r: (r.get("sort_order") or 0)):
        if str(rule["kind"]) != "delete_object":
            continue
        config = _json(rule.get("config")) or {}
        parameter = str(config.get("object", ""))
        if not parameter:
            deletions.append(
                {"object_type_id": str(default_object_type_id), "instance_id": None}
            )
            continue
        named = bound.get(parameter)
        if named is None or str(named).strip() == "":
            # Supplied nothing: not a deletion of nothing, which would be an
            # action reporting success for a row it never chose.
            raise ValueError(
                f"{parameter!r} names the object to delete and no value was supplied"
            )
        deletions.append({
            "object_type_id": str(config.get("object_type") or default_object_type_id),
            "instance_id": str(named),
        })
    return deletions


def modification_targets(
    bound: dict[str, Any],
    *,
    rules: list[dict[str, Any]],
    default_object_type_id: UUID,
    link_types: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """The objects, other than the subject, that this action's rules change.

    Read before anything is coerced, for the same reason `creation_targets` is:
    a property write has to be checked against the object type it lands on and
    the *source that instance actually came from*, and neither is known until
    the instance has been looked up. A create resolves its source from the
    type (there must be exactly one); a modify does not have to guess, because
    the instance already says which source it came from.

    Two rule shapes name an object here, and they say which type differently. A
    `modify_object` says it outright in `object_type`. A link rule written from
    the far side does not have to: the join property is on the link's *from*
    side, so the link type already names the type of the object being written,
    and letting the rule repeat it would be a second answer that could disagree.

    Returns `{object_type_id, instance_id}`, deduplicated - two rules setting
    two properties of the same named object are one object to look up.
    """
    targets: list[dict[str, Any]] = []
    for rule in sorted(rules, key=lambda r: (r.get("sort_order") or 0)):
        kind = str(rule["kind"])
        if kind not in ("modify_object", "create_link", "delete_link"):
            continue
        config = _json(rule.get("config")) or {}
        parameter = str(config.get("object", ""))
        if not parameter:
            continue  # the subject, which the caller already has
        named = bound.get(parameter)
        if named is None or str(named).strip() == "":
            # Same refusal `object_deletions` makes, for the same reason: an
            # action that writes nothing because nobody said which object is
            # indistinguishable from one that worked.
            raise ValueError(
                f"{parameter!r} names the object to change and no value was supplied"
            )
        if kind == "modify_object":
            type_id = str(config.get("object_type") or default_object_type_id)
        else:
            link = (link_types or {}).get(str(config.get("link_type", "")))
            if link is None:
                raise ValueError("this action names a link type this workspace does not have")
            type_id = str(link["from_object_type_id"])
        target = {"object_type_id": type_id, "instance_id": str(named)}
        if target not in targets:
            targets.append(target)
    return targets


def object_modifications(
    bound: dict[str, Any],
    *,
    rules: list[dict[str, Any]],
    contexts: dict[tuple[str, str], dict[str, Any]],
    default_object_type_id: UUID,
    link_types: dict[str, dict[str, Any]] | None = None,
    subject: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """The property writes this action makes to objects a parameter names (p.75).

    "Some object other than the one I was run against", for the two rule kinds
    that can mean one. A `modify_object` rule with an `object` in its config
    means *that* object rather than the subject; everything else about the rule
    is unchanged, which is why it is the same rule kind and not a fourth one.

    **A link rule with an `object` is the far side of migration 0027's
    derivation.** A link here is a property value: the *from* side holds
    `from_property` and instances of the *to* side match on `to_property`. A
    rule written on the from side sets its own row's foreign key, which
    `apply_rules` does. A rule written on the **to** side - this action's
    object type is the far end - can only link by writing the *other* object's
    foreign key, and the value it writes is not a parameter at all: it is this
    subject's `to_property`, because the link the rule creates is a link to
    *this* object. `delete_link` clears the same column. That is why these
    rules take an `object` and no `target`: the parameter says which object,
    and the subject says what to point it at.

    **Keyed by instance, not by type.** `object_creations` can key its contexts
    by object type because a new row has no source of its own yet and the type
    must have exactly one. A named object does have one, and two instances of a
    type can legitimately come from different sources with different column
    mappings - so the property this rule writes might be mapped on one and not
    the other. Checking against the type would answer the wrong question.

    Returns one entry per named object, `{object_type_id, instance_id,
    properties}`, with the rules' writes merged in `sort_order`. An entry whose
    properties all came from unsupplied parameters is dropped rather than
    returned empty: staging a dataset to write nothing to it would be a version
    in the history that says nothing happened.
    """
    from . import ontology as ontology_service

    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for rule in sorted(rules, key=lambda r: (r.get("sort_order") or 0)):
        kind = str(rule["kind"])
        if kind not in ("modify_object", "create_link", "delete_link"):
            continue
        config = _json(rule.get("config")) or {}
        parameter = str(config.get("object", ""))
        if not parameter:
            continue
        link = (link_types or {}).get(str(config.get("link_type", "")))
        if kind == "modify_object":
            type_id = str(config.get("object_type") or default_object_type_id)
        elif link is None:
            raise ValueError("this action names a link type this workspace does not have")
        else:
            type_id = str(link["from_object_type_id"])
        key = (type_id, str(bound[parameter]))
        context = contexts.get(key)
        if context is None:
            # Resolved by the caller, which had to find the instance to know
            # its source. Missing here means the caller and this function
            # disagree about which objects the rules name.
            raise ValueError("this action changes an object it could not resolve")
        if kind == "modify_object":
            value_parameter = str(config.get("parameter", ""))
            if value_parameter not in bound:
                continue  # not supplied, no default - nothing to write
            prop = str(config.get("property", ""))
            value = bound[value_parameter]
        else:
            prop = str(link["from_property"] or "")
            # **The subject supplies the value, so `to_property` is read here
            # and not by the caller.** A link to this object is that object's
            # foreign key holding this object's `to_property`; when the link
            # joins on identity, that is the primary key, which is not a
            # property and does not live in `properties`.
            to_property = str(link["to_property"] or "")
            value = (
                None if kind == "delete_link"
                else (subject or {}).get("primary_key") if to_property == "$primary_key"
                else ((subject or {}).get("properties") or {}).get(to_property)
            )
            if kind == "create_link" and value is None:
                # Nothing to point the other object at. Writing None anyway
                # would be a `delete_link` reporting itself as a create.
                raise ValueError(
                    "this object has no value for the property this link joins on, so "
                    "nothing can be linked to it"
                )
        if prop not in context["mapped_properties"]:
            raise ValueError(
                f"{prop!r} has no dataset column mapped on the source the object to "
                "change came from"
            )
        merged.setdefault(key, {})[prop] = (
            None if value is None
            else ontology_service.coerce_property_value(
                context["property_types"].get(prop, "string"), value
            )
        )
    return [
        {"object_type_id": type_id, "instance_id": instance_id, "properties": properties}
        for (type_id, instance_id), properties in merged.items()
        if properties
    ]


def changes_the_subject(rules: list[dict[str, Any]]) -> bool:
    """Whether any rule writes a property of the object the action ran on.

    Neither a link rule nor a `modify_object` does when it names another
    object: the foreign key a far-side link writes is on that object's row, not
    on this one's.
    """
    for rule in rules:
        kind = str(rule["kind"])
        if (_json(rule.get("config")) or {}).get("object"):
            continue
        if kind in ("create_link", "delete_link", "modify_object"):
            return True
    return False


def deletes_the_subject(rules: list[dict[str, Any]]) -> bool:
    """Whether any `delete_object` rule means the object the action ran on.

    Kept separate from `object_deletions` because the *contradiction* check -
    an action cannot both change and delete the same object - is about the
    subject only: changing one object and deleting another is an ordinary
    two-object action, not a contradiction.
    """
    return any(
        str(rule["kind"]) == "delete_object"
        and not (_json(rule.get("config")) or {}).get("object")
        for rule in rules
    )


def creation_targets(
    rules: list[dict[str, Any]], *, default_object_type_id: UUID
) -> list[str]:
    """Which object types this action's `create_object` rules write.

    Read before anything is resolved, because the route has to find each type's
    source in this project before it can coerce a single value - and a type
    with no source here is a refusal rather than a write.
    """
    targets: list[str] = []
    for rule in rules:
        if str(rule["kind"]) != "create_object":
            continue
        config = _json(rule.get("config")) or {}
        target = str(config.get("object_type") or default_object_type_id)
        if target not in targets:
            targets.append(target)
    return targets


def object_creations(
    bound: dict[str, Any],
    *,
    rules: list[dict[str, Any]],
    contexts: dict[str, dict[str, Any]],
    default_object_type_id: UUID,
) -> list[dict[str, Any]]:
    """The rows a `create_object` rule adds (Foundry p.75).

    The first rule kind that writes something other than the object the action
    was run against, and therefore the first one that needs decision 0008's
    boundary: an action with a modify *and* a create is two writes, and two
    writes have to land as one version or not at all.

    Config is `{"primary_key": <parameter>, "properties": {<property>:
    <parameter>}}` - the same property-to-parameter shape `modify_object` uses,
    because a create is a modify of a row that does not exist yet, plus the one
    thing a modify never needs.

    **The primary key is separate because it is not a property.** An object's
    identity lives in a *dataset column* named by its source's
    `primary_key_column`, and that column is frequently not mapped to any
    property at all - the fixture ticket type has `status` and `site` and no
    `ticket_id`. A create that could only set properties could therefore never
    give the new object an identity, which is exactly the shape of hole that
    only shows up when something real is written through it.

    **`contexts` carries one entry per target type** - its property types and
    the properties its source maps - because a rule creating another type's
    object must be checked against *that* type rather than against the one the
    action happens to hang off. `object_type` defaults to the action's own,
    which is what every rule written before cross-type creates still says.

    A property with no dataset column is refused for the same reason a modify
    refuses one: there is nowhere to put it, and a create that silently dropped
    half a row would be worse than one that did not happen.
    """
    from . import ontology as ontology_service

    creations: list[dict[str, Any]] = []
    for rule in sorted(rules, key=lambda r: (r.get("sort_order") or 0)):
        if str(rule["kind"]) != "create_object":
            continue
        config = _json(rule.get("config")) or {}
        target = str(config.get("object_type") or default_object_type_id)
        context = contexts.get(target)
        if context is None:
            # Resolved by the caller; missing means the type has no dataset in
            # this project, which is a refusal rather than a silent skip.
            raise ValueError(
                "this action creates an object of a type that has no dataset mapped in "
                "this project"
            )
        property_types = context["property_types"]
        mapped_properties = context["mapped_properties"]
        key_parameter = str(config.get("primary_key", ""))
        key = bound.get(key_parameter)
        if key is None or str(key).strip() == "":
            raise ValueError(
                "a create_object rule needs a value for the new object's primary key"
            )
        row: dict[str, Any] = {}
        for prop, parameter in (config.get("properties") or {}).items():
            prop, parameter = str(prop), str(parameter)
            if parameter not in bound:
                continue  # not supplied, no default - the column stays empty
            if prop not in mapped_properties:
                raise ValueError(
                    f"{prop!r} has no dataset column mapped on the source for its object type"
                )
            row[prop] = ontology_service.coerce_property_value(
                property_types.get(prop, "string"), bound[parameter]
            )
        creations.append(
            {"object_type_id": target, "primary_key": str(key), "properties": row}
        )
    return creations


class CriteriaRefusal(ValueError):
    """An action that may not be submitted, and the message saying why.

    Its own type because the caller has to tell it apart from a bad request:
    p.56's failure message "informs the user about why they are blocked", and
    surfacing "'status' is not a parameter of this action" in its place would
    be telling them about our schema instead of their situation.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


# p.54 and p.55's operator names, unchanged. A builder reading Foundry's table
# should find the same words here.
_SINGLE_VALUE_OPERATORS = frozenset(
    {"is", "is_not", "matches", "is_less_than", "is_greater_than_or_equals"}
)
_LIST_OPERATORS = frozenset({"includes", "is_included_in"})
CRITERION_OPERATORS = _SINGLE_VALUE_OPERATORS | _LIST_OPERATORS


def _side(spec: Any, *, bound: dict[str, Any], user: dict[str, Any]) -> Any:
    """One side of a comparison: a parameter, the current user, or a constant.

    p.50's two condition templates ("based on current user", "based on
    parameter") plus p.55's static value, which is the right-hand side of most
    real conditions.
    """
    spec = _json(spec) or {}
    kind = str(spec.get("kind", ""))
    if kind == "parameter":
        return bound.get(str(spec.get("parameter", "")))
    if kind == "current_user":
        # p.140: "Simple submission criteria can require a specific user ID or
        # group ID". Those are the two attributes we actually hold; a criterion
        # asking for any other one is unevaluable, and unevaluable fails.
        attribute = str(spec.get("attribute", "id"))
        if attribute not in ("id", "group_ids"):
            raise _Unevaluable(f"unknown current-user attribute {attribute!r}")
        return user.get(attribute)
    if kind == "value":
        return spec.get("value")
    if kind == "none":
        return None
    raise _Unevaluable(f"unknown condition side {kind!r}")


class _Unevaluable(Exception):
    """A condition that cannot be decided - a missing operator, a comparison
    between things that do not compare. Never a pass: see `_passes`."""


def _passes(condition: dict[str, Any], *, bound: dict[str, Any], user: dict[str, Any]) -> bool:
    left = _side(condition.get("left"), bound=bound, user=user)
    right_spec = _json(condition.get("right")) or {}
    operator = str(condition.get("operator", ""))

    # p.55: "No value checks whether the first value is empty (or null)." It is
    # a property of the *right* side rather than an operator of its own, which
    # is why `is` against no value reads as "is empty" and `is_not` as "is not
    # empty".
    if str(right_spec.get("kind", "")) == "none":
        empty = left is None or left == "" or left == [] or left == {}
        if operator == "is":
            return empty
        if operator == "is_not":
            return not empty
        raise _Unevaluable(f"{operator!r} cannot be used against no value")

    right = _side(right_spec, bound=bound, user=user)
    if operator not in CRITERION_OPERATORS:
        raise _Unevaluable(f"unknown operator {operator!r}")

    if operator == "is":
        return left == right
    if operator == "is_not":
        return left != right
    if operator == "matches":
        # p.54's regex operator. A pattern that does not compile is a
        # misconfiguration, and a misconfiguration must not grant access.
        import re as _re

        if not isinstance(left, str) or not isinstance(right, str):
            raise _Unevaluable("`matches` compares a string against a pattern")
        try:
            return _re.search(right, left) is not None
        except _re.error as exc:
            raise _Unevaluable(f"invalid pattern: {exc}") from exc
    if operator in ("is_less_than", "is_greater_than_or_equals"):
        # Numbers only, deliberately. Dates arrive as ISO-8601 text whose
        # ordering is lexicographic *only* when the offsets match, and a
        # comparison that is right in London and wrong in New York is worse
        # than one that refuses - especially in a check whose whole job is to
        # decide whether somebody may write.
        if isinstance(left, bool) or isinstance(right, bool):
            raise _Unevaluable("a boolean has no ordering")
        if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
            raise _Unevaluable("only numbers can be ordered by this build")
        return left < right if operator == "is_less_than" else left >= right
    if operator == "includes":
        # p.55: "At least one of the left values exactly matches the right
        # value." The left side is the list.
        if not isinstance(left, (list, tuple)):
            raise _Unevaluable("`includes` needs a list on the left")
        return right in left
    # is_included_in - p.55, the same check with the sides swapped.
    if not isinstance(right, (list, tuple)):
        raise _Unevaluable("`is_included_in` needs a list on the right")
    return left in right


def check_criteria(
    bound: dict[str, Any],
    *,
    criteria: list[dict[str, Any]],
    user: dict[str, Any],
) -> None:
    """Refuse the action unless every criterion holds (p.49-50).

    > "Actions can only be submitted if all the submission criteria are met."

    **Every row must pass, and an unevaluable criterion fails.** A condition
    the executor cannot decide - an operator it does not know, a comparison
    between things that do not compare - is a misconfiguration, and a
    misconfiguration in a check that governs *who may write* has exactly one
    safe direction. p.52 makes the same argument about NOT conditions against
    group membership: a condition that passes because an attribute is missing
    "grant[s] more access than intended".

    Raises `CriteriaRefusal` carrying the criterion's own failure message
    (p.56), which is the whole point of storing one.
    """
    for criterion in sorted(criteria, key=lambda c: (c.get("sort_order") or 0)):
        condition = _json(criterion.get("config")) or {}
        message = str(criterion.get("message") or "this action cannot be submitted")
        try:
            ok = _passes(condition, bound=bound, user=user)
        except _Unevaluable as exc:
            raise CriteriaRefusal(f"{message} (this criterion could not be checked: {exc})")
        if not ok:
            raise CriteriaRefusal(message)


async def criteria_user(conn: AsyncConnection, user_id: UUID) -> dict[str, Any]:
    """The submitting user, as a criterion can ask about them (p.140).

    Two attributes, because two are what Foundry's "simple submission criteria"
    need and two are what we can answer honestly: the user's id, and the ids of
    the groups they belong to. Foundry's other multipass attributes
    (organisation, arbitrary markings) have no equivalent here, and
    `_side` refuses one rather than returning an empty list - a criterion that
    passed because we could not check it is p.52's exact warning.

    Group membership is read here rather than taken from the request, so a
    criterion cannot be satisfied by a client claiming a group.
    """
    rows = await fetch_all(
        conn,
        "SELECT group_id FROM group_members WHERE user_id = :uid",
        {"uid": str(user_id)},
    )
    return {"id": str(user_id), "group_ids": [str(r["group_id"]) for r in rows]}


def _json(value: Any) -> Any:
    """psycopg hands jsonb back as a decoded object; some fetch paths hand back
    the text. Both shapes reach here."""
    return json.loads(value) if isinstance(value, str) else value


def editable_properties_of(rules: list[dict[str, Any]]) -> list[str]:
    """The properties this action's rules write.

    **A projection of the rules, not a stored field.** It replaces the
    `editable_properties` column that migration 0044 dropped, and keeps two
    callers working unchanged: the ontology change-impact report (which asks
    "does an action write this property") and the Workshop `run_action`
    validation (which refuses an effect that names a property the action does
    not write). It stays what its name says - the properties written on **the
    action's own object** - so a `modify_object` naming another object is not
    in it: a `run_action` effect citing one of those properties would be citing
    a property of a different row, and the change-impact report would claim
    this action writes the subject's type when it writes a parameter's. A
    caller wanting "everything this action touches" needs the rules themselves.
    """
    return [
        str(_json(r.get("config")).get("property"))
        for r in sorted(rules, key=lambda r: (r.get("sort_order") or 0))
        if str(r["kind"]) == "modify_object"
        and _json(r.get("config")).get("property")
        and not _json(r.get("config")).get("object")
    ]


# ---- parameters and rules ----------------------------------------------------
_PARAMETER_COLUMNS = (
    "id, action_type_id, api_name, display_name, data_type, required, "
    "default_value, hidden, sort_order"
)


async def _parameters_for(
    conn: AsyncConnection, action_type_ids: list[str]
) -> dict[str, list[dict[str, Any]]]:
    """Every action type's parameters in one query rather than one each - the
    list endpoint returns a workspace's actions and a per-row fetch would make
    it N+1 for a page nothing paginates."""
    if not action_type_ids:
        return {}
    rows = await fetch_all(
        conn,
        f"SELECT {_PARAMETER_COLUMNS} FROM action_parameters "
        "WHERE action_type_id = ANY(CAST(:ids AS uuid[])) ORDER BY sort_order, api_name",
        {"ids": action_type_ids},
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["action_type_id"]), []).append(dict(row))
    return grouped


async def _rules_for(
    conn: AsyncConnection, action_type_ids: list[str]
) -> dict[str, list[dict[str, Any]]]:
    if not action_type_ids:
        return {}
    rows = await fetch_all(
        conn,
        "SELECT id, action_type_id, kind, config, sort_order FROM action_rules "
        "WHERE action_type_id = ANY(CAST(:ids AS uuid[])) ORDER BY sort_order",
        {"ids": action_type_ids},
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["action_type_id"]), []).append(dict(row))
    return grouped


async def _criteria_for(
    conn: AsyncConnection, action_type_ids: list[str]
) -> dict[str, list[dict[str, Any]]]:
    if not action_type_ids:
        return {}
    rows = await fetch_all(
        conn,
        "SELECT id, action_type_id, message, config, sort_order FROM action_criteria "
        "WHERE action_type_id = ANY(CAST(:ids AS uuid[])) ORDER BY sort_order",
        {"ids": action_type_ids},
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["action_type_id"]), []).append(dict(row))
    return grouped


async def _with_definition(
    conn: AsyncConnection, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """An action type is not usable without its parameters, rules and criteria,
    so they are never a separate fetch a caller could forget to make.

    Criteria especially: a caller that forgot the parameters would get an
    action that refuses everything, and one that forgot the criteria would get
    an action that permits everything.
    """
    ids = [str(r["id"]) for r in rows]
    parameters = await _parameters_for(conn, ids)
    rules = await _rules_for(conn, ids)
    criteria = await _criteria_for(conn, ids)
    return [
        {
            **row,
            "parameters": parameters.get(str(row["id"]), []),
            "rules": rules.get(str(row["id"]), []),
            "criteria": criteria.get(str(row["id"]), []),
        }
        for row in rows
    ]


# ---- action types (workspace-scoped) ----------------------------------------
async def list_action_types(
    conn: AsyncConnection, workspace_id: UUID, *, object_type_id: UUID | None = None
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"wid": str(workspace_id)}
    where = "at.workspace_id = :wid"
    if object_type_id is not None:
        where += " AND at.object_type_id = :tid"
        params["tid"] = str(object_type_id)
    rows = await fetch_all(
        conn,
        f"""
        SELECT at.id, at.object_type_id, ot.display_name AS object_type_name,
               at.api_name, at.display_name, at.description,
               at.created_at, at.updated_at
          FROM action_types at
          JOIN object_types ot ON ot.id = at.object_type_id
         WHERE {where}
         ORDER BY at.display_name
        """,
        params,
    )
    return await _with_definition(conn, [dict(r) for r in rows])


async def get_action_type(
    conn: AsyncConnection, workspace_id: UUID, action_type_id: UUID
) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        """
        SELECT at.id, at.object_type_id, ot.display_name AS object_type_name,
               at.api_name, at.display_name, at.description,
               at.created_at, at.updated_at
          FROM action_types at
          JOIN object_types ot ON ot.id = at.object_type_id
         WHERE at.id = :aid AND at.workspace_id = :wid
        """,
        {"aid": str(action_type_id), "wid": str(workspace_id)},
    )
    if row is None:
        raise NotFoundError("action type")
    return (await _with_definition(conn, [dict(row)]))[0]


async def create_action_type(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    object_type_id: UUID,
    api_name: str,
    display_name: str,
    description: str,
    editable_properties: list[str],
    created_by: UUID,
) -> dict[str, Any]:
    if not _API_NAME_RE.match(api_name):
        raise ValueError(f"invalid action api_name {api_name!r}")
    if not editable_properties:
        raise ValueError("an action must make at least one property editable")

    from . import ontology as ontology_service

    await ontology_service.get_type(conn, workspace_id, object_type_id)  # 404 if invisible
    known = {p["api_name"] for p in await ontology_service.list_properties(conn, object_type_id)}
    unknown = [p for p in editable_properties if p not in known]
    if unknown:
        raise ValueError(f"not properties of this object type: {', '.join(unknown)}")

    existing = await fetch_one(
        conn,
        "SELECT 1 AS x FROM action_types WHERE object_type_id=:tid AND api_name=:api",
        {"tid": str(object_type_id), "api": api_name},
    )
    if existing is not None:
        raise ConflictError(f"an action named {api_name!r} already exists on this object type")

    row = await fetch_one(
        conn,
        """
        INSERT INTO action_types (workspace_id, object_type_id, api_name, display_name,
                                  description, created_by)
        VALUES (:wid, :tid, :api, :name, :descr, :by)
        RETURNING id, object_type_id, api_name, display_name, description,
                  created_at, updated_at
        """,
        {
            "wid": str(workspace_id), "tid": str(object_type_id), "api": api_name,
            "name": display_name, "descr": description, "by": str(created_by),
        },
    )
    assert row is not None
    action_type_id = UUID(str(row["id"]))
    declared = await ontology_service.list_properties(conn, object_type_id)
    property_types = {p["api_name"]: p["data_type"] for p in declared}
    display_names = {p["api_name"]: p["display_name"] for p in declared}
    # **The same conversion migration 0044 ran**, in Python, and deliberately
    # so: one property per parameter, named after it, plus one `modify_object`
    # rule writing it back. Keeping the two in step is what makes
    # `{property: value}` and `{parameter: value}` the same wire shape, which
    # is what lets every saved Workshop `run_action` keep working. `required`
    # is false for the same reason it is false in the migration - submitting a
    # subset of an action's properties has always been legal.
    for order, prop in enumerate(dict.fromkeys(editable_properties)):
        await conn.execute(
            text(
                """
                INSERT INTO action_parameters
                    (action_type_id, api_name, display_name, data_type, required, sort_order)
                VALUES (:aid, :api, :name, CAST(:dtype AS action_parameter_type), false, :ord)
                """
            ),
            {
                "aid": str(action_type_id), "api": prop,
                "name": display_names.get(prop) or prop,
                "dtype": property_types.get(prop, "string"), "ord": order,
            },
        )
        await conn.execute(
            text(
                """
                INSERT INTO action_rules (action_type_id, kind, config, sort_order)
                VALUES (:aid, 'modify_object', CAST(:config AS jsonb), :ord)
                """
            ),
            {
                "aid": str(action_type_id),
                "config": json.dumps({"property": prop, "parameter": prop}),
                "ord": order,
            },
        )
    object_type = await ontology_service.get_type(conn, workspace_id, object_type_id)
    return {
        **(await _with_definition(conn, [dict(row)]))[0],
        "object_type_name": object_type["display_name"],
    }


async def delete_action_type(
    conn: AsyncConnection, workspace_id: UUID, action_type_id: UUID
) -> None:
    row = await fetch_one(
        conn,
        "DELETE FROM action_types WHERE id=:aid AND workspace_id=:wid RETURNING id",
        {"aid": str(action_type_id), "wid": str(workspace_id)},
    )
    if row is None:
        raise NotFoundError("action type")


# ---- action_runs bookkeeping --------------------------------------------------
async def open_run(
    conn: AsyncConnection,
    *,
    action_type_id: UUID,
    instance_id: UUID,
    dataset_id: UUID,
    requested_by: UUID,
    submitted_values: dict[str, Any],
) -> UUID:
    row = await fetch_one(
        conn,
        """
        INSERT INTO action_runs (action_type_id, instance_id, dataset_id,
                                 requested_by, submitted_values)
        VALUES (:atid, :iid, :did, :by, CAST(:vals AS jsonb))
        RETURNING id
        """,
        {
            "atid": str(action_type_id), "iid": str(instance_id), "did": str(dataset_id),
            "by": str(requested_by), "vals": json.dumps(submitted_values),
        },
    )
    assert row is not None
    return UUID(str(row["id"]))


async def close_run(
    conn: AsyncConnection,
    run_id: UUID,
    *,
    ok: bool,
    dataset_version: int | None,
    error: str | None,
) -> None:
    await conn.execute(
        text(
            """
            UPDATE action_runs
               SET status = :status, dataset_version = :version,
                   error = :error, finished_at = now()
             WHERE id = :id
            """
        ),
        {
            "status": "succeeded" if ok else "failed",
            "version": dataset_version,
            "error": error,
            "id": str(run_id),
        },
    )


async def list_runs(conn: AsyncConnection, action_type_id: UUID) -> list[dict[str, Any]]:
    return await fetch_all(
        conn,
        """
        SELECT id, instance_id, dataset_id, dataset_version, submitted_values,
               status, error, started_at, finished_at
          FROM action_runs
         WHERE action_type_id = :atid
         ORDER BY started_at DESC
         LIMIT 50
        """,
        {"atid": str(action_type_id)},
    )


# ---- editing the definition ---------------------------------------------------
# **`ontology.PROPERTY_TYPES` plus `object`**, built rather than typed out.
# The two enums overlapping is what `test_every_property_type_can_be_an_action
# _parameter` guards, and it caught exactly this drift when `time_series`
# arrived: a property type no parameter can hold is a property no action could
# ever write. `object` is the one word p.25 needs that the ontology has no use
# for - a parameter that takes a whole instance.
_PARAMETER_TYPES = frozenset(_ONTOLOGY_PROPERTY_TYPES | {"object"})
_RULE_KINDS = frozenset(
    {"modify_object", "create_object", "delete_object", "create_link", "delete_link"}
)
_USER_ATTRIBUTES = frozenset({"id", "group_ids"})


async def properties_by_type(
    conn: AsyncConnection, workspace_id: UUID
) -> dict[str, dict[str, str]]:
    """Every object type in the workspace, and its properties' declared types.

    One query rather than one per referenced type: a `create_object` rule can
    name any type in the workspace, and the validator has to check what it sets
    against *that* type rather than against the one the action hangs off.
    """
    rows = await fetch_all(
        conn,
        """
        SELECT ot.id AS object_type_id, p.api_name, p.data_type
          FROM object_types ot
          LEFT JOIN object_type_properties p ON p.object_type_id = ot.id
         WHERE ot.workspace_id = :wid
        """,
        {"wid": str(workspace_id)},
    )
    grouped: dict[str, dict[str, str]] = {}
    for row in rows:
        entry = grouped.setdefault(str(row["object_type_id"]), {})
        if row["api_name"]:
            entry[str(row["api_name"])] = str(row["data_type"])
    return grouped


async def link_types_for(
    conn: AsyncConnection, workspace_id: UUID
) -> dict[str, dict[str, Any]]:
    """Every link type in the workspace, by id.

    Read in one query and handed to both the validator and the executor,
    because a link rule is only meaningful against the link type it names - and
    the two would otherwise each grow their own lookup and their own idea of
    what "the from side" is.
    """
    rows = await fetch_all(
        conn,
        """
        SELECT id, from_object_type_id, to_object_type_id,
               from_property, to_property, cardinality
          FROM link_types
         WHERE workspace_id = :wid
        """,
        {"wid": str(workspace_id)},
    )
    return {str(row["id"]): dict(row) for row in rows}


async def parameter_usages(
    conn: AsyncConnection, workspace_id: UUID, action_type_id: UUID
) -> dict[str, list[str]]:
    """Which Workshop modules name which of this action's parameters.

    A saved `run_action` effect carries `{action, subject, values}` and the keys
    of `values` are parameter names (§127: the conversion made them the same
    words the old model used for properties). So renaming or removing a
    parameter breaks every module that names it, silently, at click time.

    §1.2a already refuses deleting a *variable* a layout uses, and this is the
    same refusal one table over. Returns `{parameter: [module name, ...]}`, so
    the message can say which module rather than only that one exists - the
    person who has to fix it is usually not the person who typed the rename.
    """
    rows = await fetch_all(
        conn,
        """
        SELECT ca.name, ca.definition
          FROM canvas_apps ca
         WHERE rls_project_workspace_id(ca.project_id) = :wid
        """,
        {"wid": str(workspace_id)},
    )
    target = str(action_type_id)
    usages: dict[str, list[str]] = {}
    for row in rows:
        document = _json(row["definition"]) or {}
        if not isinstance(document, dict):
            continue
        for event in (document.get("events") or {}).values():
            if not isinstance(event, dict):
                continue
            # `{trigger, effects: [{type, config}]}` - an event is a trigger and
            # a *list* of effects, so the action is two levels down. Reading
            # `event["config"]` finds nothing and reports no usages, which is
            # the shape of bug this refusal exists to prevent.
            for effect in event.get("effects") or []:
                if not isinstance(effect, dict) or str(effect.get("type", "")) != "run_action":
                    continue
                config = effect.get("config") or {}
                if not isinstance(config, dict) or str(config.get("action", "")) != target:
                    continue
                for name in (config.get("values") or {}):
                    modules = usages.setdefault(str(name), [])
                    if str(row["name"]) not in modules:
                        modules.append(str(row["name"]))
    return usages


def _validate_definition(
    *,
    parameters: list[dict[str, Any]],
    rules: list[dict[str, Any]],
    criteria: list[dict[str, Any]],
    property_types: dict[str, str],
    object_type_id: UUID,
    link_types: dict[str, dict[str, Any]],
    workspace_properties: dict[str, dict[str, str]],
) -> None:
    """Refuse a definition that could not be executed, at save time.

    Every check here has the same justification: the executor would refuse it
    later, at click time, in front of somebody who did not write it. §1.2a made
    that argument for Workshop variables and it is the same one.
    """
    seen: set[str] = set()
    for parameter in parameters:
        name = str(parameter.get("api_name", ""))
        if not _API_NAME_RE.match(name):
            raise ValueError(f"invalid parameter name {name!r}")
        if name in seen:
            raise ValueError(f"two parameters are both named {name!r}")
        seen.add(name)
        data_type = str(parameter.get("data_type", ""))
        if data_type not in _PARAMETER_TYPES:
            raise ValueError(f"parameter {name!r} has unknown type {data_type!r}")
        if not str(parameter.get("display_name") or "").strip():
            raise ValueError(f"parameter {name!r} needs a display name")

    for rule in rules:
        kind = str(rule.get("kind", ""))
        if kind not in _RULE_KINDS:
            raise ValueError(f"unknown rule kind {kind!r}")
        config = rule.get("config") or {}
        if kind == "create_object":
            # Checked here rather than at execute time, because every refusal
            # below is one somebody can still fix while they are looking at the
            # rule they typed.
            if str(config.get("primary_key", "")) not in seen:
                # Without one the rule can only produce a row with no identity,
                # and an object nobody can address is not a created object.
                raise ValueError(
                    "a create_object rule needs a `primary_key` naming a parameter"
                )
            properties = config.get("properties") or {}
            if not isinstance(properties, dict) or not properties:
                raise ValueError("a create_object rule needs at least one property to set")
            target = str(config.get("object_type") or object_type_id)
            target_properties = workspace_properties.get(target)
            if target_properties is None:
                raise ValueError(
                    "a create_object rule names an object type this workspace does not have"
                )
            for prop, parameter in properties.items():
                if str(parameter) not in seen:
                    raise ValueError(
                        f"a create_object rule reads {parameter!r}, which is not a parameter"
                    )
                if str(prop) not in target_properties:
                    raise ValueError(
                        f"a create_object rule sets {prop!r}, which is not a property of "
                        "the object type it creates"
                    )
            continue
        if kind in ("create_link", "delete_link"):
            link = (link_types or {}).get(str(config.get("link_type", "")))
            if link is None:
                raise ValueError("a link rule names a link type this workspace does not have")
            far_side = str(link["from_object_type_id"]) != str(object_type_id)
            if far_side and str(link["to_object_type_id"]) != str(object_type_id):
                raise ValueError(
                    "a link rule names a link type neither of whose ends is this action's "
                    "object type"
                )
            if far_side and not config.get("object"):
                # The foreign key lives on the *from* side. Written from the
                # **to** side there is no "this object's column" to set - the
                # rule can only write some *other* object's, and which one is
                # not a thing a link type knows. So the far side needs the
                # parameter that says which, and the near side must not have
                # one: on that side the rule already knows whose row it writes.
                raise ValueError(
                    "a link rule written from the side that does not hold the join property "
                    "needs an `object` naming the parameter that says which object to link"
                )
            if not far_side and config.get("object"):
                raise ValueError(
                    "a link rule from the side that holds the join property writes this "
                    "action's own object, so it cannot also name one"
                )
            if far_side and str(config.get("object")) not in seen:
                raise ValueError(
                    f"a link rule links {config.get('object')!r}, which is not a parameter"
                )
            if far_side and str(link["to_property"] or "") == "":
                # Nothing on this side to point the other object at.
                raise ValueError(
                    "this link type joins on nothing, so an action cannot set it"
                )
            if str(link["cardinality"]) == "many_to_many":
                # A many-to-many link cannot be expressed by one foreign key,
                # and this platform has no join table to put the second half
                # in. Refusing beats writing a value that means half a link.
                raise ValueError(
                    "a many-to-many link cannot be set by an action in this build"
                )
            if not link["from_property"] or str(link["from_property"]) == "$primary_key":
                raise ValueError(
                    "this link type joins on the primary key or on nothing, so an action "
                    "cannot set it"
                )
            if (
                kind == "create_link" and not far_side
                and str(config.get("target", "")) not in seen
            ):
                # Near side only. On the far side the value is not a parameter
                # at all - it is this object's `to_property`, because the link
                # the rule creates is a link *to this object*.
                raise ValueError(
                    "a create_link rule needs a `target` naming the parameter that supplies "
                    "the object to link to"
                )
            continue
        if kind == "delete_object":
            named = config.get("object")
            if named and str(named) not in seen:
                raise ValueError(
                    f"a delete_object rule reads {named!r}, which is not a parameter"
                )
            target = str(config.get("object_type") or object_type_id)
            if named and target not in workspace_properties:
                raise ValueError(
                    "a delete_object rule names an object type this workspace does not have"
                )
            if config.get("object_type") and not named:
                # An object type with no object names a *set*, and deleting a
                # set is not something p.75's simple rules express.
                raise ValueError(
                    "a delete_object rule naming an object type also needs the parameter "
                    "that says which object"
                )
            continue
        if kind != "modify_object":
            # Storable, so the schema and the editor agree, and refused by
            # `apply_rules` at execute time (§127). Refusing to *save* one
            # would make the table a lie about what it holds.
            continue
        parameter = str(config.get("parameter", ""))
        prop = str(config.get("property", ""))
        if parameter not in seen:
            raise ValueError(f"a rule reads {parameter!r}, which is not a parameter")
        named = config.get("object")
        if named and str(named) not in seen:
            raise ValueError(
                f"a modify_object rule changes {named!r}, which is not a parameter"
            )
        if config.get("object_type") and not named:
            # Same hole as `delete_object`: a type with no object names every
            # object of that type, and changing all of them is not a rule p.75
            # can express.
            raise ValueError(
                "a modify_object rule naming an object type also needs the parameter "
                "that says which object"
            )
        # **Checked against the type the property lands on.** For the subject
        # that is this action's object type; for a named object it is whatever
        # type the rule says, and using this action's would let a rule write a
        # property the target has never heard of.
        target_properties = (
            property_types if not named
            else workspace_properties.get(str(config.get("object_type") or object_type_id))
        )
        if target_properties is None:
            raise ValueError(
                "a modify_object rule names an object type this workspace does not have"
            )
        if prop not in target_properties:
            raise ValueError(
                f"a rule writes {prop!r}, which is not a property of "
                + ("this object type" if not named else "the object type it changes")
            )

    # Writing a property of a row and removing the row are not two things that
    # happen in some order - they are a contradiction, and the order they
    # happen to run in is not a specification. Refused where somebody can still
    # see both rules. Two objects are the same one here when the rules say the
    # same type and read the same parameter; two rules that *happen* to be
    # handed the same instance at click time are a coincidence, not a
    # definition, and refusing those would refuse a definition that is fine.
    def _named(rule: dict[str, Any]) -> tuple[str, str] | None:
        config = rule.get("config") or {}
        return (
            None if not config.get("object")
            else (
                str(config.get("object_type") or object_type_id),
                str(config.get("object")),
            )
        )

    named_deletes = {
        _named(rule) for rule in rules if str(rule.get("kind", "")) == "delete_object"
    } - {None}
    named_changes = {
        _named(rule) for rule in rules if str(rule.get("kind", "")) == "modify_object"
    } - {None}
    if (deletes_the_subject(rules) and changes_the_subject(rules)) or (
        named_deletes & named_changes
    ):
        raise ValueError(
            "an action cannot both change and delete the same object"
        )

    for criterion in criteria:
        if not str(criterion.get("message") or "").strip():
            # p.56: the failure message is what the blocked user is told. A
            # criterion without one refuses in silence.
            raise ValueError("every criterion needs a message saying why it refuses")
        config = criterion.get("config") or {}
        operator = str(config.get("operator", ""))
        if operator not in CRITERION_OPERATORS:
            raise ValueError(f"unknown criterion operator {operator!r}")
        for side in ("left", "right"):
            spec = config.get(side) or {}
            kind = str(spec.get("kind", ""))
            if kind == "parameter" and str(spec.get("parameter", "")) not in seen:
                raise ValueError(
                    f"a criterion reads {spec.get('parameter')!r}, which is not a parameter"
                )
            elif kind == "current_user" and str(spec.get("attribute", "id")) not in _USER_ATTRIBUTES:
                raise ValueError(
                    f"a criterion reads the current user's {spec.get('attribute')!r}, "
                    "which this build cannot answer"
                )
            elif kind not in ("parameter", "current_user", "value", "none"):
                raise ValueError(f"a criterion has an unknown {side} side {kind!r}")


async def set_definition(
    conn: AsyncConnection,
    workspace_id: UUID,
    action_type_id: UUID,
    *,
    parameters: list[dict[str, Any]],
    rules: list[dict[str, Any]],
    criteria: list[dict[str, Any]],
) -> dict[str, Any]:
    """Replace an action type's parameters, rules and criteria as one document.

    **Whole-document, not per-row.** The three lists constrain each other - a
    rule names a parameter, a criterion names a parameter - so a per-row API
    would have an ordering in which every sequence of individually valid edits
    passes through an invalid state. Saving the module document (decision 0002)
    is the same shape for the same reason.
    """
    from . import ontology as ontology_service

    action_type = await get_action_type(conn, workspace_id, action_type_id)
    object_type_id = UUID(str(action_type["object_type_id"]))
    property_types = {
        p["api_name"]: p["data_type"]
        for p in await ontology_service.list_properties(conn, object_type_id)
    }
    _validate_definition(
        parameters=parameters, rules=rules, criteria=criteria,
        property_types=property_types, object_type_id=object_type_id,
        link_types=await link_types_for(conn, workspace_id),
        workspace_properties=await properties_by_type(conn, workspace_id),
    )

    # **The refusal decision 0007 names.** Checked against what is *going*, not
    # what is arriving: a parameter that survives under a new name is, to every
    # saved module, a parameter that vanished.
    surviving = {str(p["api_name"]) for p in parameters}
    going = {str(p["api_name"]) for p in action_type["parameters"]} - surviving
    if going:
        usages = await parameter_usages(conn, workspace_id, action_type_id)
        broken = sorted((name, usages[name]) for name in going if name in usages)
        if broken:
            detail = "; ".join(
                f"{name!r} is used by {', '.join(repr(m) for m in modules)}"
                for name, modules in broken
            )
            raise ConflictError(
                f"this action's parameters are in use by a Workshop module: {detail}. "
                "Change the module first, or keep the parameter's name."
            )

    for table in ("action_parameters", "action_rules", "action_criteria"):
        await conn.execute(
            text(f"DELETE FROM {table} WHERE action_type_id = :aid"),
            {"aid": str(action_type_id)},
        )
    for order, parameter in enumerate(parameters):
        await conn.execute(
            text(
                """
                INSERT INTO action_parameters
                    (action_type_id, api_name, display_name, data_type, required,
                     default_value, hidden, sort_order)
                VALUES (:aid, :api, :name, CAST(:dtype AS action_parameter_type), :required,
                        CAST(:default AS jsonb), :hidden, :ord)
                """
            ),
            {
                "aid": str(action_type_id),
                "api": parameter["api_name"],
                "name": parameter["display_name"],
                "dtype": parameter["data_type"],
                "required": bool(parameter.get("required", False)),
                "default": (
                    None if parameter.get("default_value") is None
                    else json.dumps(parameter["default_value"])
                ),
                "hidden": bool(parameter.get("hidden", False)),
                "ord": order,
            },
        )
    for order, rule in enumerate(rules):
        await conn.execute(
            text(
                """
                INSERT INTO action_rules (action_type_id, kind, config, sort_order)
                VALUES (:aid, CAST(:kind AS action_rule_kind), CAST(:config AS jsonb), :ord)
                """
            ),
            {
                "aid": str(action_type_id), "kind": rule["kind"],
                "config": json.dumps(rule.get("config") or {}), "ord": order,
            },
        )
    for order, criterion in enumerate(criteria):
        await conn.execute(
            text(
                """
                INSERT INTO action_criteria (action_type_id, message, config, sort_order)
                VALUES (:aid, :message, CAST(:config AS jsonb), :ord)
                """
            ),
            {
                "aid": str(action_type_id), "message": criterion["message"],
                "config": json.dumps(criterion.get("config") or {}), "ord": order,
            },
        )
    return await get_action_type(conn, workspace_id, action_type_id)
