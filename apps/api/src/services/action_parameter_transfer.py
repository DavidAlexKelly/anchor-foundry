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

**Only the outward direction is here.** The inverse belongs to the unit that
applies action types at import, and it has no caller until then — a translator
back to ids, written now, would be a page of code nothing runs and nothing can
hold to account. What the import *can* check today is the document: a parameter
naming a type or link the file does not define is refused by `check_references`,
because the plan reads files whether or not apply writes actions.

**Nothing is invented on the way through.** A hop's `far_type_id` is derived —
`action_search_arounds.check_source` recomputes it from the link and refuses a
document that disagrees — so it travels for readability and is *checked* rather
than trusted on the way back in. The names this module emits are the ones the
rest of the document already uses: `object_type` for a type, as an action's
subject is written, and `link_type` for a link.
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
