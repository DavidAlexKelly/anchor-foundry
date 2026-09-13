"""Importing an ontology from JSON (§326; `ontology-manager` p.65-67).

    "You can import a previously exported Ontology working state by selecting
     the Advanced settings page… Next, select Import, which will recreate the
     entire working state from the JSON file in the application. **You will see
     the number of changes made in the file that need to be saved** in the
     application header." (p.66)

**p.66's import does not apply, and this platform has nowhere to put a state
that is loaded but unsaved.** Foundry stages the file into a working state and
counts the unsaved changes; here an ontology edit is written when it is made.
So the import is split in two rather than pretending: `plan` says what the file
would do and writes nothing, and `apply` does it. p.66's "number of changes
that need to be saved" is the plan's count, and the confirmation is where
Foundry's Save is.

**And the plan reports removals without performing them.** "Recreate the entire
working state" implies a type absent from the file should go — but deleting an
object type here deletes its objects, immediately and with no review, which is
the one thing Foundry's staging exists to prevent. So a plan names what the
file does not contain and points at §325's cleanup queue, which is the tool for
deciding whether a type is safe to delete. An importer that quietly removed
them would be a file-shaped delete button.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from . import ontology as ontology_service
from .ontology_export import FORMAT_VERSION, export_ontology


class ImportRefused(ValueError):
    """The file cannot be applied, and the message says what to change.

    A `ValueError`, so it reaches the caller as the 422 every other refusal in
    this platform uses — an import that failed for a reason the reader could
    fix should not arrive looking like a server fault.
    """


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ImportRefused(message)


def read_document(raw: Any) -> dict[str, Any]:
    """Check the file is one of ours before anything reads its contents.

    **Refused by shape, not by what happens when it is used.** A document
    missing `object_types` would otherwise fail somewhere deep in the planner
    with a `KeyError`, which tells a person editing JSON in a text editor — the
    situation p.65 is entirely about — nothing they can act on.
    """
    _require(isinstance(raw, dict), "an ontology file is a JSON object")
    version = raw.get("format_version")
    _require(
        version == FORMAT_VERSION,
        f"this file says format_version {version!r}; this platform writes and "
        f"reads {FORMAT_VERSION}",
    )
    for section in ("object_types", "link_types", "action_types"):
        _require(
            isinstance(raw.get(section), list),
            f"an ontology file needs a {section!r} list; this one has "
            f"{type(raw.get(section)).__name__}",
        )
    return raw


def check_references(document: dict[str, Any]) -> None:
    """Every name the file uses must be a name the file defines.

    **This is p.67's problem in the shape it takes here.** Foundry refuses a
    file whose conditional formatting references rule sets defined outside the
    ontology; this platform's formatting is inline and names sibling properties,
    so the equivalent failure is a rule — or a link, or an action — naming
    something the document does not carry.

    Checked before anything is written, because a half-applied import is worse
    than a refused one: p.138's reasoning about batches, applied to a file.
    """
    types = {t.get("api_name"): t for t in document["object_types"]}
    _require(all(types), "every object type in the file needs an api_name")

    for name, kind in types.items():
        properties = kind.get("properties") or []
        theirs = {p.get("api_name") for p in properties}
        title = kind.get("title_property")
        _require(
            title is None or title in theirs,
            f"{name!r} names {title!r} as its title property, and the file "
            f"does not give it that property",
        )
        for prop in properties:
            for rule in prop.get("conditional_format") or []:
                named = rule.get("property")
                _require(
                    named is None or named in theirs,
                    f"{name}.{prop.get('api_name')} is formatted on "
                    f"{named!r}, which is not a property of {name!r}",
                )

    for link in document["link_types"]:
        for side in ("from_object_type", "to_object_type"):
            _require(
                link.get(side) in types,
                f"link type {link.get('api_name')!r} joins "
                f"{link.get(side)!r}, which the file does not define",
            )
        # **The fields a link cannot be created without** (§340). p.65's premise
        # is that somebody edited this JSON in a text editor, so a key they
        # deleted has to come back as a sentence about that key — before §340
        # applied links nothing read `cardinality`, and the first thing that did
        # turned a hand-edited file into a 500.
        _require(
            bool(link.get("api_name")),
            "every link type in the file needs an api_name",
        )
        _require(
            link.get("cardinality") in ontology_service.CARDINALITIES,
            f"link type {link.get('api_name')!r} needs a cardinality, one of "
            f"{', '.join(sorted(ontology_service.CARDINALITIES))}",
        )

    for action in document["action_types"]:
        _require(
            action.get("object_type") in types,
            f"action type {action.get('api_name')!r} is on "
            f"{action.get('object_type')!r}, which the file does not define",
        )


#: What a link type will not let an import change, and the reason is
#: `ontology.set_link_join`'s own: "changing an endpoint or the cardinality
#: would make it a different relationship wearing the same name — delete and
#: recreate for that." An import is not an exception to that. Applying the half
#: that *is* mutable and leaving these would produce a link matching neither the
#: file nor the workspace, which is worse than refusing (§340).
IMMUTABLE_LINK_FIELDS = (
    ("from_object_type", "the type at its from end"),
    ("to_object_type", "the type at its to end"),
    ("cardinality", "its cardinality"),
)


def check_immutable_links(
    document: dict[str, Any], current: dict[str, Any]
) -> None:
    """Refuse a file that redefines a link this workspace already has.

    **Before anything is written**, which is the same rule `check_references`
    follows and for the same reason: a half-applied import is worse than a
    refused one. It cannot live in `check_references` because that is a pure
    function over the document, and this is a comparison against the workspace.

    A link the workspace does not have is not checked here — it is created whole
    below, endpoints and all.
    """
    mine = {row["api_name"]: row for row in current["link_types"]}
    for link in document["link_types"]:
        held = mine.get(link.get("api_name"))
        if held is None:
            continue
        for field, phrase in IMMUTABLE_LINK_FIELDS:
            _require(
                link.get(field) == held.get(field),
                f"link type {link.get('api_name')!r} already exists here and "
                f"the file changes {phrase}, which would make it a different "
                f"relationship wearing the same name. Rename it in the file, "
                f"or delete the link type first",
            )


async def plan(
    conn: AsyncConnection, workspace_id: UUID, document: dict[str, Any]
) -> dict[str, Any]:
    """p.66's "number of changes made in the file that need to be saved".

    Compared against an export of the workspace as it is now, so the two sides
    are the same shape by construction. A planner that read the database in its
    own way would be a second description of an ontology, free to disagree with
    the one the file was written from — and the disagreement would show as a
    change nobody made.
    """
    read_document(document)
    check_references(document)
    current = await export_ontology(conn, workspace_id)

    def compare(section: str, key: str = "api_name") -> dict[str, list[str]]:
        mine = {row[key]: row for row in current[section]}
        theirs = {row.get(key): row for row in document[section]}
        return {
            "added": sorted(n for n in theirs if n not in mine),
            # **Changed means "differs", not "mentioned".** A file that is a
            # straight re-import of an unedited export should plan zero
            # changes, and a planner counting every named thing would report
            # the whole ontology as work to do.
            "changed": sorted(
                n for n in theirs if n in mine and theirs[n] != mine[n]
            ),
            "unchanged": sorted(
                n for n in theirs if n in mine and theirs[n] == mine[n]
            ),
            # Named, never performed — see the module docstring.
            "absent_from_file": sorted(n for n in mine if n not in theirs),
        }

    sections = {
        "object_types": compare("object_types"),
        "link_types": compare("link_types"),
        "action_types": compare("action_types"),
    }
    return {
        "workspace": current["workspace"],
        "from_workspace": document.get("workspace"),
        #: p.65's two workflows, told apart by the one fact the file carries
        #: about its origin. A round-trip and a copy want different things read
        #: of the same plan: "nothing changed" is reassuring for one and
        #: suspicious for the other.
        "is_round_trip": (document.get("workspace") or {}).get("id")
        == current["workspace"]["id"],
        "sections": sections,
        "changes": sum(
            len(s["added"]) + len(s["changed"]) for s in sections.values()
        ),
    }


async def apply(
    conn: AsyncConnection,
    workspace_id: UUID,
    document: dict[str, Any],
    *,
    actor_id: UUID,
) -> dict[str, Any]:
    """Write what the plan described. Object types and link types.

    **Adds and updates, never removals** — the module docstring says why.

    **Two passes, because a link needs its ends to exist** (§340). p.65's second
    workflow is "copy the working state of one Ontology to another", where every
    type in the file is new — so a link resolved before the object-type pass
    would name two types that are not there yet. Resolving afterwards by
    api_name needs no ordering rules in the document and no two-phase insert:
    `check_references` has already refused a file whose link names a type the
    file does not define, and every type the file defines exists by the time the
    second pass runs.

    Action types are still named in the plan and not applied, and are still ○ in
    `ontology.md`: an action's rules and criteria name parameters, and since
    §330-§339 its parameters name object types, link types and properties inside
    jsonb documents — so it needs a resolution pass of its own rather than a
    line here.

    Returned as a report rather than as a status, because an import is
    something a person reads afterwards: p.66's screen shows a count, and a
    count with nothing under it cannot be checked against what was expected.
    """
    made = await plan(conn, workspace_id, document)
    before = await export_ontology(conn, workspace_id)
    # **Refused before the first write**, which is why it is here rather than
    # between the two passes: an object type applied and then a link refused
    # leaves a workspace that matches neither side.
    check_immutable_links(document, before)
    current = {t["api_name"]: t for t in before["object_types"]}
    added: list[str] = []
    updated: list[str] = []
    for kind in document["object_types"]:
        name = kind["api_name"]
        if name in made["sections"]["object_types"]["unchanged"]:
            continue
        properties = [dict(p) for p in (kind.get("properties") or [])]
        if name in current:
            row = await _find_type(conn, workspace_id, name)
            await ontology_service.update_type(
                conn,
                workspace_id=workspace_id,
                type_id=UUID(str(row["id"])),
                display_name=kind["display_name"],
                description=kind.get("description") or "",
                icon=kind.get("icon") or "cube",
                colour=kind.get("colour") or "#4f46e5",
                properties=properties,
                title_property=kind.get("title_property"),
                updated_by=actor_id,
                # **Acknowledged, because the file is the acknowledgement.**
                # A person who edited JSON and pressed Import has already been
                # shown the plan; asking again here would be a second
                # confirmation of the same decision, and one with no screen to
                # ask it on.
                acknowledge_breaking=True,
            )
            updated.append(name)
        else:
            await ontology_service.create_type(
                conn,
                workspace_id=workspace_id,
                api_name=name,
                display_name=kind["display_name"],
                description=kind.get("description") or "",
                icon=kind.get("icon") or "cube",
                colour=kind.get("colour") or "#4f46e5",
                properties=properties,
                title_property=kind.get("title_property"),
                created_by=actor_id,
            )
            added.append(name)

    links_added, links_updated = await _apply_links(
        conn, workspace_id, document, made, actor_id=actor_id
    )

    return {
        "added": added,
        "updated": updated,
        "links_added": links_added,
        "links_updated": links_updated,
        "not_applied": {
            "action_types": made["sections"]["action_types"]["added"]
            + made["sections"]["action_types"]["changed"],
        },
        "absent_from_file": made["sections"]["object_types"]["absent_from_file"],
    }


async def _apply_links(
    conn: AsyncConnection,
    workspace_id: UUID,
    document: dict[str, Any],
    made: dict[str, Any],
    *,
    actor_id: UUID,
) -> tuple[list[str], list[str]]:
    """p.65's link types, resolved by api_name after the types exist (§340).

    A link that is new is created whole. A link that exists has already been
    checked for an endpoint or cardinality change, so what is left is the half
    `set_link_join` calls mutable: the join, the two side names, and the status.

    **The status goes through `set_link_join` even on a create**, rather than
    being a column on the insert. p.257 caps a link at the weakest status of its
    two object types and its join properties, and that cap lives in one place;
    an insert carrying a status would be a second answer to "how production-ready
    is this link", free to store something p.257 says is unreachable.

    **A link's `deprecation` is not applied, and cannot be by anything.** The
    column is exported and no code path in this build writes it — not this, not
    the PATCH route, not §177's bulk status. That is a ○ on the Status row
    rather than something to fix here, and it costs a round trip nothing today:
    every export of every workspace carries `null` for it.
    """
    section = made["sections"]["link_types"]
    wanted = set(section["added"]) | set(section["changed"])
    if not wanted:
        return [], []

    types = {
        row["api_name"]: UUID(str(row["id"]))
        for row in await _types_by_name(conn, workspace_id)
    }
    # The ids, read straight rather than off an export: `LINK_FIELDS` carries
    # what a *file* should say about a link, and an id is the one thing a
    # portable document must never contain (§326's whole shape is by api_name).
    existing = {
        row["api_name"]: UUID(str(row["id"]))
        for row in await _links_by_name(conn, workspace_id)
    }
    added: list[str] = []
    updated: list[str] = []
    for link in document["link_types"]:
        name = str(link.get("api_name"))
        if name not in wanted:
            continue
        if name not in existing:
            made_link = await ontology_service.create_link_type(
                conn,
                workspace_id=workspace_id,
                api_name=name,
                display_name=link.get("display_name") or name,
                from_type_id=types[str(link["from_object_type"])],
                to_type_id=types[str(link["to_object_type"])],
                cardinality=str(link["cardinality"]),
                created_by=actor_id,
                from_property=link.get("from_property"),
                to_property=link.get("to_property"),
                from_side_name=link.get("from_side_name"),
                to_side_name=link.get("to_side_name"),
            )
            link_id = UUID(str(made_link["id"]))
            added.append(name)
        else:
            link_id = existing[name]
            updated.append(name)
        await ontology_service.set_link_join(
            conn,
            workspace_id,
            link_id,
            from_property=link.get("from_property"),
            to_property=link.get("to_property"),
            from_side_name=link.get("from_side_name"),
            to_side_name=link.get("to_side_name"),
            status=link.get("status"),
        )
    return added, updated


async def _types_by_name(
    conn: AsyncConnection, workspace_id: UUID
) -> list[dict[str, Any]]:
    return await _named_rows(conn, workspace_id, "object_types")


async def _links_by_name(
    conn: AsyncConnection, workspace_id: UUID
) -> list[dict[str, Any]]:
    return await _named_rows(conn, workspace_id, "link_types")


async def _named_rows(
    conn: AsyncConnection, workspace_id: UUID, table: str
) -> list[dict[str, Any]]:
    """`{id, api_name}` for one workspace-scoped ontology table.

    The table name is this module's own literal and never a caller's — the two
    call sites above pass constants — which is what keeps an f-string in a query
    honest here.
    """
    from ..lib.db import fetch_all

    assert table in ("object_types", "link_types"), table
    rows = await fetch_all(
        conn,
        f"SELECT id, api_name FROM {table} WHERE workspace_id = :wid",
        {"wid": str(workspace_id)},
    )
    return [dict(r) for r in rows]


async def _find_type(
    conn: AsyncConnection, workspace_id: UUID, api_name: str
) -> dict[str, Any]:
    from ..lib.db import fetch_one

    row = await fetch_one(
        conn,
        "SELECT id FROM object_types WHERE workspace_id = :wid AND api_name = :n",
        {"wid": str(workspace_id), "n": api_name},
    )
    assert row is not None, api_name
    return dict(row)
