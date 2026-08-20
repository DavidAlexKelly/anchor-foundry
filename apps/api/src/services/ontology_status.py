"""Ontology resource statuses (Foundry ``object-link-types`` p.253-259).

> "Every object type, property, link type, action, or interface in the Ontology
> has a status that indicates developmental state… Status metadata helps
> Ontology-editing users to know what resources are being actively relied on by
> user applications." (p.253)

**A status is a promise about stability, and the rules are what make it one.**
p.256 is explicit that an `active` resource cannot be deleted and cannot have
its API name changed - so the status is not a label, it is the thing that turns
"applications depend on this" into a refusal. A status column with no refusals
behind it would be the shape of gap this repo's standard is written against.

Two rule sets live here, both pure so they can be tested without a database.

**Deletion (p.256).** "A resource's status must be `experimental` or
`deprecated` before it can be deleted." `promoted` inherits `active`'s
protections (p.255), and `example` is not on p.256's list of deletable states -
so the deletable set is exactly the two named.

**Propagation (p.256-257), and its one deliberate asymmetry.** Statuses cascade
*downwards* into a resource's parts and *sideways* into the link types that
depend on it, but only in the direction that prevents an invalid state:

* an object type becoming `experimental` or `example` takes its properties with
  it (p.256, p.258);
* a link type is dragged down by either of its object types, and by its foreign
  key property (p.257);
* but marking a property `active` **does not** promote its link type, and p.257
  says why in its own words: "it is valid for a foreign key property to be in
  production, while the link type and its backing datasource are still in
  development".

That asymmetry is the whole design. Cascading both ways would let one edit
quietly declare a half-built link type production-ready.
"""
from __future__ import annotations

from typing import Any

#: p.254's five, in increasing order of "applications may rely on this". The
#: order is load-bearing: `weakest` picks the lowest of several, which is how
#: p.257's table is expressed without writing the table out.
STATUSES = ("deprecated", "example", "experimental", "active", "promoted")

#: p.256: "By default, any new ontological resource will be given the
#: `experimental` status."
DEFAULT_STATUS = "experimental"

#: p.256: "A resource's status must be `experimental` or `deprecated` before it
#: can be deleted." `promoted` inherits `active`'s protections (p.255), and
#: `example` is simply not on the list.
DELETABLE = ("experimental", "deprecated")

#: p.255: `promoted` "applies only to object types. It is not available for
#: properties, link types, action types or interfaces."
OBJECT_TYPE_ONLY = ("promoted",)

#: p.255's permission sentence, as this platform spells it.
#:
#: > "Only users with the `Ontology Owner` role on the ontology level can
#: > directly apply the `promoted` status." (p.255)
#:
#: **A workspace is this platform's ontology** (db 0003), and `workspace_role`
#: already has a tier above editor - so "the ontology level" is a role this
#: platform has rather than one it needs. Foundry's own Ontology-roles chapter
#: (`ontology-manager` p.43) is marked legacy and superseded by "the Compass
#: filesystem", which is its project/folder permission system; building a
#: per-resource role registry here would have been replicating the model
#: Palantir is migrating off, when the platform already has the shape they
#: moved to.
#:
#: The divergence worth naming: our admin is workspace-wide, where Foundry's
#: Ontology Owner is per resource. Nobody can promote who could not already
#: administer the whole ontology, which is stricter, not looser.
PROMOTION_ROLE = "admin"


class StatusError(ValueError):
    """A status change, or a delete, that the ontology will not allow."""


def check_status(status: str, *, kind: str) -> str:
    """Validate one status for one kind of resource, or refuse it by name."""
    if status not in STATUSES:
        raise StatusError(
            f"invalid status {status!r}; expected one of {', '.join(STATUSES)}"
        )
    if status in OBJECT_TYPE_ONLY and kind != "object_type":
        raise StatusError(
            f"{status!r} applies only to object types (p.255), not to a {kind}"
        )
    return status


def rank(status: str) -> int:
    return STATUSES.index(status)


def weakest(*statuses: str) -> str:
    """The least production-ready of several (p.257's table, as a function).

    p.257 gives a grid of link type statuses by the statuses of the two object
    types it joins, and every cell in it is "whichever of the two is lower" -
    an `active` type joined to an `experimental` one gives `experimental only`.
    Writing the grid out would be writing an ordering out twice.
    """
    return min(statuses, key=rank)


def check_deletable(status: str, *, kind: str, name: str) -> None:
    """p.256: an `active` (or `promoted`) resource cannot be deleted.

    The refusal names what to do about it, because "cannot delete" without
    "mark it deprecated first" is a dead end rather than a step.
    """
    if status not in DELETABLE:
        raise StatusError(
            f"{name!r} is {status} and cannot be deleted - mark it deprecated "
            "or experimental first (p.256)"
        )


def parse_deprecation(raw: Any, status: str) -> dict[str, Any] | None:
    """p.254's deprecation metadata: why, by when, and what replaces it.

    > "A deprecated resource also has metadata that includes: A description for
    > why it is being deprecated; A deadline for when it is expected to be
    > deleted from the system; and The resource that is meant to replace the one
    > that is deprecated." (p.254)

    **Only meaningful on a deprecated resource**, and refused elsewhere: a
    deadline on an `active` object type is a date nothing will ever act on, and
    somebody reading it would reasonably believe otherwise. Cleared rather than
    refused when the status moves *away* from deprecated - that is somebody
    un-deprecating something, and keeping the old reason would leave a resource
    explaining why it was going to be deleted.
    """
    if status != "deprecated":
        if raw:
            raise StatusError(
                "deprecation details apply only to a deprecated resource (p.254)"
            )
        return None
    if raw is None:
        # p.256 prompts for these but does not require them, and a deprecation
        # somebody could not record because they had not picked a date yet is
        # a deprecation that does not get recorded.
        return None
    if not isinstance(raw, dict):
        raise StatusError("deprecation details must be an object")
    out: dict[str, Any] = {}
    reason = raw.get("reason")
    if reason is not None:
        if not isinstance(reason, str):
            raise StatusError("the deprecation reason must be text")
        out["reason"] = reason.strip()
    deadline = raw.get("deadline")
    if deadline is not None:
        if not isinstance(deadline, str):
            raise StatusError("the deprecation deadline must be an ISO date")
        from datetime import date

        try:
            date.fromisoformat(deadline[:10])
        except ValueError as exc:
            raise StatusError(
                f"{deadline!r} is not an ISO 8601 date (2026-01-31)"
            ) from exc
        out["deadline"] = deadline
    replacement = raw.get("replacement_id")
    if replacement is not None:
        out["replacement_id"] = str(replacement)
    return out or None


def propagate_to_properties(
    object_type_status: str, properties: list[dict[str, Any]]
) -> None:
    """Drag a type's properties down with it (p.256, p.258), in place.

    > "if an object type is changed from `active` to `experimental`, all of its
    > properties will be marked `experimental` as well." (p.256)
    > "When you change an object type to `example`, all of its properties will
    > automatically become `example` also." (p.258)

    **Downwards only, and `weakest` is the whole of that rule.** p.258 makes
    promoting the properties of a type becoming `active` an *option* ("there is
    the option to also apply the active status to all properties"), not a
    consequence - so a property deliberately left experimental on an otherwise
    finished type stays that way, and `weakest` cannot raise one.

    An earlier version also carried a list of "contagious" statuses and
    returned early for the rest. Mutation testing found it did nothing:
    `weakest` already refuses to raise, so adding `active` to that list changed
    no behaviour at all. Two spellings of one rule, and the redundant one was
    the one that could drift - so it is gone.
    """
    for prop in properties:
        current = str(prop.get("status") or DEFAULT_STATUS)
        prop["status"] = weakest(current, object_type_status)


def link_status(
    declared: str,
    *,
    from_status: str,
    to_status: str,
    from_property_status: str | None = None,
    to_property_status: str | None = None,
) -> str:
    """What a link type's status may actually be (p.257).

    > "If at least one object type in a link type is changed to `experimental`,
    > the link type will automatically be changed to `experimental`." …
    > "The same requirements are true of foreign keys of a link type." (p.257)

    Returns the strongest status the link may hold, which is the weakest of its
    own declaration and everything it depends on. A link type may always be
    *less* production-ready than its ends - p.257's own note that a foreign key
    can be in production while "the link type and its backing datasource are
    still in development" - so the declaration is a ceiling that its
    dependencies lower, never a floor they raise.
    """
    limits = [declared, from_status, to_status]
    limits += [s for s in (from_property_status, to_property_status) if s]
    return weakest(*limits)


def check_promotion(
    next_status: str, *, current_status: str, workspace_role: str
) -> None:
    """p.255: only the ontology level may apply `promoted`.

    > "Only users with the `Ontology Owner` role on the ontology level can
    > directly apply the `promoted` status. Other users must submit a proposal
    > for review and approval by an `Ontology Owner`." (p.255)

    **Gated on the transition, not on the value**, and that distinction is the
    whole of the function. The object type editor sends the whole definition on
    every save, so an editor pressing Save on an already-promoted type is
    sending `promoted` without asking for anything - refusing that would lock
    every editor out of every promoted type, turning p.255's protection into a
    trap that makes the most important object types uneditable by the people
    who build them.

    Demotion is deliberately not gated. p.255 restricts *applying* the status;
    stepping down from it is the safe direction, and `check_deletable` still
    stops a promoted type being deleted on the way past.

    The second half of p.255 - a proposal others may submit for approval - is
    not built. It needs a review surface for ontology changes, which is a
    feature rather than a rule, and one this refusal does not pretend to be.
    """
    if next_status not in OBJECT_TYPE_ONLY:
        return
    if next_status == current_status:
        return
    if workspace_role != PROMOTION_ROLE:
        raise StatusError(
            "only a workspace admin can promote an object type (p.255) - ask "
            "one to apply it, or choose active instead"
        )


def visibility_for(status: str, current: str) -> str:
    """What p.255's promotion does to an object type's visibility.

    > "Setting an object type's status to `promoted` will automatically set its
    > visibility to `prominent`, increasing its discoverability across the
    > platform." (p.255)

    **Raises and never lowers**, which is the same asymmetry
    `propagate_to_properties` has and for a related reason: p.255 describes
    what promoting *does*, and says nothing about demoting undoing it. A type
    somebody deliberately made prominent should not quietly stop being so
    because its status stepped down - that is a second decision, and it is
    theirs to make.
    """
    if status == "promoted":
        return "prominent"
    return current
