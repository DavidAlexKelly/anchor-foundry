"""Exporting an ontology as JSON (§326; `ontology-manager` p.65-67).

    "Ontology schema definitions are stored in a JSON file. An Ontology JSON
     file can be exported and edited with a code editor or text editor before
     being imported back into Foundry." (p.65)

    "You should not depend on the exported JSON schema as it may change over
     time." (p.65)

p.65's two workflows are what the shape has to serve:

  1. "make Ontology edits in code… bypass the Ontology Manager interface"
  2. "copy the working state of one Ontology to another"

**Written by api_name, never by id.** Every identifier in the file is the stable
machine name db 0003 calls "the stable machine name used by exports", because
the second workflow copies an ontology into a *different* workspace where no id
from the first one exists. A file full of uuids would round-trip into its own
workspace and be meaningless anywhere else — which is the workflow p.65 puts
second and most people want first.

**And that is also why the file names its origin.** p.67 is about a state that
cannot be imported elsewhere; the equivalent here is weaker but real, so the
document says which workspace it came from and the importer can tell a
round-trip from a copy.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from . import action_parameter_transfer as parameter_transfer
from . import action_rule_transfer as rule_transfer

#: The document's own version. p.65 says "you should not depend on the exported
#: JSON schema as it may change over time" — which is licence to change it, and
#: a reason to stamp it: a file that did not say which shape it was would leave
#: the importer guessing on the day the shape moves.
FORMAT_VERSION = 1

#: Property fields that travel. **A list rather than `SELECT *`**, because an
#: export is a promise: a column added to `object_type_properties` should not
#: silently start appearing in everybody's files, and one removed should break
#: this line rather than a stranger's import.
PROPERTY_FIELDS = (
    "api_name",
    "display_name",
    "data_type",
    "required",
    "description",
    "sort_order",
    "visibility",
    "value_format",
    "conditional_format",
    "edit_only",
    "derivation",
    "struct_fields",
    "status",
    "deprecation",
)

#: The same decision for the type itself. `resource_id`, `created_at` and
#: `created_by` are deliberately absent: they are facts about *this* copy rather
#: than about the ontology, and carrying them would make an import claim
#: somebody else's authorship and a resource id that already belongs to another
#: row.
TYPE_FIELDS = (
    "api_name",
    "display_name",
    "description",
    "icon",
    "colour",
    "status",
    "deprecation",
    "visibility",
)

#: A link type has no description column; what it does have is the *join* —
#: `from_property` and `to_property` — and the two side names p.219 puts on
#: either end. Those are the link, not decoration: a file carrying a link type
#: without its join would import something that cannot traverse.
LINK_FIELDS = (
    "api_name",
    "display_name",
    "cardinality",
    "from_property",
    "to_property",
    "from_side_name",
    "to_side_name",
    "status",
    "deprecation",
)

ACTION_FIELDS = (
    "api_name",
    "display_name",
    "description",
    "status",
    "deprecation",
    "allow_revert",
)


#: The columns that hold JSON. **Named, rather than parsing anything that
#: happens to be a string**: the driver hands back `jsonb` as text in some
#: configurations and as objects in others, so a `json.loads` on every field
#: was a blanket that tried to parse `display_name` and fell over on the first
#: type whose name was not valid JSON. Found exactly that way.
JSON_FIELDS = frozenset({
    "deprecation",
    "value_format",
    "conditional_format",
    "derivation",
    "struct_fields",
    "default_value",
    "config",
    # §341's additions, for the two tables §326 never read.
    #
    # **`dropdown_filters` is deliberately not here**, though it is name-based
    # and would travel verbatim. A filter is written against the type the
    # parameter offers, and that type is `object_type_id` — an id, and one of
    # the three fields this unit leaves to §342. Carrying the filter without it
    # would put a narrowing in the file with nothing to say what it narrows,
    # which is a document that reads as complete and is not. A sweep is what
    # made the coupling obvious: the fixture's filter list was empty, so
    # "carried" and "dropped" were the same document.
    "conditions",
    "set_default",
    "visible_when",
})


def _json(value: Any) -> Any:
    """Parse a jsonb column that every query above casts to `::text`.

    **The cast is the point, and a browser test is why** (§341). This used to
    read "if it is a string it must be raw JSON text", because psycopg hands
    jsonb back as text in some configurations and as decoded objects in others.
    That heuristic is undecidable for one case and it is not a rare one: a jsonb
    column holding a JSON *string* decodes to a Python `str`, which is
    indistinguishable from an undecoded one — so `_json` parsed it a second
    time and `json.loads('see the ticket')` failed.

    An override's `set_default` is the field that found it, and p.43-46's whole
    point is defaulting a parameter to a value, which for a string parameter is
    a string. `default_value` had the same latent defect since §326 and nothing
    had set a string default in a workspace that was later exported.

    Casting in SQL removes the guess rather than patching it: what arrives is
    NULL or JSON text, always, whatever the driver is configured to do.

    **The actions route already knew.** `_action_type_out` carries a comment
    saying `default_value` is deliberately not parsed, "a jsonb scalar comes
    back already decoded, and parsing it again raises" — written before this
    module and never read by it. `action_overrides._json` is the same heuristic
    with no comment at all, and is reached only with a `conditions` list, which
    is why it has not met this. Named here so the next person finds all three.
    """
    return json.loads(value) if isinstance(value, str) else value


def _pick(row: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {
        name: (_json(row.get(name)) if name in JSON_FIELDS else row.get(name))
        for name in fields
        if name in row
    }


async def export_ontology(
    conn: AsyncConnection, workspace_id: UUID
) -> dict[str, Any]:
    """The workspace's ontology as p.65's JSON document.

    **One query per kind, not one per row.** A workspace with two hundred object
    types is the ordinary case here (§315's note on the same problem), and an
    export that read each type's properties separately would make the file's
    size the number of round trips.
    """
    workspace = await fetch_one(
        conn,
        "SELECT id, slug, name FROM workspaces WHERE id = :wid",
        {"wid": str(workspace_id)},
    )
    assert workspace is not None

    types = await fetch_all(
        conn,
        """
        SELECT id, api_name, display_name, description, icon, colour,
               status::text AS status, deprecation::text AS deprecation,
               visibility::text AS visibility, title_property_id
          FROM object_types
         WHERE workspace_id = :wid
         ORDER BY api_name
        """,
        {"wid": str(workspace_id)},
    )
    properties = await fetch_all(
        conn,
        """
        SELECT object_type_id, api_name, display_name,
               data_type::text AS data_type, required, description, sort_order,
               visibility::text AS visibility,
               value_format::text AS value_format,
               conditional_format::text AS conditional_format,
               edit_only, derivation::text AS derivation,
               struct_fields::text AS struct_fields, status::text AS status,
               deprecation::text AS deprecation, id
          FROM object_type_properties
         WHERE object_type_id = ANY(
                   SELECT id FROM object_types WHERE workspace_id = :wid)
         ORDER BY object_type_id, sort_order, api_name
        """,
        {"wid": str(workspace_id)},
    )
    by_type: dict[str, list[dict[str, Any]]] = {}
    title_of: dict[str, str] = {}
    for row in properties:
        by_type.setdefault(str(row["object_type_id"]), []).append(row)
        title_of[str(row["id"])] = str(row["api_name"])

    # **id → api_name, for the three fields that point** (§342). Built from the
    # rows this function already read rather than by a fourth query: an export
    # that resolved names separately could disagree with the types and links it
    # is writing in the same document.
    type_names = {str(t["id"]): str(t["api_name"]) for t in types}

    links = await fetch_all(
        conn,
        """
        SELECT lt.id, lt.api_name, lt.display_name,
               lt.cardinality::text AS cardinality,
               lt.from_property, lt.to_property,
               lt.from_side_name, lt.to_side_name,
               lt.status::text AS status, lt.deprecation::text AS deprecation,
               a.api_name AS from_object_type, b.api_name AS to_object_type
          FROM link_types lt
          JOIN object_types a ON a.id = lt.from_object_type_id
          JOIN object_types b ON b.id = lt.to_object_type_id
         WHERE lt.workspace_id = :wid
         ORDER BY lt.api_name
        """,
        {"wid": str(workspace_id)},
    )

    actions = await fetch_all(
        conn,
        """
        SELECT at.id, at.api_name, at.display_name, at.description,
               at.status::text AS status,
               at.deprecation::text AS deprecation, at.allow_revert,
               ot.api_name AS object_type
          FROM action_types at
          JOIN object_types ot ON ot.id = at.object_type_id
         WHERE at.workspace_id = :wid
         -- **By object type first, and that is not cosmetic** (§341).
         -- `action_types` is unique on (object_type_id, api_name), *not* per
         -- workspace, so two actions in one ontology may share a name — and
         -- ordering by the name alone leaves which of them comes first to the
         -- planner's tie-break, which is to say to nothing.
         ORDER BY ot.api_name, at.api_name
        """,
        {"wid": str(workspace_id)},
    )
    parameters = await fetch_all(
        conn,
        """
        SELECT id, action_type_id, api_name, display_name,
               data_type::text AS data_type, required,
               default_value::text AS default_value, hidden,
               sort_order, section_id,
               object_type_id, dropdown_filters::text AS dropdown_filters,
               dropdown_search_around::text AS dropdown_search_around,
               options_from::text AS options_from
          FROM action_parameters
         WHERE action_type_id = ANY(
                   SELECT id FROM action_types WHERE workspace_id = :wid)
         ORDER BY action_type_id, sort_order, api_name
        """,
        {"wid": str(workspace_id)},
    )
    rules = await fetch_all(
        conn,
        """
        SELECT action_type_id, kind::text AS kind, config::text AS config,
               sort_order
          FROM action_rules
         WHERE action_type_id = ANY(
                   SELECT id FROM action_types WHERE workspace_id = :wid)
         ORDER BY action_type_id, sort_order
        """,
        {"wid": str(workspace_id)},
    )
    criteria = await fetch_all(
        conn,
        """
        SELECT action_type_id, message, config::text AS config
          FROM action_criteria
         WHERE action_type_id = ANY(
                   SELECT id FROM action_types WHERE workspace_id = :wid)
         ORDER BY action_type_id, id
        """,
        {"wid": str(workspace_id)},
    )
    # p.29's form sections (§328, db 0081) and p.43-46's overrides (§329, db
    # 0082), which §326 never read at all — so an export dropped every section
    # and every override somebody had configured, silently (§341).
    sections = await fetch_all(
        conn,
        """
        SELECT id, action_type_id, title, description, columns, collapsible,
               collapsed, hidden, visible_when::text AS visible_when,
               sort_order
          FROM action_sections
         WHERE action_type_id = ANY(
                   SELECT id FROM action_types WHERE workspace_id = :wid)
         ORDER BY action_type_id, sort_order, id
        """,
        {"wid": str(workspace_id)},
    )
    overrides = await fetch_all(
        conn,
        """
        SELECT o.parameter_id, o.conditions::text AS conditions,
               o.set_hidden, o.set_required,
               o.set_default::text AS set_default, o.sort_order
          FROM action_parameter_overrides o
          JOIN action_parameters p ON p.id = o.parameter_id
         WHERE p.action_type_id = ANY(
                   SELECT id FROM action_types WHERE workspace_id = :wid)
         ORDER BY o.parameter_id, o.sort_order, o.id
        """,
        {"wid": str(workspace_id)},
    )
    sections_by: dict[str, list[dict[str, Any]]] = {}
    for row in sections:
        sections_by.setdefault(str(row["action_type_id"]), []).append(row)
    overrides_by: dict[str, list[dict[str, Any]]] = {}
    for row in overrides:
        overrides_by.setdefault(str(row["parameter_id"]), []).append(row)

    link_names = {str(l["id"]): str(l["api_name"]) for l in links}

    params_by: dict[str, list[dict[str, Any]]] = {}
    for row in parameters:
        params_by.setdefault(str(row["action_type_id"]), []).append(row)
    rules_by: dict[str, list[dict[str, Any]]] = {}
    for row in rules:
        rules_by.setdefault(str(row["action_type_id"]), []).append(row)
    criteria_by: dict[str, list[dict[str, Any]]] = {}
    for row in criteria:
        criteria_by.setdefault(str(row["action_type_id"]), []).append(row)

    return {
        "format_version": FORMAT_VERSION,
        # **Which ontology this came from**, so an importer can tell p.65's
        # first workflow (edit and put back) from its second (copy elsewhere).
        # The slug as well as the id, because a person reading the file in a
        # text editor needs to recognise it and a uuid tells them nothing.
        "workspace": {
            "id": str(workspace["id"]),
            "slug": workspace["slug"],
            "name": workspace["name"],
        },
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "object_types": [
            {
                **_pick(dict(t), TYPE_FIELDS),
                # **By api_name, like everything else.** The title property is
                # stored as an id, and an id means nothing in the workspace this
                # file might be imported into.
                "title_property": title_of.get(str(t["title_property_id"]))
                if t["title_property_id"] else None,
                "properties": [
                    _pick(dict(p), PROPERTY_FIELDS)
                    for p in by_type.get(str(t["id"]), [])
                ],
            }
            for t in types
        ],
        "link_types": [
            {
                **_pick(dict(link), LINK_FIELDS),
                "from_object_type": link["from_object_type"],
                "to_object_type": link["to_object_type"],
            }
            for link in links
        ],
        "action_types": [
            {
                **_pick(dict(a), ACTION_FIELDS),
                "object_type": a["object_type"],
                "parameters": [
                    {
                        "api_name": p["api_name"],
                        "display_name": p["display_name"],
                        "data_type": p["data_type"],
                        "required": p["required"],
                        "default_value": _json(p["default_value"]),
                        "hidden": p["hidden"],
                        "sort_order": p["sort_order"],
                        # p.36's filters (§331), which name properties and
                        # parameters and so travel verbatim — but only
                        # alongside the type they are written against, which
                        # is why they waited for §342 rather than riding §341.
                        "dropdown_filters": _json(p["dropdown_filters"]) or [],
                        # db 0083, 0085 and 0086's three pointing fields, as
                        # api_names (§342). Only the ones this parameter has.
                        **parameter_transfer.to_names(
                            {
                                "object_type_id": p["object_type_id"],
                                "dropdown_search_around": _json(
                                    p["dropdown_search_around"]),
                                "options_from": _json(p["options_from"]),
                            },
                            type_names=type_names,
                            link_names=link_names,
                        ),
                        # p.43-46's overrides (§329), nested under the parameter
                        # they belong to rather than listed beside it — they
                        # have no identity of their own and an order that is the
                        # rule (p.45: if more than one holds, the first wins).
                        "overrides": [
                            {
                                "conditions": _json(o["conditions"]),
                                "set_hidden": o["set_hidden"],
                                "set_required": o["set_required"],
                                "set_default": _json(o["set_default"]),
                                "sort_order": o["sort_order"],
                            }
                            for o in overrides_by.get(str(p["id"]), [])
                        ],
                    }
                    for p in params_by.get(str(a["id"]), [])
                ],
                # p.29's sections (§328). **Each names the parameters it holds**
                # rather than the parameter naming its section, because a
                # section has no portable identity — no api_name, and titles
                # that may repeat — so an id or an index would be a handle this
                # document invented. Naming members needs neither.
                "sections": [
                    {
                        "title": sec["title"],
                        "description": sec["description"],
                        "columns": sec["columns"],
                        "collapsible": sec["collapsible"],
                        "collapsed": sec["collapsed"],
                        "hidden": sec["hidden"],
                        "visible_when": _json(sec["visible_when"]),
                        "sort_order": sec["sort_order"],
                        "parameters": [
                            p["api_name"]
                            for p in params_by.get(str(a["id"]), [])
                            if p["section_id"] is not None
                            and str(p["section_id"]) == str(sec["id"])
                        ],
                    }
                    for sec in sections_by.get(str(a["id"]), [])
                ],
                # p.75's rules. **The config is translated, not echoed** (§343):
                # six of its fields hold a uuid — the object type three of them
                # name, the link type two of them name, and the type a notify
                # rule reads a recipient off — so an action with a `create_link`
                # rule used to put a link type's id straight into the file. The
                # assertion that nothing in the ontology is identified by id was
                # already there and passed, because no fixture had ever built a
                # rule that carried one.
                "rules": [
                    {"kind": r["kind"],
                     "config": rule_transfer.to_names(
                         {"kind": r["kind"], "config": _json(r["config"])},
                         type_names=type_names, link_names=link_names,
                     ),
                     "sort_order": r["sort_order"]}
                    for r in rules_by.get(str(a["id"]), [])
                ],
                "criteria": [
                    {"message": c["message"], "config": _json(c["config"])}
                    for c in criteria_by.get(str(a["id"]), [])
                ],
            }
            for a in actions
        ],
    }
