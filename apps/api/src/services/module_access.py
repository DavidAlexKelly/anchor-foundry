"""The Check access panel (Foundry ``workshop`` p.92).

> "You can use the Check access panel in the sidebar to easily check a user's
> access on a Workshop module. This will show if they meet the access
> requirement on the Workshop module, as well as **additional data
> requirements to see object types, link types, action types, and
> functions**." (p.92)

The whole feature exists because of the sentence above it:

> "Note that the ability to open or edit a Workshop module is separate from
> the ability to access the data, actions, or functions which may be needed to
> fully use a Workshop module." (p.92)

So "can they open it" is the easy half and the useless one on its own. A
viewer with the module role and no access to the object type behind its main
table opens a page of empty widgets, and the builder who shared it has no way
to see why. This answers both halves in one place.

---

**The answer is asked, not re-derived.** Visibility is resolved by opening a
connection *as the named user* and reading the resource, so the answer comes
from the same row-level security a real read would meet. A second copy of the
rules here would be §146's second matcher: free to disagree with the one that
actually decides, and wrong in exactly the cases somebody opens this panel to
understand.

**It grants nothing and reveals only what the module already names.** The
resources asked about are the ones this module references - discovered from
its own definition below - so the panel cannot be used to probe the ontology
at large. What it adds is the *pairing*: this user, these resources.

**Functions are absent** (p.92 names them fourth). This platform has no
function permissions to check because it has no functions; the parity doc
carries that as `[fn]` and this is not the place to invent one.
"""
from __future__ import annotations

from typing import Any

#: Widget props that hold an object type id, mirroring the widgets that have
#: one. Kept beside the variable walk rather than in the browser, because the
#: question "what does this module reference" is about the stored document.
_TYPE_PROPS = ("objectTypeId", "placeholderTypeId")

#: Widget props that hold an action type id.
_ACTION_PROPS = ("actionTypeId", "inlineEditAction")


def _walk_nodes(layout: Any) -> list[dict[str, Any]]:
    if not isinstance(layout, dict):
        return []
    return [n for n in layout.values() if isinstance(n, dict)]


def _ids_named(node: Any, key_name: str, out: set[str]) -> None:
    """Every id stored under ``key_name``, however deeply it is nested.

    **Structural rather than a list of known paths**, and the first draft of
    this was the list. A traversal sits inside an object set inside a variable,
    and its `base` is another object set with its own `object_type_id`; a
    derived property's chain sits inside a property inside a type. Reading only
    the variable's top-level `object_set` reported the *near* type of a
    traversal and silently dropped the one it starts from — an under-reported
    requirement, which is the exact failure this panel exists to prevent.

    A list of paths is a list the next nesting outgrows. The key name is the
    fact worth relying on.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if key == key_name and isinstance(value, str) and value:
                out.add(value)
            else:
                _ids_named(value, key_name, out)
    elif isinstance(node, list):
        for item in node:
            _ids_named(item, key_name, out)


def referenced(definition: Any) -> dict[str, list[str]]:
    """Every ontology resource this module names, by kind.

    **From the document, not from what rendered.** p.92's panel is about the
    module, and a widget on a page nobody has opened still needs its object
    type - a walk over what happens to be on screen would report fewer
    requirements than the module actually has.
    """
    if not isinstance(definition, dict):
        return {"object_types": [], "action_types": [], "link_types": []}

    object_types: set[str] = set()
    action_types: set[str] = set()
    links: set[str] = set()

    _ids_named(definition, "object_type_id", object_types)
    _ids_named(definition, "link_type_id", links)

    for node in _walk_nodes(definition.get("layout")):
        props = node.get("props")
        if not isinstance(props, dict):
            continue
        for key in _TYPE_PROPS:
            value = props.get(key)
            if isinstance(value, str) and value:
                object_types.add(value)
        for key in _ACTION_PROPS:
            value = props.get(key)
            if isinstance(value, str) and value:
                action_types.add(value)

    events = definition.get("events")
    if isinstance(events, dict):
        for event in events.values():
            if not isinstance(event, dict):
                continue
            for effect in event.get("effects") or []:
                if not isinstance(effect, dict):
                    continue
                config = effect.get("config")
                if not isinstance(config, dict):
                    continue
                action = config.get("action")
                if isinstance(action, str) and action:
                    action_types.add(action)

    return {
        "object_types": sorted(object_types),
        "action_types": sorted(action_types),
        "link_types": sorted(links),
    }
