"""What a module references (Foundry `workshop` p.92's Check access panel).

> "This will show if they meet the access requirement on the Workshop module,
> as well as additional data requirements to see object types, link types,
> action types, and functions." (p.92)

The *requirements* half is this walk: which ontology resources a module names.
Whether a given user can see them is asked of row-level security by the route,
because a second copy of those rules here would be free to disagree with the
one that actually decides (§146).
"""
from __future__ import annotations

from src.services import module_access as ma

TYPE_A = "11111111-1111-1111-1111-111111111111"
TYPE_B = "22222222-2222-2222-2222-222222222222"
ACTION = "33333333-3333-3333-3333-333333333333"
LINK = "44444444-4444-4444-4444-444444444444"


def test_an_empty_or_unreadable_definition_names_nothing() -> None:
    for raw in (None, {}, [], "module", 7):
        assert ma.referenced(raw) == {
            "object_types": [], "action_types": [], "link_types": [],
        }


def test_an_object_set_variable_names_its_type() -> None:
    """The commonest way a module reaches the ontology, and the one a builder
    is most likely to be debugging when they open this panel."""
    got = ma.referenced({
        "variables": {
            "v_all": {"kind": "object_set", "object_set": {"object_type_id": TYPE_A}},
        },
    })
    assert got["object_types"] == [TYPE_A]


def test_a_widget_that_names_a_type_directly_counts_too() -> None:
    """p.65's other half of how a table is populated: an object type picked on
    the widget rather than a bound set. A walk that read only the variables
    would report no data requirement for a module built that way."""
    got = ma.referenced({
        "layout": {
            "tbl": {"props": {"objectTypeId": TYPE_A}},
            "title": {"props": {"placeholderTypeId": TYPE_B}},
        },
    })
    assert got["object_types"] == sorted([TYPE_A, TYPE_B])


def test_action_types_come_from_widgets_and_from_events() -> None:
    """An action reaches a module two ways — a form that submits it and a
    button whose event runs it — and a user who cannot use it fails the same
    way in both."""
    got = ma.referenced({
        "layout": {
            "form": {"props": {"actionTypeId": ACTION}},
            "tbl": {"props": {"inlineEditAction": ACTION}},
        },
        "events": {
            "e1": {"effects": [{"type": "run_action", "config": {"action": ACTION}}]},
        },
    })
    assert got["action_types"] == [ACTION]


def test_a_link_type_is_found_however_deeply_it_is_nested() -> None:
    """p.92 names link types, and they are never at the top level: a traversal
    sits inside an object set inside a variable, and a derived property's chain
    sits inside a property inside a type. A list of known paths would be a list
    the next nesting outgrows, so the walk is structural."""
    got = ma.referenced({
        "variables": {
            "v_near": {
                "kind": "object_set",
                "object_set": {
                    "object_type_id": TYPE_A,
                    "via": {"link_type_id": LINK, "base": {"object_type_id": TYPE_B}},
                },
            },
        },
    })
    assert got["link_types"] == [LINK]
    assert got["object_types"] == sorted([TYPE_A, TYPE_B])


def test_each_resource_is_named_once_however_many_widgets_use_it() -> None:
    """A panel listing the same object type four times because four widgets
    read it is a panel nobody reads twice."""
    got = ma.referenced({
        "variables": {
            "v1": {"object_set": {"object_type_id": TYPE_A}},
            "v2": {"object_set": {"object_type_id": TYPE_A}},
        },
        "layout": {
            "a": {"props": {"objectTypeId": TYPE_A}},
            "b": {"props": {"objectTypeId": TYPE_A}},
        },
    })
    assert got["object_types"] == [TYPE_A]


def test_it_reads_the_document_rather_than_what_rendered() -> None:
    """p.92's panel is about the *module*. A widget on a page nobody has
    opened still needs its object type, so a walk over what happens to be on
    screen would report fewer requirements than the module has."""
    got = ma.referenced({
        "layout": {
            "page_two_table": {"props": {"objectTypeId": TYPE_B}, "parent": "page_two"},
        },
    })
    assert got["object_types"] == [TYPE_B]


def test_a_malformed_node_does_not_stop_the_walk() -> None:
    """§212: a layout document holds whatever was put there. One unreadable
    node must not hide every requirement after it — an under-reported
    requirement is the failure this panel exists to prevent."""
    got = ma.referenced({
        "layout": {
            "broken": "not a node",
            "also_broken": {"props": "not props"},
            "fine": {"props": {"objectTypeId": TYPE_A}},
        },
        "events": {"bad": "not an event", "ok": {"effects": [
            "not an effect", {"config": {"action": ACTION}},
        ]}},
        "variables": {"bad": "not a variable"},
    })
    assert got["object_types"] == [TYPE_A]
    assert got["action_types"] == [ACTION]


def test_a_links_widget_names_the_link_types_it_shows() -> None:
    """p.272's "Link types to display", stored as `"<id>:<direction>"` because
    a self-link occupies both ends and the id alone names two rows (§272).

    **Found by §412's mutation sweep, as a real under-report.** No walk over
    field names can see an id that is half a string, so a widget configured
    with three link types asked for none of them - and a reader who could see
    none of the three would have been told every requirement was met.
    """
    got = ma.referenced({
        "layout": {
            "links": {"props": {"links": [
                {"key": f"{LINK}:outgoing", "label": "Orders"},
                # The same type at its other end is one requirement, not two.
                {"key": f"{LINK}:incoming"},
                "not a link", {"key": ""}, {"no": "key"},
            ]}},
        },
    })
    assert got["link_types"] == [LINK]


def test_a_column_declared_on_a_type_names_that_type() -> None:
    """p.168: "Derived properties are defined at the module level and per
    object type" (§411) - so the map is keyed *by* object type id, and a walk
    over values cannot reach a key.

    A module whose only mention of a type is a column it declares on that type
    still needs the type to draw the column.
    """
    got = ma.referenced({
        "derived_properties": {
            TYPE_B: [{"api_name": "margin", "kind": "column_math",
                      "expression": "revenue - cost"}],
            "": [],
        },
        "layout": {"t": {"props": {"objectTypeId": TYPE_A}}},
    })
    assert got["object_types"] == [TYPE_A, TYPE_B]


def test_a_malformed_derived_property_map_does_not_stop_the_walk() -> None:
    """§212 again: the raw editor can hold anything, including a list where a
    map belongs."""
    got = ma.referenced({
        "derived_properties": ["not a map"],
        "layout": {"t": {"props": {"objectTypeId": TYPE_A}}},
    })
    assert got["object_types"] == [TYPE_A]
