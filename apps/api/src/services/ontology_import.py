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

from . import action_parameter_transfer as parameter_transfer
from . import action_rule_transfer as rule_transfer
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

    **Not all of p.67, and `check_outside_ontology` is the rest** (§343). This
    one is pure over the document and asks whether the file is self-consistent;
    that one asks whether a reference can survive the journey at all, which
    needs to know where the file is going.

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
        # **The field a link cannot be created without** (§340). p.65's premise
        # is that somebody edited this JSON in a text editor, so a key they
        # deleted has to come back as a sentence about that key — before §340
        # applied links nothing read `cardinality`, and the first thing that did
        # turned a hand-edited file into a 500.
        #
        # There is no check for a missing `api_name` beside this one, and a
        # sweep is why (§213): `create_link_type` refuses one by regex, in a
        # sentence that names the field, and a request is a single transaction —
        # so the earlier check changed neither the outcome nor what was written.
        # `object_types` has one because its name is a *key* this module builds
        # a dictionary on, which is a different job.
        _require(
            link.get("cardinality") in ontology_service.CARDINALITIES,
            f"link type {link.get('api_name')!r} needs a cardinality, one of "
            f"{', '.join(sorted(ontology_service.CARDINALITIES))}",
        )

    links = {l.get("api_name") for l in document["link_types"]}
    for action in document["action_types"]:
        _require(
            action.get("object_type") in types,
            f"action type {action.get('api_name')!r} is on "
            f"{action.get('object_type')!r}, which the file does not define",
        )
        # **A parameter's dropdown names types and links, and the file has to
        # define them too** (§342). The same rule as a link's two ends, one
        # resource further in: a name the document does not carry cannot be
        # resolved on the way in, and a dropdown stored against nothing is the
        # state §339 spent a unit making unreachable by deletion.
        for parameter in action.get("parameters") or []:
            where = f"{action.get('object_type')}.{action.get('api_name')}." \
                    f"{parameter.get('api_name')}"
            for named, kind in _parameter_references(parameter):
                _require(
                    named in (types if kind == "object type" else links),
                    f"{where} names the {kind} {named!r}, which the file does "
                    "not define",
                )
        # **And so does a rule** (§343). p.75's rules name the object type they
        # create, change or delete and the link type they write or clear, and a
        # notify rule names the type it reads a recipient off — six fields that
        # held a uuid until this unit and are api_names now. Same rule as the
        # dropdown above, one table over.
        for order, rule in enumerate(action.get("rules") or [], start=1):
            where = f"{action.get('object_type')}.{action.get('api_name')} " \
                    f"rule {order}"
            for named, kind in rule_transfer.references(rule):
                _require(
                    named in (types if kind == "object type" else links),
                    f"{where} names the {kind} {named!r}, which the file does "
                    "not define",
                )


def check_outside_ontology(document: dict[str, Any]) -> None:
    """p.67's refusal, for the file that is going somewhere else (§343).

        "If you receive the error `OntologyMetadata:UnreferencedRuleSets`, you
         are trying to import an Ontology working state with conditional
         formatting rules that are not defined in that Ontology and cannot be
         transferred over. You will need to delete the … rules from the Ontology
         working state before importing." (p.67)

        "An exported Ontology working state with conditional formatting rules
         configured on its properties cannot be imported to an Ontology other
         than the one it was exported from." (p.67)

    **§326 recorded that this refusal had no cause here, and that was right
    about formatting and wrong about the class.** This platform's conditional
    formatting is inline jsonb naming sibling properties, so it is
    self-contained and p.67's own example genuinely cannot happen. What can is
    the thing p.67 is *about*: a rule referring to something the ontology does
    not contain. A webhook rule names a webhook, which is scoped to a workspace
    and a project; a static notify rule names people, who are scoped to an
    organisation. Neither is in the file and neither can be, so the file cannot
    build them somewhere else.

    **Only for a copy, which is the other half of p.67's sentence** — "other
    than the one it was exported from". A round trip is putting the ontology
    back where those ids already mean what they say, and refusing it would be
    refusing p.65's first workflow for a reason that does not apply to it.

    The remedy is p.67's remedy: the message names the action and the rule, so
    the sentence somebody can act on is "delete this rule from the file".
    """
    reaching: list[str] = []
    for action in document["action_types"]:
        for order, rule in enumerate(action.get("rules") or [], start=1):
            for what in rule_transfer.outside_ontology(rule):
                reaching.append(
                    f"{action.get('object_type')}.{action.get('api_name')} "
                    f"rule {order} names {what}"
                )
    _require(
        not reaching,
        "this file came from a different ontology and carries rules that "
        "reach outside it: " + "; ".join(reaching) + ". Those references "
        "cannot be transferred over — delete the rules from the file, or "
        "import it into the workspace it was exported from (p.67)",
    )


def _parameter_references(parameter: dict[str, Any]):
    """Every type and link one parameter's dropdown names, for `check_references`.

    A generator rather than three loops at the call site, because the three
    fields are one question — "what does this dropdown point at" — and the day
    a fourth arrives it should be added in one place. The shapes themselves are
    `action_parameter_transfer`'s; this only walks them.
    """
    held = parameter.get("object_type")
    if held:
        yield held, "object type"
    options = parameter.get("options_from")
    if isinstance(options, dict) and options.get("object_type"):
        yield options["object_type"], "object type"
    walk = parameter.get("dropdown_search_around")
    if isinstance(walk, dict) and walk:
        start = walk.get("start") or {}
        if start.get("object_type"):
            yield start["object_type"], "object type"
        for hop in walk.get("hops") or []:
            if isinstance(hop, dict) and hop.get("link_type"):
                yield hop["link_type"], "link type"


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

    Its own function rather than a line in `check_references`, because that one
    is pure over the document and this is a comparison against the workspace.

    **It is called before the first write, and that is tidiness rather than
    safety** — a sweep is what made the difference clear. Moving this call to
    sit after the object-type pass changes no test and no outcome, because
    `user_connection` wraps the whole request in one transaction: any refusal
    already rolls back everything the import had written. So the reason it runs
    first is that work nobody will keep is work not worth doing, and not the
    half-applied-import argument `check_references` can legitimately make about
    a file it reads before touching a database at all.

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
    round_trip = (document.get("workspace") or {}).get("id") == current[
        "workspace"
    ]["id"]
    # p.67's refusal, which needs the one fact `check_references` cannot have:
    # whether this file is going back where it came from (§343).
    if not round_trip:
        check_outside_ontology(document)

    def named(section: str) -> "Any":
        """How this section's rows are keyed, and for actions it is a pair.

        **An action's api_name is not unique in an ontology** (§341).
        `action_types` is unique on (object_type_id, api_name), so `set_status`
        on Ticket and `set_status` on Invoice are two different actions with one
        name — and keying the document by the name alone silently drops one of
        them, reports the other as *changed* when the two differ, and would
        apply the wrong one the day the import applies actions at all.

        Found by a browser test whose workspace happened to hold two, which is
        also why it is written down here: on a clean database nothing collides
        and this reads like a distinction without a difference.
        """
        if section == "action_types":
            return lambda row: f"{row.get('object_type')}.{row.get('api_name')}"
        return lambda row: row.get("api_name")

    def compare(section: str) -> dict[str, list[str]]:
        key = named(section)
        mine = {key(row): row for row in current[section]}
        theirs = {key(row): row for row in document[section]}
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
        #: suspicious for the other. It is also what p.67's refusal turns on,
        #: which is why it is computed above rather than here (§343).
        "is_round_trip": round_trip,
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
    """Write what the plan described. Object types, link types and actions.

    **Adds and updates, never removals** — the module docstring says why.

    **Three passes, because each one needs the last** (§340, §344). p.65's
    second workflow is "copy the working state of one Ontology to another",
    where every type in the file is new — so a link resolved before the
    object-type pass would name two types that are not there yet, and an action
    resolved before the link pass would name a link that is not. Resolving
    afterwards by api_name needs no ordering rules in the document and no
    two-phase insert: `check_references` has already refused a file naming
    anything it does not define, and everything the file defines exists by the
    time the pass that needs it runs.

    Returned as a report rather than as a status, because an import is
    something a person reads afterwards: p.66's screen shows a count, and a
    count with nothing under it cannot be checked against what was expected.
    """
    made = await plan(conn, workspace_id, document)
    before = await export_ontology(conn, workspace_id)
    # Before the two passes rather than between them — see the function's own
    # docstring for why that is a preference and not a safety property.
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
    actions_added, actions_updated = await _apply_actions(
        conn, workspace_id, document, made, actor_id=actor_id
    )

    return {
        "added": added,
        "updated": updated,
        "links_added": links_added,
        "links_updated": links_updated,
        "actions_added": actions_added,
        "actions_updated": actions_updated,
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


async def _apply_actions(
    conn: AsyncConnection,
    workspace_id: UUID,
    document: dict[str, Any],
    made: dict[str, Any],
    *,
    actor_id: UUID,
) -> tuple[list[str], list[str]]:
    """p.65's action types, resolved by api_name after the types and links exist.

    **A third pass for the same reason there was a second** (§340). An action's
    parameters name object types and link types and its rules name both, so
    every one of them has to be there before an action can be written — and
    p.65's second workflow, "copy the working state of one Ontology to another",
    is the case where *none* of them were a moment ago.

    **The action row and its document are two calls, because they always were.**
    `create_shell_action_type` writes the row; `set_definition` writes the
    parameters, rules and criteria as the one document they constrain each
    other inside (decision 0007); `replace_sections` writes p.29's form, which
    is its own document for the same reason. Going through `create_action_type`
    instead would run p.75's property-to-parameter conversion and then delete
    every row it wrote — and would refuse an action whose rules never modify its
    subject, which is a legal action and not an importable one.

    **The form is handed to `set_definition` as well as written after it**, and
    that is not belt and braces: p.45 lets an override read only the parameters
    *above* it in the form, the form is §328's sections, and the sections do not
    exist yet when a new action's definition is saved. Without this, an action
    that is legal where it was exported is refused where it is imported, for an
    arrangement the workspace is one statement away from having.

    **Every reference is resolved before anything is written**, so a file naming
    something this workspace does not have refuses rather than half-applying —
    and `user_connection`'s single transaction is what actually keeps that
    promise, as §340 had to learn about its own version of this sentence.
    """
    section = made["sections"]["action_types"]
    wanted = set(section["added"]) | set(section["changed"])
    if not wanted:
        return [], []

    # Imported here rather than at the top: `actions` imports `ontology`, which
    # this module also imports, and the pair at module scope is a cycle.
    from . import action_sections as sections_service
    from . import actions as actions_service
    from ..lib.db import fetch_all

    type_ids = {
        str(row["api_name"]): str(row["id"])
        for row in await _types_by_name(conn, workspace_id)
    }
    link_ids = {
        str(row["api_name"]): str(row["id"])
        for row in await _links_by_name(conn, workspace_id)
    }
    # **Keyed by `object_type.api_name`, like the plan** (§341). `action_types`
    # is unique on (object_type_id, api_name) and not per workspace, so the name
    # alone would find `set_status` on Ticket when the file meant the one on
    # Invoice — and this is the pass that would then have written it.
    held = {
        f"{row['object_type']}.{row['api_name']}": UUID(str(row["id"]))
        for row in await fetch_all(
            conn,
            """
            SELECT at.id, at.api_name, ot.api_name AS object_type
              FROM action_types at
              JOIN object_types ot ON ot.id = at.object_type_id
             WHERE at.workspace_id = :wid
            """,
            {"wid": str(workspace_id)},
        )
    }

    added: list[str] = []
    updated: list[str] = []
    for action in document["action_types"]:
        where = f"{action.get('object_type')}.{action.get('api_name')}"
        if where not in wanted:
            continue
        parameters = [
            _parameter_for(parameter, type_ids, link_ids, where)
            for parameter in action.get("parameters") or []
        ]
        rules = [
            {"kind": rule.get("kind"),
             "config": rule_transfer.to_ids(
                 rule, type_ids=type_ids, link_ids=link_ids,
                 where=f"{where} rule {order}")}
            for order, rule in enumerate(action.get("rules") or [], start=1)
        ]
        criteria = [dict(c) for c in (action.get("criteria") or [])]
        sections = [dict(s) for s in (action.get("sections") or [])]

        if where in held:
            action_type_id = held[where]
            # **What the action is called, which nothing else writes** (§344).
            # No screen renames an action, so without this an ontology file that
            # renamed one had the rename dropped and the import still reported
            # it as updated — §214's control that looks like it works.
            await actions_service.rename_action_type(
                conn, workspace_id, action_type_id,
                display_name=action.get("display_name"),
                description=action.get("description") or "",
            )
            updated.append(where)
        else:
            row = await actions_service.create_shell_action_type(
                conn,
                workspace_id=workspace_id,
                object_type_id=UUID(type_ids[str(action["object_type"])]),
                api_name=str(action["api_name"]),
                # **Not defaulted to the api_name**, which is what the first
                # draft did and a sweep found unreachable (§345). p.65's
                # premise is a hand-edited file, and a display name somebody
                # deleted has to come back as a sentence about *that key* —
                # inventing one puts an action into the ontology under a name
                # nobody chose, and db 0013 refuses an empty one anyway, as a
                # 500 with nothing in it. Same correction §340 made for a
                # link's missing `cardinality`.
                display_name=action.get("display_name"),
                description=action.get("description") or "",
                created_by=actor_id,
            )
            action_type_id = UUID(str(row["id"]))
            added.append(where)

        await actions_service.set_definition(
            conn, workspace_id, action_type_id,
            parameters=parameters, rules=rules, criteria=criteria,
            sections=sections,
        )
        await sections_service.replace_sections(conn, action_type_id, sections)
        # p.253's status and p.154's revert toggle, written last because they
        # are statements *about* the action rather than part of what it does —
        # which is the division `set_action_status` exists to keep.
        await actions_service.set_action_status(
            conn, workspace_id, action_type_id,
            status=action.get("status"),
            deprecation=action.get("deprecation"),
            allow_revert=action.get("allow_revert"),
        )
    return added, updated


def _parameter_for(
    parameter: dict[str, Any],
    type_ids: dict[str, str],
    link_ids: dict[str, str],
    where: str,
) -> dict[str, Any]:
    """One document parameter as the definition API's shape (§344).

    Built field by field rather than echoed with `**parameter`: the file carries
    `sort_order`, which `set_definition` derives from the list's order, and a
    document that had grown a key nobody validated would be handed straight to
    an insert. The same argument `check_source` makes about a walk.
    """
    return {
        "api_name": parameter.get("api_name"),
        "display_name": parameter.get("display_name"),
        "data_type": parameter.get("data_type"),
        "required": bool(parameter.get("required", False)),
        "default_value": parameter.get("default_value"),
        "hidden": bool(parameter.get("hidden", False)),
        "dropdown_filters": parameter.get("dropdown_filters") or [],
        "overrides": parameter.get("overrides") or [],
        **parameter_transfer.to_ids(
            parameter, type_ids=type_ids, link_ids=link_ids,
            where=f"{where}.{parameter.get('api_name')}",
        ),
    }


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
