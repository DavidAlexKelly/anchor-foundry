"""Conversion into the Workshop module format (roadmap phase 2, item 1.1).

The decision is `docs/decisions/0002-workshop-module-format.md`; these are the
proofs it promises. What matters here is not that conversion *runs* but that it
**changes no behaviour**: the layout is untouched, every binding that worked
still resolves, and every binding that was already broken is still visibly
broken rather than quietly tidied away.

No database. Conversion is a pure function over JSON, and a test that stood up
Postgres to check a dict transform would be slower and prove less.
"""
from __future__ import annotations

import copy
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import workshop_format as wf  # noqa: E402


# A real saved definition, copied out of the development database rather than
# invented: a Filter declaring "region", a map bound to it, and a second map
# bound to nothing.
REAL_V1 = {
    "f1": {
        "type": {"resolvedName": "CanvasParameterControl"},
        "nodes": [],
        "props": {
            "name": "region",
            "label": "Region",
            "column": "region",
            "control": "select",
            "datasetId": "c484055f-fc7e-4457-b3fc-1b1e161e7d6c",
        },
        "parent": "ROOT",
        "isCanvas": False,
        "displayName": "Filter",
    },
    "ROOT": {
        "type": {"resolvedName": "CanvasContainer"},
        "nodes": ["f1", "objmap", "dsmap"],
        "props": {"padding": 12},
        "isCanvas": True,
        "displayName": "Container",
    },
    "dsmap": {
        "type": {"resolvedName": "CanvasMap"},
        "nodes": [],
        "props": {
            "limit": 500,
            "source": "dataset",
            "datasetId": "95d21b22-fd54-4bf5-8ab5-75efd2586222",
            "latColumn": "lat",
            "lonColumn": "lon",
            "filterParameter": None,
        },
        "parent": "ROOT",
        "isCanvas": False,
        "displayName": "Map",
    },
    "objmap": {
        "type": {"resolvedName": "CanvasMap"},
        "nodes": [],
        "props": {
            "limit": 500,
            "source": "objects",
            "objectTypeId": "bb18d7de-1ae6-4332-8a72-45bc5891ae55",
            "filterProperty": "region",
            "filterParameter": "region",
            "searchParameter": None,
        },
        "parent": "ROOT",
        "isCanvas": False,
        "displayName": "Map",
    },
}


def layout_shape(nodes: dict) -> dict:
    """Everything about the layout except the reference props, which are the
    only thing conversion is allowed to touch."""
    stripped = copy.deepcopy(nodes)
    for node in stripped.values():
        props = node.get("props")
        if isinstance(props, dict):
            for prop in wf.REFERENCE_PROPS:
                props.pop(prop, None)
    return stripped


# ---- the shape of the document ----------------------------------------------
def test_a_v1_document_is_recognised_without_a_marker() -> None:
    """v1 predates having anything to mark it with, so the test is structural:
    Craft.js's root is always called ROOT, and a v2 document never has one at
    the top level."""
    assert wf.is_v1(REAL_V1)
    assert not wf.is_v1(wf.convert(REAL_V1))
    assert not wf.is_v1(wf.empty_module())


def test_conversion_produces_the_three_parts_and_a_version() -> None:
    module = wf.convert(REAL_V1)
    assert module["format"] == wf.FORMAT_VERSION
    assert set(module) >= {"format", "layout", "variables", "events"}
    assert module["events"] == {}, "v1 had no events to convert"


# ---- the layout survives -----------------------------------------------------
def test_the_layout_is_carried_across_untouched() -> None:
    """The one part of Canvas that is not in question. If conversion moved a
    node or dropped a prop, every app would render differently the day the
    format changed."""
    module = wf.convert(REAL_V1)
    assert layout_shape(module["layout"]) == layout_shape(REAL_V1)
    assert module["layout"]["ROOT"]["nodes"] == ["f1", "objmap", "dsmap"]


def test_the_input_is_not_mutated() -> None:
    """The migration reads a row and writes a new version; a converter that
    edited its argument would corrupt whatever the caller still held."""
    before = copy.deepcopy(REAL_V1)
    wf.convert(REAL_V1)
    assert REAL_V1 == before


# ---- declarations ------------------------------------------------------------
def test_each_named_filter_declares_exactly_one_variable() -> None:
    module = wf.convert(REAL_V1)
    assert len(module["variables"]) == 1
    variable = next(iter(module["variables"].values()))
    assert variable["legacy_name"] == "region"
    assert variable["label"] == "Region"
    assert variable["kind"] == "string"


def test_a_node_whose_type_is_a_plain_string_is_handled() -> None:
    """Craft.js writes `type` as {"resolvedName": …} for a registered component
    and as a bare string for a plain element. The fixture above was copied from
    an app that only had the first form; running the converter over every app
    in a real database found the second on the first try, as an
    AttributeError."""
    v1 = copy.deepcopy(REAL_V1)
    v1["plain"] = {"type": "div", "nodes": [], "props": {}, "parent": "ROOT"}
    v1["ROOT"]["nodes"].append("plain")

    module = wf.convert(v1)
    assert module["layout"]["plain"]["type"] == "div"
    assert len(module["variables"]) == 1


def test_an_unnamed_filter_declares_nothing() -> None:
    """A Filter with no name is the half-configured widget the builder tells
    you to finish. It declared no parameter before and declares no variable
    now."""
    v1 = copy.deepcopy(REAL_V1)
    v1["f1"]["props"]["name"] = ""
    module = wf.convert(v1)
    assert module["variables"] == {}


def test_two_filters_sharing_a_name_share_one_variable() -> None:
    """They share a parameter today. Splitting them would silently change an
    app that currently works, which a conversion may not do."""
    v1 = copy.deepcopy(REAL_V1)
    v1["f2"] = copy.deepcopy(v1["f1"])
    v1["f2"]["props"]["label"] = "Region (again)"
    v1["ROOT"]["nodes"].append("f2")

    module = wf.convert(v1)
    assert len(module["variables"]) == 1
    assert module["layout"]["objmap"]["props"]["filterParameter"] in module["variables"]


def test_the_variable_id_is_not_derived_from_the_name() -> None:
    """A label-derived id is a rename waiting to break every reference - the
    exact failure this format removes."""
    module = wf.convert(REAL_V1)
    variable_id = next(iter(module["variables"]))
    assert "region" not in variable_id


# ---- references --------------------------------------------------------------
def test_a_working_binding_is_rewritten_to_the_variable_id() -> None:
    module = wf.convert(REAL_V1)
    expected = wf.variable_for_legacy_name(module, "region")
    assert expected is not None
    assert module["layout"]["objmap"]["props"]["filterParameter"] == expected
    # …and no longer the bare name it used to match on.
    assert module["layout"]["objmap"]["props"]["filterParameter"] != "region"


def test_an_unbound_reference_is_left_alone() -> None:
    module = wf.convert(REAL_V1)
    assert module["layout"]["dsmap"]["props"]["filterParameter"] is None
    assert module["layout"]["objmap"]["props"]["searchParameter"] is None


def test_a_broken_binding_is_recorded_rather_than_tidied_away() -> None:
    """A reference to a parameter nothing declares has silently read as "no
    filter" for as long as it has existed - the map shows *more* rows than it
    should. The app is already wrong; a converter that quietly fixed the
    document would destroy the only evidence of it."""
    v1 = copy.deepcopy(REAL_V1)
    v1["objmap"]["props"]["searchParameter"] = "typo_never_declared"

    module = wf.convert(v1)
    assert module["layout"]["objmap"]["props"]["searchParameter"] == "typo_never_declared"
    assert module["broken_bindings"] == [
        {"node": "objmap", "prop": "searchParameter", "parameter": "typo_never_declared"}
    ]


def test_a_clean_app_records_no_broken_bindings() -> None:
    assert "broken_bindings" not in wf.convert(REAL_V1)


# ---- running it twice --------------------------------------------------------
def test_converting_twice_is_the_same_as_converting_once() -> None:
    """The migration must be safe to re-run - and a second pass must not treat
    the variable *ids* it wrote as parameter names to look up again."""
    once = wf.convert(REAL_V1)
    twice = wf.convert(once)
    assert once == twice


@pytest.mark.parametrize("definition", [{}, {"format": 2, "layout": {}, "variables": {}, "events": {}}])
def test_degenerate_documents_convert_to_something_renderable(definition: dict) -> None:
    """An app saved before anybody put a widget on it. It has to come out as a
    valid empty module rather than as a KeyError during a migration."""
    module = wf.convert(definition)
    assert module["format"] == wf.FORMAT_VERSION
    assert module["layout"] == {}
