"""Narrowing what an object parameter offers (§331; db 0084;
`action-types` p.33-36, p.40-41).

    "The object dropdown only shows objects where the specified property
     matches any of the provided values. The value can be statically defined by
     the user, inferred from another parameter, or a property of an Object
     Reference parameter. **If more than one value is provided to compare
     against, the result will be an OR operation.**" (p.36)

    "After configuring the filters, the action form will render a dropdown with
     only objects that match the filter. **The value selected is also validated
     before the action is executed.**" (p.34)

**A filter compiles into an object set, which is what p.41 says Foundry does
too** — "the object dropdown validation is converted into an object set". That
is not an implementation detail borrowed for convenience: this platform already
has one way to narrow a set of objects (`object_sets.ObjectSet`), it runs
against both stores identically, and a second narrowing written here would be
free to disagree with it. p.36's OR over values is `in`; p.36's several filters
narrowing together is what a tuple of `Filter` already means.

**The dropdown and the refusal are the same set, evaluated twice.** p.34 says
both in one sentence, and §330 built the second half against the parameter's
*type*; this adds the filter to both, so "only objects that match" and
"validated before the action is executed" cannot come apart. A form that
narrowed the list without narrowing the check would offer a short list and
accept anything, which is §214's control that looks like it works.

**A filter that cannot be resolved yet yields nothing rather than everything.**
p.36 lets a value come from another parameter, so a filter can reference
something nobody has filled in. Showing every object then would offer exactly
the ones the filter exists to exclude, and the submission would be refused a
moment later — so the dropdown is empty and the form says which parameter to
fill in first. The same reading fails the *check* closed: a value that cannot
be confirmed to be in the set is not a value we can accept.
"""
from __future__ import annotations

import json
from typing import Any

from . import object_sets

#: p.36's value kinds, as decision 0007 already spells them. A `value` is
#: p.36's "statically defined by the user"; a `parameter` is its "inferred from
#: another parameter". p.36's third — a property of an object-reference
#: parameter — is not here, and `docs/parity` carries it as a named ○ rather
#: than a silent gap.
VALUE_KINDS = ("value", "parameter")


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def filters_of(parameter: dict[str, Any]) -> list[dict[str, Any]]:
    """The filters declared on one parameter, as a list of documents."""
    declared = _json(parameter.get("dropdown_filters")) or []
    return [f for f in declared if isinstance(f, dict)]


def referenced_parameters(parameter: dict[str, Any]) -> list[str]:
    """Which parameters this one's filters read.

    What the form watches, and what the editor narrows its dropdown to. Sorted
    and deduplicated so it can key a query without the order of a document
    changing the answer.
    """
    named: set[str] = set()
    for entry in filters_of(parameter):
        for side in entry.get("values") or []:
            if not isinstance(side, dict):
                continue
            if str(side.get("kind", "")) != "parameter":
                continue
            name = str(side.get("parameter", "")).strip()
            if name:
                named.add(name)
    return sorted(named)


class Unresolved(Exception):
    """A filter that reads a parameter nobody has supplied yet.

    Named rather than returned as `None`, because the two callers need
    different things from it and neither wants to guess: the dropdown turns it
    into a sentence about which box to fill in first, and the check turns it
    into a refusal.
    """

    def __init__(self, parameter: str) -> None:
        super().__init__(parameter)
        self.parameter = parameter


def resolve(
    parameter: dict[str, Any],
    *,
    bound: dict[str, Any],
    property_types: dict[str, str],
) -> tuple[object_sets.Filter, ...]:
    """p.36's filters as this platform's object-set filters.

    Each filter becomes one `in` over the values it was given, which is p.36's
    OR; several filters stay several, which is p.36's narrowing. The property's
    declared type rides along because `Filter` carries it for the same reason
    it always has — the decision that a comparison is legal is made once,
    against the ontology the caller resolved.

    Raises `Unresolved` for the first parameter-valued side with nothing behind
    it. **Not "skip that value"**: dropping it would quietly widen an OR, and
    dropping the whole filter would quietly widen the set — both of which end
    with somebody picking an object the submission then refuses.
    """
    out: list[object_sets.Filter] = []
    for entry in filters_of(parameter):
        prop = str(entry.get("property", "")).strip()
        if not prop:
            continue
        values: list[Any] = []
        for side in entry.get("values") or []:
            if not isinstance(side, dict):
                continue
            kind = str(side.get("kind", ""))
            if kind == "value":
                values.append(side.get("value"))
            elif kind == "parameter":
                name = str(side.get("parameter", ""))
                held = bound.get(name)
                if held is None or held == "":
                    raise Unresolved(name)
                values.append(held)
        if not values:
            # A filter with a property and no values narrows to nothing, which
            # would be a dropdown that is empty for a reason nobody chose.
            # `check_filters` refuses this at save time; here it is skipped so
            # a document that predates that refusal does not empty a form.
            continue
        out.append(object_sets.Filter(
            property=prop, op="in", value=values,
            data_type=property_types.get(prop),
        ))
    return tuple(out)


def check_filters(
    parameter: dict[str, Any],
    *,
    declared_properties: set[str],
    parameter_names: set[str],
) -> None:
    """Refuse a filter that could not narrow anything, at save time.

    Every refusal here has the same justification the definition's others do:
    the alternative is a dropdown that is empty, or wrong, in front of somebody
    who did not write it.

    A filter on a property the parameter's object type does not have is the
    common one — a filter is written against the *offered* type, not the
    action's own, and those are easy to confuse because for most of this
    platform's history they were the same thing.
    """
    name = str(parameter.get("api_name", ""))
    for index, entry in enumerate(filters_of(parameter), start=1):
        prop = str(entry.get("property", "")).strip()
        if not prop:
            raise ValueError(f"filter {index} on {name!r} names no property")
        if prop not in declared_properties:
            raise ValueError(
                f"filter {index} on {name!r} reads {prop!r}, which is not a "
                "property of the object type this parameter offers"
            )
        sides = [s for s in (entry.get("values") or []) if isinstance(s, dict)]
        if not sides:
            raise ValueError(
                f"filter {index} on {name!r} has no values to match against"
            )
        for side in sides:
            kind = str(side.get("kind", ""))
            if kind not in VALUE_KINDS:
                raise ValueError(
                    f"filter {index} on {name!r} has a value of kind {kind!r}; "
                    f"this build offers {' and '.join(VALUE_KINDS)}"
                )
            if kind != "parameter":
                continue
            read = str(side.get("parameter", ""))
            if read == name:
                raise ValueError(
                    f"filter {index} on {name!r} reads {name!r} itself"
                )
            if read not in parameter_names:
                raise ValueError(
                    f"filter {index} on {name!r} reads {read!r}, which is not "
                    "a parameter of this action"
                )


def redact(parameter: dict[str, Any]) -> dict[str, Any]:
    """The parameter as somebody who may not edit the action sees it (p.40-41).

    p.40: "Static value filters in object dropdown validations are exposed to
    all users who can view the action type. Use of these filters risks exposing
    property value combinations to users without permissions to view the
    filtered objects." Foundry's example is a filter naming an investigation,
    shown to people who cannot see a single document in it.

    p.41 gives the mitigation as redaction — "a user will not be able to see the
    new object dropdown filters in the action type definition in the interface
    or while inspecting the response in the backend" — and that is what this
    does. **The whole list goes, not just the static values.** A filter reduced
    to its properties still says "somebody is filtering Documents by
    Investigation Name", and p.40's concern is the combination.

    p.41 then admits the leak Foundry could not close: its form receives the
    filter as an object set, so "users could review the network request
    containing this object set". This platform's form never receives the filter
    — it asks for the resulting objects — so what is left after this redaction
    is nothing at all.
    """
    return {**parameter, "dropdown_filters": []}
