"""The declared types a module is checked and cast against (§831).

`ontology.property_types_for_workspace` reads two columns where
`list_properties_for_workspace` reads every property's whole description;
evaluation runs on every keystroke in a filter, and building the rest was half
its time. It must give exactly the map the full listing gave, reduced the way
`routes/canvas._workspace_property_types` used to reduce it - including a
property's type coming from its shared property, and from one the caller
cannot see.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture  # noqa: E402
from test_canvas_app_workspace import as_service  # noqa: E402
from test_object_instance_workspace import admin, workspace  # noqa: E402


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


def reduced(full: dict) -> dict:
    """The map as `_workspace_property_types` built it before §831."""
    return {
        type_id: {str(p["api_name"]): str(p["data_type"])
                  for p in props if p.get("api_name") and p.get("data_type")}
        for type_id, props in full.items()
    }


def a_type(fx, wid) -> uuid.UUID:
    return admin("INSERT INTO object_types (workspace_id, api_name, display_name, created_by) "
                 "VALUES (%s,%s,'T',%s) RETURNING id",
                 (wid, f"t_{uuid.uuid4().hex[:8]}", fx.owner))[0][0]


def shared(fx, wid, data_type: str) -> uuid.UUID:
    return admin("INSERT INTO shared_properties (workspace_id, api_name, display_name, data_type) "
                 "VALUES (%s,%s,'S',%s) RETURNING id",
                 (wid, f"s_{uuid.uuid4().hex[:8]}", data_type))[0][0]


def test_the_lean_map_is_the_full_listing_reduced(fx) -> None:
    from src.services import ontology

    type_id = a_type(fx, fx.workspace)
    mine = shared(fx, fx.workspace, "integer")
    # Another organisation's: attached here only by writing past every check,
    # which is the one way a property's shared property is not visible to
    # someone who can see the property.
    hidden = shared(fx, workspace(fx, fx.other_org), "date")
    admin("""INSERT INTO object_type_properties
                 (object_type_id, api_name, display_name, data_type, shared_property_id)
             VALUES (%s,'plain','Plain','string',NULL),
                    (%s,'counted','Counted','string',%s),
                    (%s,'hidden','Hidden','string',%s)""",
          (type_id, type_id, mine, type_id, hidden))
    a_type(fx, fx.workspace)  # a type with no properties at all

    lean = as_service(fx.owner, lambda c: ontology.property_types_for_workspace(c, fx.workspace))
    full = as_service(fx.owner, lambda c: ontology.list_properties_for_workspace(c, fx.workspace))
    assert lean == reduced(full)
    # And what that means, said outright: the shared property's type wins, and
    # one the caller cannot see gives the property no type.
    assert lean[str(type_id)] == {"plain": "string", "counted": "integer"}


def test_the_map_can_be_narrowed_to_named_types(fx) -> None:
    from src.services import ontology

    first, second = a_type(fx, fx.workspace), a_type(fx, fx.workspace)
    admin("INSERT INTO object_type_properties (object_type_id, api_name, display_name, data_type) "
          "VALUES (%s,'a','A','string'), (%s,'b','B','integer')", (first, second))
    narrowed = as_service(fx.owner, lambda c: ontology.property_types_for_workspace(
        c, fx.workspace, type_ids=[str(first)]))
    assert narrowed == {str(first): {"a": "string"}}
