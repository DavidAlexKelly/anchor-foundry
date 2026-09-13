"""Narrowing what an object parameter offers (§331, §334; db 0084;
`action-types` p.33-36, p.40-41).

    "The object dropdown only shows objects where the specified property
     matches any of the provided values. **The value can be statically defined
     by the user, inferred from another parameter, or a property of an Object
     Reference parameter.** If more than one value is provided to compare
     against, the result will be an OR operation." (p.36)

**All three of p.36's value kinds as of §334.** The third reads through a
parameter rather than out of one — "the Teams in the region of the Office you
chose" — which is the only one of the three that compares against a value
nobody typed and no parameter holds.

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

#: p.36's three value kinds, all of them as of §334. A `value` is p.36's
#: "statically defined by the user", a `parameter` its "inferred from another
#: parameter", and an `object_property` its "or a property of an Object
#: Reference parameter".
#:
#: **`object_property` is spelled the way this platform already spells it** —
#: `notifications.RECIPIENT_KINDS` has had the same name for the same idea
#: since §257, and `workshop_variables` before that. One difference, and it is
#: db 0083's doing: a notify rule's recipient carries an `object_type` because
#: a parameter could not say what it held, and its docstring calls naming it
#: "a second convention for the same fact". §330 gave the parameter the column,
#: so a filter written today reads the type off the parameter and cannot
#: disagree with it.
VALUE_KINDS = ("value", "parameter", "object_property")


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
            # Both of p.36's parameter-reading kinds (§334). An
            # `object_property` value changes when its parameter does — the
            # whole point of "the region of the Office you chose" — so a form
            # that watched only the plain kind would narrow once and then stop.
            if str(side.get("kind", "")) not in ("parameter", "object_property"):
                continue
            name = str(side.get("parameter", "")).strip()
            if name:
                named.add(name)
    return sorted(named)


def object_property_reads(parameter: dict[str, Any]) -> list[tuple[str, str]]:
    """The `(parameter, property)` pairs p.36's third kind reads.

    What the caller has to load an object for before `resolve` can run — see
    that function on why the read is not in here.
    """
    pairs: set[tuple[str, str]] = set()
    for entry in filters_of(parameter):
        for side in entry.get("values") or []:
            if not isinstance(side, dict):
                continue
            if str(side.get("kind", "")) != "object_property":
                continue
            name = str(side.get("parameter", "")).strip()
            prop = str(side.get("property", "")).strip()
            if name and prop:
                pairs.add((name, prop))
    return sorted(pairs)


class Unresolved(Exception):
    """A filter that reads something nobody has supplied yet.

    Named rather than returned as `None`, because the two callers need
    different things from it and neither wants to guess: the dropdown turns it
    into a sentence about which box to fill in first, and the check turns it
    into a refusal.

    `property` is set only for p.36's third kind, and only when the box *is*
    filled in and the object it names has nothing under that property (§334).
    The two states need different sentences: "choose the Office first" is
    simply false to somebody who has chosen one, and a control that tells them
    to do what they have already done is §214 in words.
    """

    def __init__(self, parameter: str, *, property: str | None = None) -> None:
        super().__init__(parameter)
        self.parameter = parameter
        self.property = property


def resolve(
    parameter: dict[str, Any],
    *,
    bound: dict[str, Any],
    property_types: dict[str, str],
    objects: dict[str, dict[str, Any]] | None = None,
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

    `objects` is `{parameter: properties}` for p.36's third kind, loaded by the
    caller (§334). **The read is not in here** for the reason §333 gives about
    `start_key`: a form holds instance ids and this needs what is *inside* the
    object, which is a round trip — and keeping it outside is what lets the
    whole of p.36's compilation be tested without a database. The shape is
    `notifications.recipient_ids`' own `objects` argument, which has resolved
    "a property of an object parameter" the same way since §257.
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
            elif kind == "object_property":
                # p.36's third: "a property of an Object Reference parameter".
                name = str(side.get("parameter", ""))
                prop = str(side.get("property", ""))
                if bound.get(name) is None or bound.get(name) == "":
                    # Nobody has chosen the object yet, which is the same state
                    # a plain parameter reference is in and gets the same
                    # sentence: fill that box in first.
                    raise Unresolved(name)
                held = (objects or {}).get(name, {}).get(prop)
                if held is None or held == "":
                    # The box *is* filled in and the object has nothing there.
                    # Told apart from the case above because "choose the Office
                    # first" is false to somebody who has, and because
                    # filtering on the empty value would narrow to whichever
                    # objects also have nothing — a short list for a reason
                    # nobody chose.
                    raise Unresolved(name, property=prop)
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
    object_properties: dict[str, set[str]] | None = None,
) -> None:
    """Refuse a filter that could not narrow anything, at save time.

    Every refusal here has the same justification the definition's others do:
    the alternative is a dropdown that is empty, or wrong, in front of somebody
    who did not write it.

    A filter on a property the parameter's object type does not have is the
    common one — a filter is written against the *offered* type, not the
    action's own, and those are easy to confuse because for most of this
    platform's history they were the same thing.

    `object_properties` is `{parameter: its object type's property names}` for
    every *other* object parameter with a declared type, which is what p.36's
    third kind is checked against (§334). Its **absence is a refusal rather
    than a permission**, the rule `notifications.parse_notify` states one
    service over: a caller that has not resolved the ontology has checked no
    property.
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
            if kind == "value":
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
            if kind != "object_property":
                continue
            # p.36's third kind, and the two things only the ontology can
            # answer (§334). The type comes off the *parameter* rather than out
            # of the document, which is db 0083's whole point — see
            # `VALUE_KINDS` on why a notify rule still names one.
            offers = object_properties.get(read) if object_properties else None
            if offers is None:
                raise ValueError(
                    f"filter {index} on {name!r} reads a property of {read!r}, "
                    "which is not an object parameter with a declared type — "
                    "p.36's third kind needs to know which object type it is "
                    "reading from"
                )
            of = str(side.get("property", "")).strip()
            if not of:
                raise ValueError(
                    f"filter {index} on {name!r} reads {read!r} without saying "
                    "which of its properties"
                )
            if of not in offers:
                raise ValueError(
                    f"filter {index} on {name!r} reads {of!r} from {read!r}, "
                    "which is not a property of the object type that parameter "
                    "holds"
                )


def for_reader(parameter: dict[str, Any], *, may_edit: bool) -> dict[str, Any]:
    """The parameter as this caller sees it: p.40-41's redaction, and the one
    thing a redacted form still has to be told.

    p.40: "Static value filters in object dropdown validations are exposed to
    all users who can view the action type. Use of these filters risks exposing
    property value combinations to users without permissions to view the
    filtered objects." Foundry's example is a filter naming an investigation,
    shown to people who cannot see a single document in it.

    p.41 gives the mitigation as redaction — "a user will not be able to see the
    new object dropdown filters in the action type definition in the interface
    or while inspecting the response in the backend" — and that is what
    `dropdown_filters` becoming `[]` is. **The whole list goes, not just the
    static values.** A filter reduced to its properties still says "somebody is
    filtering Documents by Investigation Name", and p.40's concern is the
    combination.

    **`dropdown_watches` is why this is one function rather than two.** §331
    shipped the redaction alone, and the form works out which boxes to re-ask on
    by reading the filters — so for the people the redaction is *for*, p.36's
    "inferred from another parameter" stopped working entirely: fill in Region
    and the Team dropdown sits on "choose Region first" forever, because nothing
    told it Region mattered. That is §214's control that looks like it works,
    and it was invisible because every test of the loop ran as an editor. A
    redaction that can be applied without supplying the replacement is a
    redaction that will be, so the two are the same call and there is no
    `redact` to reach for.

    What the watch list gives away is a parameter *name* of the same action,
    which the reader already has in full — not a property, not a value, not a
    combination of the two. It says "this dropdown depends on that box", which
    is a fact the form's own behaviour states out loud the moment somebody
    types. Sent to the editor as well, so the browser has one source for it
    rather than one per role.

    p.41 then admits the leak Foundry could not close: its form receives the
    filter as an object set, so "users could review the network request
    containing this object set". This platform's form never receives the filter
    — it asks for the resulting objects — so what is left after this redaction
    is a list of names the reader could have written down themselves.
    """
    from .action_search_arounds import (
        referenced_parameters as source_reads,
        source_of,
    )

    # p.36-37's search around goes with the filters (§333): a walk names object
    # types and link types, and "somebody is offering the Documents linked to
    # this Investigation" is exactly p.40's combination. What the *start* reads
    # stays, for §332's reason — the form has to know which box makes the
    # dropdown change, and p.37's example changes on every one of them.
    watches = sorted({*referenced_parameters(parameter), *source_reads(parameter)})
    return {
        **parameter,
        "dropdown_watches": watches,
        "dropdown_filters": filters_of(parameter) if may_edit else [],
        "dropdown_search_around": source_of(parameter) if may_edit else None,
    }
