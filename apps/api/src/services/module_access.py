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

So "can they open it" is the easy half and the useless one on its own, and on
this platform the two halves genuinely come apart. A module published to the
workspace opens for any workspace viewer; **running** an action is a project
editor's right on the module's own project. That reader gets the page, gets
the Action Form, and gets a refusal at the button — and the builder who
published it has no way to find that out short of borrowing their account.
This answers both halves in one place, before anybody presses anything.

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
from uuid import UUID

from ..lib.errors import NotFoundError
from . import actions, ontology
from .canvas import get_published

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


# ---- resolving one user's access ---------------------------------------------
#: p.92's kinds, in p.92's order ("object types, link types, action types, and
#: functions"), each paired with the key `referenced` files it under and the
#: read that decides whether a user may see one.
#:
#: **The read is the platform's own.** Asking `ontology.get_type` the question
#: on a connection opened as the named user is the same call the route serving
#: that user makes, so the panel cannot drift from what a real request would
#: get. Spelling out the RLS predicate here instead would be §146's second
#: matcher, free to disagree with the one that decides.
_KINDS: tuple[tuple[str, str, Any], ...] = (
    ("object_types", "object_type", ontology.get_type),
    ("link_types", "link_type", ontology.get_link_type),
    ("action_types", "action_type", actions.get_action_type),
)


def _as_uuid(raw: str) -> UUID | None:
    try:
        return UUID(raw)
    except (ValueError, AttributeError, TypeError):
        return None


async def resources(
    conn,
    caller_conn,
    *,
    workspace_id: UUID,
    definition: Any,
    may_run_actions: bool,
) -> list[dict[str, Any]]:
    """Every resource the module needs, and how the user behind ``conn`` stands
    to each one.

    ``caller_conn`` is the *asking* user's connection and is used only to put a
    name on a resource the subject cannot see. Without it every hidden row
    would read "hidden: <uuid>", which tells the builder that something is
    wrong and nothing about what — and the builder is already entitled to that
    name, because it is in a module they are looking at.

    One field rather than a flag beside it. A `visible` boolean and a `status`
    string are two answers to one question, and the pair only has to disagree
    once to make the panel worse than nothing (§146). The four states are:

    ``visible``
        They can read it, and for an action type they can also run it.
    ``unusable``
        p.92's sentence in one word. An action type they can *read* — every
        workspace member can — but cannot **run**, because running one is a
        project editor's right on the module's own project. This is what a
        published module's reader actually hits: the form draws, the button
        refuses, and until now nothing said so before they pressed it.
    ``hidden``
        They cannot read it and the asker can name it.
    ``unknown``
        Neither can (§210). A dangling reference to something deleted or never
        created — calling that a permission problem would send the builder to
        ask an administrator for a grant that would not help.
    """
    found = referenced(definition)
    out: list[dict[str, Any]] = []
    for key, kind, read in _KINDS:
        for raw in found[key]:
            rid = _as_uuid(raw)
            row: dict[str, Any] | None = None
            if rid is not None:
                try:
                    row = await read(conn, workspace_id, rid)
                except NotFoundError:
                    row = None
            if row is not None:
                usable = may_run_actions or kind != "action_type"
                out.append({
                    "kind": kind, "id": raw, "name": row["display_name"],
                    "status": "visible" if usable else "unusable",
                })
                continue
            name: str | None = None
            if rid is not None:
                try:
                    name = (await read(caller_conn, workspace_id, rid))["display_name"]
                except NotFoundError:
                    name = None
            out.append({
                "kind": kind, "id": raw, "name": name,
                "status": "hidden" if name is not None else "unknown",
            })
    return out


async def opens(conn, *, workspace_id: UUID, app_id: UUID, project_role: str | None) -> bool:
    """Whether the user behind ``conn`` can open the module at all.

    p.92 calls this "the access requirement on the Workshop module", and it has
    two doors: membership of the module's own project, or the module having
    been published to a workspace they belong to. Checking only the first would
    report no access for every reader a published module was made for.

    The published door is *opened*, not described: `get_published` carries the
    `publish_scope <> 'private'` clause and RLS carries the group shares, and
    both are asked here by making the read.
    """
    if project_role is not None:
        return True
    try:
        await get_published(conn, workspace_id, app_id)
    except NotFoundError:
        return False
    return True
