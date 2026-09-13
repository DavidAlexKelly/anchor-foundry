"""Where an object dropdown's objects come from (§333; db 0085;
`action-types` p.34, p.36-37).

    "A Search Around would create a new set by traversing a link on every
     object in the current set. For example, `Github Issue of Current Employee`
     would take the `Employees` in the current set and create a resulting set
     of `Github Issues` linked to those `Employees`." (p.37)

    "The starting set for the query is set to all objects of the object type by
     default, but this can be changed to any other type. The starting set could
     also be set to an `ObjectReference` list parameter." (p.36)

**db 0084's filters narrow a set; this says which set.** Until §333 the answer
was always p.36's default — every object of the parameter's declared type — and
p.37's example cannot be written as a filter at all. "The Github Issues of
*this* Employee" is not a property comparison; it is a walk, and the thing being
walked from is a value in the form.

**A source compiles into the same nested `ObjectSet` a Workshop variable
builds**, which is the whole implementation: `Traversal` has been the shape of
a hop since §155, `object_set_eval.resolve_traversal` has evaluated one against
both stores since then, and p.37 asks for nothing that is not already there. A
hop resolver written beside the action code would be a set whose members this
dropdown and the object-set editor could disagree about.

**The chain's landing type is not stored as a promise, it is checked against
one.** `object_type_id` (db 0083) says what the parameter holds; the walk says
where it arrives; if they differ the definition is refused at save time rather
than producing a dropdown of the wrong objects. Same refusal §156 makes for a
traversal's link/landing pair and `derived_properties` for a derivation's.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from . import object_sets
from .action_filters import Unresolved

#: p.36's two ways to start. `object_type` is its "all objects of the object
#: type… changed to any other type"; `parameter` is its "could also be set to an
#: ObjectReference list parameter", read here as the single object reference
#: this build has — which is what makes p.37's own example ("of Current
#: Employee") expressible. p.36's list parameter is a named ○: this platform has
#: no list-valued parameter to point at yet.
START_KINDS = ("object_type", "parameter")

#: How many links one dropdown may walk. `object_sets`' own bound, not a second
#: number: every hop here becomes a `Traversal`, and `parse` refuses a set
#: deeper than this anyway — so a larger cap would be a promise overruled one
#: call down, which is the mistake §330 made with `MAX_CHOICES`.
MAX_HOPS = object_sets.MAX_TRAVERSALS


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def source_of(parameter: dict[str, Any]) -> dict[str, Any] | None:
    """The search-around document on one parameter, or `None` for p.36's
    default.

    `None` and `{}` mean the same thing and both arrive: NULL is what db 0085
    writes for every parameter that predates it, and a dialog that saved an
    untouched panel could send the empty object.
    """
    raw = _json(parameter.get("dropdown_search_around"))
    return raw if isinstance(raw, dict) and raw else None


def hops_of(source: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [h for h in (source or {}).get("hops") or [] if isinstance(h, dict)]


def referenced_parameters(parameter: dict[str, Any]) -> list[str]:
    """Which parameters this dropdown's *source* reads.

    p.37's example reads one: the employee whose issues are being offered. It
    joins `action_filters.referenced_parameters` in what the form watches, and
    for the same reason — change the employee and the issues change.
    """
    source = source_of(parameter)
    start = (source or {}).get("start")
    if not isinstance(start, dict) or str(start.get("kind", "")) != "parameter":
        return []
    name = str(start.get("parameter", "")).strip()
    return [name] if name else []


def start_parameter(parameter: dict[str, Any]) -> str | None:
    """The parameter this dropdown walks *from*, or `None`.

    `referenced_parameters` in the singular, and separate from it because the
    two are asked by different people: the wire shape wants a list to merge with
    the filters', and `build`'s caller wants the one name whose value it has to
    turn into a key first.
    """
    named = referenced_parameters(parameter)
    return named[0] if named else None


def build(
    parameter: dict[str, Any],
    *,
    object_type_id: UUID,
    filters: tuple[object_sets.Filter, ...],
    start_key: str | None = None,
) -> object_sets.ObjectSet:
    """p.36's start and p.37's hops as one `ObjectSet`, with 0084's filters on
    the outermost.

    **The filters land on the result, not on the start**, which is p.34's
    sentence read in its own order: "filters and Search Arounds to limit the
    objects that show up in the dropdown". Both narrow what shows up, and what
    shows up is the far end. A filter applied to the starting set would be
    filtering Employees by a property of a Github Issue.

    Raises `Unresolved` when the start is a parameter nobody has filled in —
    `action_filters`' own exception rather than a second one, because the two
    are the same thing to a caller: the dropdown is empty, and the form says
    which box comes first. Two exception types would be two `except` clauses,
    free to drift into treating one as empty and the other as an error.

    **`start_key` is a primary key, and the form holds an instance id**, which
    is why the caller resolves it rather than this reading `bound` directly.
    §155's `PRIMARY_KEY_FILTER` is the only way a set can name one object, and
    the first draft here rooted the walk on the uuid out of the form — every
    dropdown came back empty, because no object's primary key is its own id.
    Keeping the lookup outside also keeps this function pure, which is what lets
    the whole of p.36-37's compilation be tested without a database.
    """
    source = source_of(parameter)
    if source is None:
        return object_sets.ObjectSet(object_type_id=object_type_id, filters=filters)

    start = source.get("start") or {}
    hops = hops_of(source)
    kind = str(start.get("kind", ""))

    if kind == "parameter":
        name = str(start.get("parameter", ""))
        if not start_key:
            raise Unresolved(name)
        # A set of exactly one object, reached by its key. §155 built
        # `PRIMARY_KEY_FILTER` for precisely this — a derived property is a
        # chain rooted at one object — and p.37's "of Current Employee" is the
        # same root with a value from the form instead of the row being read.
        set_so_far = object_sets.ObjectSet(
            object_type_id=UUID(str(start["object_type_id"])),
            filters=(object_sets.Filter(
                property=object_sets.PRIMARY_KEY_FILTER, op="eq",
                value=str(start_key),
            ),),
        )
    else:
        set_so_far = object_sets.ObjectSet(
            object_type_id=UUID(str(start["object_type_id"]))
        )

    for index, hop in enumerate(hops):
        # The last hop lands on what the parameter holds, which `check_source`
        # already refused a definition for getting wrong. Taken from
        # `object_type_id` rather than from the hop's own `far_type_id` so that
        # the two cannot disagree at evaluation time about a set that was saved
        # before somebody edited a link.
        landing = (
            object_type_id if index == len(hops) - 1
            else UUID(str(hop["far_type_id"]))
        )
        set_so_far = object_sets.ObjectSet(
            object_type_id=landing,
            filters=filters if index == len(hops) - 1 else (),
            via=object_sets.Traversal(
                link_type_id=UUID(str(hop["link_type_id"])), base=set_so_far
            ),
        )

    if not hops:
        # p.36's "changed to any other type" with nothing to walk. The start
        # *is* the result, so it carries the filters — and `check_source`
        # refuses this unless that type is the one the parameter holds, because
        # otherwise the dropdown would offer objects the submission refuses.
        return object_sets.ObjectSet(
            object_type_id=set_so_far.object_type_id, filters=filters
        )
    return set_so_far


def check_source(
    parameter: dict[str, Any],
    *,
    object_type_id: str | None,
    link_types: dict[str, dict[str, Any]],
    object_type_ids: set[str],
    parameters: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Refuse a source that could not build a dropdown, at save time.

    Returns the normalised document — the hops with their landing types worked
    out — or `None` for p.36's default. **Normalised rather than echoed**: the
    walk decides where each hop lands, so a caller's own `far_type_id` is
    checked and then replaced by the answer, which is the arrangement
    `derived_properties.parse` already uses and for the same reason (an API
    that cannot accept its own output back makes read-modify-write impossible).

    Every refusal here is a dropdown that would otherwise be empty, or wrong, in
    front of somebody who did not write it.
    """
    source = source_of(parameter)
    if source is None:
        return None
    name = str(parameter.get("api_name", ""))
    if object_type_id is None:
        raise ValueError(
            f"{name!r} has a search around but no object type - a walk needs to "
            "know where it is meant to land"
        )

    unknown = sorted(k for k in source if k not in ("start", "hops"))
    if unknown:
        raise ValueError(
            f"{name!r}: unknown search-around option {', '.join(unknown)}"
        )

    start = source.get("start")
    if not isinstance(start, dict):
        raise ValueError(f"{name!r}: a search around needs a starting set")
    kind = str(start.get("kind", ""))
    if kind not in START_KINDS:
        raise ValueError(
            f"{name!r}: a starting set is one of {' or '.join(START_KINDS)}, "
            f"not {kind!r}"
        )
    start_type = str(start.get("object_type_id") or "")
    here = start_type
    if here not in object_type_ids:
        raise ValueError(
            f"{name!r}: the starting set names an object type this workspace "
            "does not have"
        )
    if kind == "parameter":
        read = str(start.get("parameter", ""))
        if read == name:
            raise ValueError(f"{name!r}: its starting set reads {name!r} itself")
        other = next(
            (p for p in parameters if str(p.get("api_name")) == read), None
        )
        if other is None:
            raise ValueError(
                f"{name!r}: its starting set reads {read!r}, which is not a "
                "parameter of this action"
            )
        if str(other.get("data_type")) != "object":
            # p.36 says an *ObjectReference* parameter. Starting from a string
            # would mean treating whatever somebody typed as an object's key,
            # and the dropdown would be empty for every value but one.
            raise ValueError(
                f"{name!r}: its starting set reads {read!r}, which holds a "
                f"{other.get('data_type')} rather than an object"
            )
        if str(other.get("object_type_id") or "") != here:
            raise ValueError(
                f"{name!r}: its starting set walks from a different object type "
                f"than {read!r} holds"
            )

    raw_hops = source.get("hops")
    if raw_hops is not None and not isinstance(raw_hops, list):
        raise ValueError(f"{name!r}: hops must be a list of links to follow")
    raw_hops = raw_hops or []
    if len(raw_hops) > MAX_HOPS:
        raise ValueError(
            f"{name!r}: a dropdown may follow at most {MAX_HOPS} links and this "
            f"one follows {len(raw_hops)} - each hop evaluates the set below it"
        )

    walked: list[dict[str, str]] = []
    for index, hop in enumerate(raw_hops, start=1):
        link_id = hop.get("link_type_id") if isinstance(hop, dict) else hop
        if not isinstance(link_id, str) or link_id not in link_types:
            raise ValueError(
                f"{name!r}: hop {index} names a link type this workspace does "
                "not have"
            )
        link = link_types[link_id]
        reached = object_sets.far_end(link, here=here)
        if reached is None:
            raise ValueError(
                f"{name!r}: hop {index} follows {link['display_name']!r}, which "
                "does not touch the object type this walk has reached"
            )
        far, _outbound = reached
        if not link.get("from_property") or not link.get("to_property"):
            # A link type can be defined and not traversable (db 0027). There is
            # nothing to follow, so there is nothing to offer.
            raise ValueError(
                f"{name!r}: hop {index} follows {link['display_name']!r}, which "
                "has no join, so nothing can be followed along it"
            )
        declared = hop.get("far_type_id") if isinstance(hop, dict) else None
        if declared is not None and str(declared) != far:
            raise ValueError(
                f"{name!r}: hop {index} lands on a different object type than "
                "it declares"
            )
        walked.append({"link_type_id": link_id, "far_type_id": far})
        here = far

    if here != str(object_type_id):
        # **The refusal this whole function exists for.** A walk that lands
        # anywhere else offers objects the parameter cannot hold, and p.34's
        # own validation would refuse every one of them a moment after somebody
        # picked one — §214's control that looks like it works, with the extra
        # insult of having offered the value it then rejects.
        raise ValueError(
            f"{name!r}: this walk lands on a different object type than the "
            "parameter holds"
        )
    # Rebuilt field by field rather than echoed with `**start`: a document that
    # carried an extra key would be stored and then read back by `build`, which
    # is how a setting nobody validated ends up deciding something.
    normalised: dict[str, Any] = {"kind": kind, "object_type_id": start_type}
    if kind == "parameter":
        normalised["parameter"] = str(start.get("parameter", ""))
    return {"start": normalised, "hops": walked}
