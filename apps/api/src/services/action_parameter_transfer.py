"""A parameter's dropdown, written by name rather than by id (§342;
`ontology-manager` p.65-67).

    "You can export your Ontology working state… Import… will recreate the
     entire working state from the JSON file." (p.66)

    "…copy the working state of one Ontology to another." (p.65)

**Three fields name other resources by id, and a portable document cannot.**
§341 carried everything on a parameter that names things by *name* — the
filters, the sections, the overrides. What was left is the part that points:

    db 0083  `object_type_id`           the type an object parameter holds
    db 0085  `dropdown_search_around`   the start, each hop's link, each landing
    db 0086  `options_from`             the type a multiple-choice set reads

An id from this workspace means nothing in the workspace a file is imported
into, which is the whole shape of §326's document — so each becomes an
api_name on the way out and an id again on the way back.

**Here rather than in `ontology_export`, for §339's reason.** The shape of a
hop is something only the action code defines, and a translator living beside
the exporter would be a second reader of it — free to drift the day a hop grows
a field. `action_search_arounds` and `action_options` own these documents;
this is their transfer form, and it is pure: dictionaries in, dictionaries out,
so the whole of it is decided without a database.

**And the inverse, which §344 gave a caller.** `to_ids` is what the import
resolves a parameter's dropdown with once the file's object types and link types
have been written, and the two directions are deliberately *not* symmetric about
failure: outward, a reference this ontology cannot name is left out, because a
document carrying an id would look portable and be meaningless anywhere; inward,
a name this workspace does not have is **refused**, because leaving it out would
write a parameter with no dropdown and report the file as applied. The file said
something; the workspace would have got something else, and nobody would be told.

Nothing resolvable reaches `to_ids` in practice — `check_references` has already
refused a file naming anything it does not define, and every type and link the
file defines exists by the time actions are applied — so the refusal is the
backstop for a writer that skips those checks, which is the same argument §339's
workspace guard was left in place for.

**Nothing is invented on the way through.** A hop's `far_type_id` is derived —
`action_search_arounds.check_source` recomputes it from the link and refuses a
document that disagrees — so it travels for readability and is *checked* rather
than trusted on the way back in. That is why `to_ids` puts it back rather than
leaving `check_source` to fill the gap: a landing type carried and then silently
replaced would make a hand-edited walk that does not join up import cleanly as a
different walk. The names this module emits are the ones the rest of the document
already uses: `object_type` for a type, as an action's subject is written, and
`link_type` for a link.
"""
from __future__ import annotations

from typing import Any


def _named(ids: dict[str, str], value: Any) -> str | None:
    """One id as a name, or `None` when this workspace has no such thing.

    `None` rather than the id: a document carrying an id it could not resolve
    would look portable and refuse on the way in, which is worse than a field
    that is plainly absent. The export's "nothing is identified by id"
    assertion is what makes that a rule rather than a preference.
    """
    return ids.get(str(value)) if value else None


def to_names(
    parameter: dict[str, Any],
    *,
    type_names: dict[str, str],
    link_names: dict[str, str],
) -> dict[str, Any]:
    """The three pointing fields, as names, for one exported parameter.

    Returns only the keys that have something to say, so a parameter with no
    dropdown adds nothing to the file — which keeps §326's documents readable
    and keeps a round trip from inventing `"options_from": null` on every
    parameter that never had one.
    """
    out: dict[str, Any] = {}
    held = _named(type_names, parameter.get("object_type_id"))
    if held:
        out["object_type"] = held

    options = parameter.get("options_from")
    if isinstance(options, dict) and options:
        named = _named(type_names, options.get("object_type_id"))
        if named:
            out["options_from"] = {
                "object_type": named,
                "property": options.get("property"),
            }

    walk = parameter.get("dropdown_search_around")
    if isinstance(walk, dict) and walk:
        written = _walk_to_names(walk, type_names, link_names)
        if written is not None:
            out["dropdown_search_around"] = written
    return out


def _walk_to_names(
    walk: dict[str, Any],
    type_names: dict[str, str],
    link_names: dict[str, str],
) -> dict[str, Any] | None:
    """p.36's start and p.37's hops as names, or `None` if anything is missing.

    **All of it or none of it.** A walk with one hop translated and one dropped
    is a different walk that would import cleanly — the worst of the three
    outcomes. A walk this workspace cannot fully name is a walk the file leaves
    out, and §326's plan then reports the parameter as changed, which is true.
    """
    start = walk.get("start") or {}
    start_type = _named(type_names, start.get("object_type_id"))
    if not start_type:
        return None
    written_start: dict[str, Any] = {
        "kind": start.get("kind"),
        "object_type": start_type,
    }
    if start.get("parameter"):
        written_start["parameter"] = start["parameter"]

    hops: list[dict[str, Any]] = []
    for hop in walk.get("hops") or []:
        if not isinstance(hop, dict):
            return None
        link = _named(link_names, hop.get("link_type_id"))
        far = _named(type_names, hop.get("far_type_id"))
        if not link or not far:
            return None
        hops.append({"link_type": link, "far_object_type": far})
    return {"start": written_start, "hops": hops}


def _resolved(
    ids: dict[str, str], value: Any, *, where: str, kind: str
) -> str:
    """One api_name as this workspace's id, or a refusal naming it.

    **The asymmetry with `_named` is the point** (§344). Outward, a reference
    this ontology cannot name is left out; inward, a name this workspace does
    not have is refused — because leaving it out would write a parameter with no
    dropdown and then report the file as applied, which is a silent
    disagreement between what the file said and what the workspace got.
    """
    found = ids.get(str(value))
    if not found:
        raise ValueError(
            f"{where} names the {kind} {value!r}, which this workspace does "
            "not have"
        )
    return found


def to_ids(
    parameter: dict[str, Any],
    *,
    type_ids: dict[str, str],
    link_ids: dict[str, str],
    where: str = "a parameter",
) -> dict[str, Any]:
    """The three pointing fields as this workspace's ids, for one parameter.

    The inverse of `to_names`, and the same rule about absence: a parameter the
    file says nothing about points at nothing, so the keys are emitted only when
    the document has something to say. `where` is how the refusals name this
    parameter — `type.action.parameter`, as `check_references` writes it — since
    a message about "an object type this workspace does not have" is no use
    without the field it came from.
    """
    out: dict[str, Any] = {}
    held = parameter.get("object_type")
    if held:
        out["object_type_id"] = _resolved(
            type_ids, held, where=where, kind="object type")

    options = parameter.get("options_from")
    if isinstance(options, dict) and options.get("object_type"):
        out["options_from"] = {
            "object_type_id": _resolved(
                type_ids, options["object_type"], where=where,
                kind="object type"),
            "property": options.get("property"),
        }

    walk = parameter.get("dropdown_search_around")
    if isinstance(walk, dict) and walk:
        out["dropdown_search_around"] = _walk_to_ids(
            walk, type_ids, link_ids, where)
    return out


def _walk_to_ids(
    walk: dict[str, Any],
    type_ids: dict[str, str],
    link_ids: dict[str, str],
    where: str,
) -> dict[str, Any]:
    """p.36's start and p.37's hops, back as ids.

    **The landing type is put back rather than left to be recomputed.**
    `check_source` derives each hop's far end from the link and refuses a
    document that declares a different one, so carrying it through is what makes
    a hand-edited walk that does not join up refuse instead of importing cleanly
    as a *different* walk.
    """
    start = walk.get("start") or {}
    resolved: dict[str, Any] = {
        "kind": start.get("kind"),
        "object_type_id": _resolved(
            type_ids, start.get("object_type"), where=where,
            kind="object type"),
    }
    if start.get("parameter"):
        resolved["parameter"] = start["parameter"]

    hops: list[dict[str, Any]] = []
    for hop in walk.get("hops") or []:
        if not isinstance(hop, dict):
            raise ValueError(f"{where} has a hop that is not an object")
        walked: dict[str, Any] = {
            "link_type_id": _resolved(
                link_ids, hop.get("link_type"), where=where, kind="link type"),
        }
        if hop.get("far_object_type"):
            walked["far_type_id"] = _resolved(
                type_ids, hop["far_object_type"], where=where,
                kind="object type")
        hops.append(walked)
    return {"start": resolved, "hops": hops}
