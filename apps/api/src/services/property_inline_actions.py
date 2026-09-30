"""A property's inline action (§594; db 0126; `workshop` p.266,
`object-views` p.67, `object-link-types` p.148).

    "To enable inline editing for a property, configure an inline action for
     the property in the Ontology Manager. Once the inline action is
     configured, users can edit property values directly within the Property
     List widget." (`workshop` p.266)

    "Make a property editable: If you wish to make a property editable, set up
     an action type or an inline action." (`object-views` p.67)

**An inline action is an action type that can back an inline edit** (§238's
`inline_edit_refusals`, empty) **and that writes this property from a
parameter**: one `modify_object` rule on the action's own object, reading the
parameter an edit in place fills. Every other parameter defaults to the
object's existing value (`action-types` p.135), so a one-value edit is a legal
submission of it - which is what makes one action per property enough.

**Checked when set, and again where it is used.** The action can change after
it is chosen (a rule removed, a criterion added that makes it ineligible), and
db 0126's foreign key only covers its deletion. So a surface re-reads the
action and draws no editor when it no longer backs the property, rather than
trusting what was true when the Ontology Manager saved it.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.errors import NotFoundError


def parameter_for(action_type: dict[str, Any], property_name: str) -> str | None:
    """The parameter `action_type` writes `property_name` from, or None when
    no rule on its own object writes it."""
    for rule in action_type.get("rules") or []:
        config = rule.get("config") or {}
        if (str(rule.get("kind")) == "modify_object" and not config.get("object")
                and config.get("property") == property_name and config.get("parameter")):
            return str(config["parameter"])
    return None


def check(property_name: str, action_type: dict[str, Any], type_id: UUID | None) -> None:
    """Refuse an action that could not edit this property in place, saying
    why in the Ontology Manager's words."""
    from .actions import inline_edit_refusals

    name = action_type.get("display_name") or action_type.get("api_name")
    if type_id is None or str(action_type.get("object_type_id")) != str(type_id):
        raise ValueError(
            f"{property_name}: {name!r} acts on another object type, so it cannot edit "
            "this one's property"
        )
    refusals = inline_edit_refusals(action_type)
    if refusals:
        raise ValueError(f"{property_name}: {name!r} cannot back an inline edit: {refusals[0]}")
    if parameter_for(action_type, property_name) is None:
        raise ValueError(
            f"{property_name}: {name!r} does not write this property from a parameter, "
            "so an edit to it would change nothing"
        )


async def apply(
    conn: AsyncConnection, workspace_id: UUID, type_id: UUID | None,
    properties: list[dict[str, Any]],
) -> None:
    """Check each property's inline action and normalise it in place.

    `type_id` is None for a type being created, which no action can act on
    yet, so any inline action given for one is refused by `check`."""
    from .actions import get_action_type

    for prop in properties:
        raw = prop.get("inline_action_type_id")
        if not raw:
            prop["inline_action_type_id"] = None
            continue
        name = str(prop["api_name"])
        if prop.get("derivation") is not None:
            # `object-link-types` p.148: "Properties with inline actions
            # configured cannot be converted to derived properties."
            raise ValueError(
                f"{name}: a derived property is computed, so it has no inline action "
                "(object-link-types p.148)"
            )
        try:
            action_type = await get_action_type(conn, workspace_id, UUID(str(raw)))
        except (NotFoundError, ValueError) as exc:
            raise ValueError(f"{name}: no action type {raw} in this workspace") from exc
        check(name, action_type, type_id)
        prop["inline_action_type_id"] = str(action_type["id"])
