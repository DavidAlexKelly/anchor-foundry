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
})


def _json(value: Any) -> Any:
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
               status::text AS status, deprecation,
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
               visibility::text AS visibility, value_format, conditional_format,
               edit_only, derivation, struct_fields, status::text AS status,
               deprecation, id
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

    links = await fetch_all(
        conn,
        """
        SELECT lt.api_name, lt.display_name, lt.cardinality::text AS cardinality,
               lt.from_property, lt.to_property,
               lt.from_side_name, lt.to_side_name,
               lt.status::text AS status, lt.deprecation,
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
               at.status::text AS status, at.deprecation, at.allow_revert,
               ot.api_name AS object_type
          FROM action_types at
          JOIN object_types ot ON ot.id = at.object_type_id
         WHERE at.workspace_id = :wid
         ORDER BY at.api_name
        """,
        {"wid": str(workspace_id)},
    )
    parameters = await fetch_all(
        conn,
        """
        SELECT action_type_id, api_name, display_name,
               data_type::text AS data_type, required, default_value, hidden,
               sort_order
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
        SELECT action_type_id, kind::text AS kind, config, sort_order
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
        SELECT action_type_id, message, config
          FROM action_criteria
         WHERE action_type_id = ANY(
                   SELECT id FROM action_types WHERE workspace_id = :wid)
         ORDER BY action_type_id, id
        """,
        {"wid": str(workspace_id)},
    )
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
                    }
                    for p in params_by.get(str(a["id"]), [])
                ],
                "rules": [
                    {"kind": r["kind"], "config": _json(r["config"]),
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
