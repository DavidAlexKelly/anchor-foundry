"""The Workshop module document, and conversion into it.

Decided in `docs/decisions/0002-workshop-module-format.md`; this is that
decision as code. Read it first - the *why* lives there and is not repeated
here.

**This is a format tool, not part of the request path.** `services/canvas.py`
stores and versions an opaque blob and still does not interpret it; keeping
that true is deliberate. Nothing that serves an HTTP request imports this
module - the one-shot conversion (roadmap item 1.8) does, and so do its tests.

The conversion is a pure function over JSON. It never asks what a widget
*renders*; it only knows which props name a parameter, which is the smallest
thing it can know and still do the job.
"""
from __future__ import annotations

import copy
from typing import Any

FORMAT_VERSION = 2

# The one widget that brings a parameter into existence today, and the prop it
# does it with. A parameter exists because somebody dropped a Filter on the
# page and typed a name into it - which is the implicit declaration this format
# replaces (decision 0002, "a variable is declared as a side effect").
DECLARING_WIDGET = "CanvasParameterControl"
DECLARING_PROP = "name"

# Props whose value is the *name of a parameter to read*. Listed explicitly
# rather than matched on a "*Parameter" suffix: a rule that clever would sweep
# up the next prop somebody names that way and rewrite a value that was never
# a reference.
REFERENCE_PROPS = ("filterParameter", "searchParameter")


def is_v1(definition: dict[str, Any]) -> bool:
    """A v1 document is a bare Craft.js node map; a v2 one has `layout`.

    Told apart structurally rather than by a marker, because v1 documents were
    written before there was anything to mark them with. `ROOT` is Craft.js's
    own fixed name for the tree root, so its presence at the top level is the
    reliable signal - and a v2 document never has one there.
    """
    return "layout" not in definition and "ROOT" in definition


def empty_module() -> dict[str, Any]:
    return {"format": FORMAT_VERSION, "layout": {}, "variables": {}, "events": {}}


def _resolved_name(node: dict[str, Any]) -> str:
    """A Craft.js node's component name.

    `type` is `{"resolvedName": "CanvasMap"}` for a registered component and a
    bare string for a plain element (`"div"`). Both occur in saved apps here -
    found by running the converter over every app in a real database, having
    written the fixture from one that only had the first form.
    """
    node_type = node.get("type")
    if isinstance(node_type, dict):
        return str(node_type.get("resolvedName") or "")
    return str(node_type or "")


def _variable_id(node_id: str) -> str:
    """Opaque, stable, and *not* derived from the parameter's name.

    Derived from the declaring node instead. A label-derived id would be a
    rename waiting to break every reference - the exact failure this format
    exists to remove - while the node id is fixed for the life of the widget.
    Deterministic rather than random so that converting the same document twice
    produces the same document.
    """
    return f"v_{node_id}"


def convert(definition: dict[str, Any]) -> dict[str, Any]:
    """v1 (or v2) in, v2 out. Idempotent.

    The layout is carried across unchanged apart from the reference props,
    which are rewritten from parameter *names* to variable *ids*.
    """
    if not definition:
        return empty_module()
    if not is_v1(definition):
        # Already converted. Returned as-is rather than rebuilt, so running the
        # migration twice cannot quietly renumber anything.
        return copy.deepcopy(definition)

    layout = copy.deepcopy(definition)

    # ---- declarations --------------------------------------------------------
    # Grouped by declared name, because two Filters sharing a name share a
    # parameter today. Giving them a variable each would silently split an app
    # that currently works - a conversion may not change behaviour.
    declared: dict[str, str] = {}  # parameter name -> variable id
    variables: dict[str, Any] = {}
    for node_id in sorted(layout):  # sorted: deterministic when names collide
        node = layout[node_id]
        if not isinstance(node, dict):
            continue
        if _resolved_name(node) != DECLARING_WIDGET:
            continue
        props = node.get("props") or {}
        name = props.get(DECLARING_PROP)
        if not name or not isinstance(name, str):
            # A Filter with no name declares nothing - it is the half-configured
            # widget the builder tells you to finish, and it stays that way.
            continue
        if name in declared:
            continue
        variable_id = _variable_id(node_id)
        declared[name] = variable_id
        variables[variable_id] = {
            "id": variable_id,
            # Every parameter today is an untyped scalar set by a Filter, so
            # that is what they convert to. Object-set variables (item 1.2)
            # have no v1 equivalent to convert *from*.
            "kind": "string",
            "label": props.get("label") or name,
            # What this variable was called when it was a string-keyed
            # parameter. Kept so a converted app can still be read against the
            # v1 document it came from.
            "legacy_name": name,
        }

    # ---- references ----------------------------------------------------------
    broken: list[dict[str, str]] = []
    for node_id in sorted(layout):
        node = layout[node_id]
        if not isinstance(node, dict):
            continue
        props = node.get("props")
        if not isinstance(props, dict):
            continue
        for prop in REFERENCE_PROPS:
            name = props.get(prop)
            if not name or not isinstance(name, str):
                continue
            if name in declared:
                props[prop] = declared[name]
            else:
                # A reference to a parameter nothing declares. The app is
                # already wrong - this binding has silently read as "no
                # filter" for as long as it has existed - and a converter that
                # tidied it away would destroy the only evidence of it. Left
                # in place, and recorded.
                broken.append({"node": node_id, "prop": prop, "parameter": name})

    module: dict[str, Any] = {
        "format": FORMAT_VERSION,
        "layout": layout,
        "variables": variables,
        "events": {},
    }
    if broken:
        module["broken_bindings"] = broken
    return module


def variable_for_legacy_name(module: dict[str, Any], name: str) -> str | None:
    """The variable a v1 parameter name became, if any. For the builder's
    "what happened to my parameter?" affordance and for tests."""
    for variable in module.get("variables", {}).values():
        if variable.get("legacy_name") == name:
            return str(variable["id"])
    return None
