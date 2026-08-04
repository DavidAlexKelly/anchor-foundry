"""Workshop events (roadmap phase 2, item 1.3; decision 0002).

An event is a **trigger** — which widget, what happened — and an **ordered list
of effects**. Both live beside the layout rather than inside a widget's props,
because an event routinely spans widgets: a row click that sets a variable a
chart reads. Nesting it inside the row's widget would make the chart's
behaviour depend on a node the chart cannot see, which is the design decision
0002 exists to replace.

**This module validates; it does not execute.** Effects run in the browser,
where the clicks are. What lives here is the set of refusals — the things that
must not be saveable, because their failure mode is an app that behaves oddly
rather than one that reports a problem:

  - a trigger on a node the layout does not contain,
  - an effect that sets a variable the module does not declare,
  - an effect that sets a **derived** variable, whose value is a function of
    its inputs; honouring that write would let one document show two different
    things depending on which write the reader believed,
  - an `open_url` with no url, or one pointing at a scheme a browser will not
    navigate to safely.

The execution semantics matter as much and are enforced on the other side (see
`components/canvas/events.ts`): effects run **in configured order** and do not
await each other's downstream recomputation, and setting a variable copies the
value immediately so the next effect sees it. Foundry behaves this way, and the
alternative — awaiting each effect — produces different results for the same
configuration, which is invisible until somebody's app misbehaves.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# What a widget can announce. Deliberately short and named after the user's
# act rather than the widget's implementation: `row_select` means the same
# thing whether it came from an object table or a dataset table.
TRIGGERS = ("click", "row_select", "change")

# Effects that run entirely in the browser.
EFFECTS = ("set_variable", "open_url", "navigate", "close_overlay")

# Named, refused, and each blocked on something real rather than on effort:
# `run_action` needs the action's parameters bound to variables, which is its
# own design question; `export` needs a download surface the viewer route does
# not have. Refusing with the reason beats accepting and silently doing
# nothing, which is what an unknown effect type would otherwise do.
#
# `navigate` moved out of this list with item 1.4: pages exist now.
PLANNED_EFFECTS = ("run_action", "export")

# The layout node type that is a page (roadmap 1.4). A page is a *node in the
# layout tree* rather than a separate document, so the builder keeps editing
# one tree and decision 0002's "the layout is a Craft.js tree" stays true.
PAGE_WIDGET = "CanvasPage"

# An overlay is a layer *over* a page rather than a page you go to - Foundry's
# modals and drawers, for content that should not navigate you away. It is the
# same kind of node as a page, so `navigate` accepts either and the difference
# is what the browser does with it: a page replaces, an overlay covers and can
# be closed back to what was underneath.
OVERLAY_WIDGET = "CanvasOverlay"

# The module header - Foundry's persistent toolbar, holding the module-wide
# title, the tabs and any module-wide buttons. It is not a navigation target:
# it is always showing, so an effect that "went to" it would mean nothing.
HEADER_WIDGET = "CanvasHeader"

# What a `set_variable` may write instead of a template value.
#
# `object` is the object the trigger was about - the row somebody clicked -
# written whole into a `single_object` variable. One entry for now, but a named
# list rather than a boolean because "the set the trigger was about" is the
# obvious next one and would otherwise arrive as a second flag.
SET_SOURCES = ("object",)

# Effects that close what a navigate opened. Separate from `navigate` rather
# than "navigate to nothing", because closing an overlay returns you to the
# page you were on - which navigate has no way to name.
CLOSE_EFFECT = "close_overlay"

# A url effect may only send somebody somewhere a browser treats as a document.
# `javascript:` is the one that matters - an app author is not necessarily
# trusted by everyone who opens the app, and a published app is opened by the
# whole workspace.
URL_SCHEMES = ("http://", "https://", "mailto:", "/")

MAX_EVENTS = 100
MAX_EFFECTS = 20


class EventError(ValueError):
    """Refusal, phrased for whoever is building the app."""


@dataclass(frozen=True)
class Effect:
    type: str
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Event:
    id: str
    node: str
    on: str
    effects: tuple[Effect, ...] = ()


def pages(layout: Any, *, widget: str = PAGE_WIDGET) -> list[str]:
    """Node ids of every page in a layout, in the order the tree lists them.

    Read from the layout rather than stored beside it, for the reason
    `usages()` reads references rather than trusting an index: a second copy of
    a fact disagrees with the first the moment something deletes a node without
    knowing to update it.
    """
    if not isinstance(layout, dict):
        return []
    found: list[str] = []
    # ROOT's own child order is the page order somebody arranged in the
    # builder. Falling back to sorted ids keeps this deterministic for a
    # document written by something other than the builder.
    root = layout.get("ROOT")
    ordered = (root or {}).get("nodes") if isinstance(root, dict) else None
    for node_id in (ordered if isinstance(ordered, list) else sorted(layout)):
        node = layout.get(node_id)
        if not isinstance(node, dict):
            continue
        node_type = node.get("type")
        name = node_type.get("resolvedName") if isinstance(node_type, dict) else node_type
        if name == widget:
            found.append(str(node_id))
    return found


def overlays(layout: Any) -> list[str]:
    """Node ids of every overlay, same reading as `pages`."""
    return pages(layout, widget=OVERLAY_WIDGET)


def headers(layout: Any) -> list[str]:
    """Node ids of every header, same reading as `pages`.

    Returns a list, though a module may have at most one, so the caller can
    say *how many* it found - "a module may have one header, this one has
    two" is a sentence somebody can act on; "invalid header" is not.
    """
    return pages(layout, widget=HEADER_WIDGET)


def parse(
    raw: Any,
    *,
    layout: Any = None,
    variables: dict[str, Any] | None = None,
) -> dict[str, Event]:
    """Validate the `events` map of a module document.

    `layout` and `variables` are optional so this can be exercised on its own,
    but the save path passes both - most of the refusals here are about a
    reference resolving, and a reference cannot be checked against nothing.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise EventError("`events` must be an object of id -> event")
    if len(raw) > MAX_EVENTS:
        raise EventError(f"a module may declare at most {MAX_EVENTS} events")

    nodes = set(layout) if isinstance(layout, dict) else None
    # A navigate may target either; what differs is what the browser does.
    page_ids = set(pages(layout)) | set(overlays(layout))
    declared = variables or {}

    events: dict[str, Event] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            raise EventError(f"event {key!r} must be an object")
        eid = str(value.get("id") or key)
        if eid != key:
            raise EventError(
                f"event {key!r} declares id {eid!r} - the key and the id must match"
            )
        trigger = value.get("trigger")
        if not isinstance(trigger, dict):
            raise EventError(f"event {key!r} needs a trigger saying which widget and what")
        node = str(trigger.get("node") or "")
        on = str(trigger.get("on") or "")
        if not node:
            raise EventError(f"event {key!r} has a trigger with no widget")
        if nodes is not None and node not in nodes:
            # An event on a deleted widget can never fire, so it is not an
            # event - it is a fragment of a previous design that will confuse
            # whoever reads the document next.
            raise EventError(
                f"event {key!r} fires from widget {node!r}, which this layout does not contain"
            )
        if on not in TRIGGERS:
            raise EventError(
                f"event {key!r} triggers on {on!r}; expected one of {', '.join(TRIGGERS)}"
            )

        raw_effects = value.get("effects") or []
        if not isinstance(raw_effects, list):
            raise EventError(f"event {key!r}: effects must be a list")
        if len(raw_effects) > MAX_EFFECTS:
            raise EventError(f"event {key!r} may have at most {MAX_EFFECTS} effects")
        effects = tuple(_parse_effect(eid, e, declared, nodes, page_ids) for e in raw_effects)
        events[eid] = Event(id=eid, node=node, on=on, effects=effects)
    return events


def _parse_effect(
    eid: str,
    raw: Any,
    declared: dict[str, Any],
    nodes: set[str] | None = None,
    page_ids: set[str] | None = None,
) -> Effect:
    if not isinstance(raw, dict):
        raise EventError(f"event {eid!r}: each effect must be an object")
    kind = raw.get("type")
    if kind in PLANNED_EFFECTS:
        raise EventError(
            f"the {kind} effect is not built yet - accepting it would save an event "
            "that silently does nothing when somebody clicks"
        )
    if kind not in EFFECTS:
        raise EventError(
            f"event {eid!r} has effect {kind!r}; expected one of {', '.join(EFFECTS)}"
        )
    config = raw.get("config") or {}
    if not isinstance(config, dict):
        raise EventError(f"event {eid!r}: effect config must be an object")

    if kind == "set_variable":
        target = config.get("variable")
        if not target or not isinstance(target, str):
            raise EventError(f"event {eid!r}: set_variable needs a variable to set")
        if declared and target not in declared:
            raise EventError(
                f"event {eid!r} sets {target!r}, which this module does not declare"
            )
        variable = declared.get(target)
        if variable is not None and getattr(variable, "derived", False):
            raise EventError(
                f"event {eid!r} sets {getattr(variable, 'label', target)!r}, which is "
                "computed from other variables - set one of those instead"
            )
        source = config.get("from")
        if source is not None:
            # `from: object` writes the object the trigger was about - the row
            # that was clicked - rather than a template. Two ways of saying
            # what to write, so exactly one may be given: a document carrying
            # both has no rule for which wins.
            if source not in SET_SOURCES:
                raise EventError(
                    f"event {eid!r}: set_variable from {source!r}; expected one of "
                    f"{', '.join(SET_SOURCES)}"
                )
            if config.get("value") is not None:
                raise EventError(
                    f"event {eid!r} sets {target!r} both from {source!r} and from a "
                    "value - give one or the other"
                )
    elif kind == "navigate":
        target = config.get("page")
        if not target or not isinstance(target, str):
            raise EventError(f"event {eid!r}: navigate needs a page to go to")
        if nodes is not None and target not in nodes:
            raise EventError(
                f"event {eid!r} navigates to {target!r}, which this layout does not contain"
            )
        if page_ids is not None and nodes is not None and target not in page_ids:
            # Navigating to a chart is not a smaller version of navigating to a
            # page - it is a click that would do nothing, and saying so here is
            # the only moment anybody can fix it.
            raise EventError(
                f"event {eid!r} navigates to {target!r}, which is a widget rather than a "
                "page or an overlay"
            )
    elif kind == "open_url":
        url = config.get("url")
        if not url or not isinstance(url, str):
            raise EventError(f"event {eid!r}: open_url needs a url")
        if not url.startswith(URL_SCHEMES):
            raise EventError(
                f"event {eid!r}: {url!r} is not a link a browser will open - "
                f"use one of {', '.join(URL_SCHEMES)}"
            )
    return Effect(type=str(kind), config=config)


def for_node(events: dict[str, Event], node: str, on: str) -> list[Event]:
    """Every event a widget should run for one act, in id order.

    Ordered rather than arbitrary for the same reason effects are: two events
    on one trigger both writing variables have to run in a stated order, or the
    app behaves differently between reloads.
    """
    return [e for _, e in sorted(events.items()) if e.node == node and e.on == on]
