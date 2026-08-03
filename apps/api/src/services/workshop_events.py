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
EFFECTS = ("set_variable", "open_url")

# Named, refused, and each blocked on something real rather than on effort:
# `navigate` needs pages and overlays, which do not exist until item 1.4;
# `run_action` needs the action's parameters bound to variables, which is its
# own design question; `export` needs a download surface the viewer route does
# not have. Refusing with the reason beats accepting and silently doing
# nothing, which is what an unknown effect type would otherwise do.
PLANNED_EFFECTS = ("navigate", "run_action", "export")

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
        effects = tuple(_parse_effect(eid, e, declared) for e in raw_effects)
        events[eid] = Event(id=eid, node=node, on=on, effects=effects)
    return events


def _parse_effect(eid: str, raw: Any, declared: dict[str, Any]) -> Effect:
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
