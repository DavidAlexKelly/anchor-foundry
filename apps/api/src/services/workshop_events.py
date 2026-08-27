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
#
# `submit` is p.465's "Event on enter: set event(s) to be triggered when the
# enter key is pressed". Named for the act rather than the key for the reason
# above - a viewer pressing enter in a field is *committing what they typed*,
# and a trigger called `enter` would have to be renamed the first time anything
# else commits an entry. It is distinct from `change`, which fires per
# keystroke: the whole point of p.465's setting is to run something **once**,
# when the entry is finished, rather than on every character of it.
TRIGGERS = ("click", "row_select", "change", "submit")

# Effects the browser runs. `run_action` is the only one that *writes* - the
# rest move the reader around - which is why it is the only one whose outcome
# the runtime reports.
EFFECTS = (
    "set_variable", "open_url", "navigate", "close_overlay", "run_action",
    # p.82's three, which Foundry groups with `navigate` under "Layout events":
    # they change "the on-screen display within a Workshop module".
    "expand_section", "collapse_section", "toggle_section",
    # p.84's "Switch to {tab name}", grouped with the same Layout events - and
    # the one of them that behaves differently, see `switch_tab` below.
    "switch_tab",
    # p.85's "Reset {variable name} value", which p.85 offers "for static
    # variables" - see the refusal in `_parse_effect`.
    "reset_variable",
    # p.85's "Recompute {variable name}", offered "for non-static variable
    # types" - the complement of reset_variable, and the thing p.76's two
    # non-automatic behaviours exist to be triggered by.
    "recompute",
)

# The three above, and the fact that binds them: each names a section.
SECTION_EFFECTS = ("expand_section", "collapse_section", "toggle_section")

# Named, refused, and blocked on something real rather than on effort: `export`
# needs a download surface the viewer route does not have. Refusing with the
# reason beats accepting and silently doing nothing, which is what an unknown
# effect type would otherwise do.
#
# `navigate` moved out of this list with item 1.4: pages exist now.
# `run_action` moved out with the second half of 1.3: its parameters are bound
# to variables, which was the design question holding it.
#
# `recompute` moved out of this list once p.76's two non-automatic recompute
# behaviours existed. It was here for precisely the right reason and for
# precisely as long as the reason held: with every derived variable recomputing
# on every resolve there was nothing for it to trigger, so accepting it would
# have saved a click that does nothing.
PLANNED_EFFECTS = ("export",)

# What a `run_action` may write. A wider form is a form, not an event.
MAX_ACTION_VALUES = 20

# The variable kind a `run_action`'s subject must be. An action executes
# against an object instance, so the subject has to be something that holds
# one - a text variable holding an id would look equivalent and would break
# the moment somebody typed a primary key into it instead.
SUBJECT_KIND = "single_object"

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

# A section, which is what p.82's three effects act on.
SECTION_WIDGET = "CanvasSection"

# The section layout that has tabs (p.54). `switch_tab` is offered "for each
# Tab section in the module", so a section arranged any other way has no tabs
# for an event to switch between.
TABS_DIRECTION = "tabs"

# How many tabs one section may have. Not a storage limit - it is the point
# past which a tab strip stops being one, and a module that wants forty
# configurations wants pages or a variable, not a row of forty buttons.
MAX_TABS = 20

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


def collapsible_sections(layout: Any) -> list[str]:
    """Node ids of every section a builder marked collapsible (p.55, p.82).

    **Marked, not merely a section.** p.82 offers its three events "for each
    collapsible section in the module", and that qualifier is the whole
    refusal below: an Expand aimed at a section that cannot collapse is a click
    that does nothing, which is precisely the failure this module exists to
    make unsaveable.
    """
    found: list[str] = []
    for node_id in pages(layout, widget=SECTION_WIDGET):
        node = layout.get(node_id) if isinstance(layout, dict) else None
        props = node.get("props") if isinstance(node, dict) else None
        if isinstance(props, dict) and props.get("collapsible"):
            found.append(node_id)
    return found


def tab_sections(layout: Any) -> dict[str, list[str]]:
    """Every Tabs section, mapped to its tab names (p.54, p.84).

    **The names, not just the ids**, because p.84's event addresses a tab by
    name - "a Switch to {tab name} event will be added for each tab in the
    section" - so validating one means knowing what this section's tabs are
    called. That is a function of two props (the author's `tabs` list) and one
    structural fact (how many children the section has), which is why it is
    computed here rather than read off a single field.

    **Mirrors `tabLabels` in `components/canvas/tab-selection.ts`**, and the
    mirroring is deliberate rather than accidental: the server is what refuses
    a save, so this copy decides only what is *legal*. If the two drift, the
    browser will draw a tab the server will not let an event name - which is
    exactly the failure `test_workshop_events.py` asserts against by walking
    the same cases the unit test does.
    """
    out: dict[str, list[str]] = {}
    if not isinstance(layout, dict):
        return out
    for node_id in pages(layout, widget=SECTION_WIDGET):
        node = layout.get(node_id)
        props = node.get("props") if isinstance(node, dict) else None
        if not isinstance(props, dict) or props.get("direction") != TABS_DIRECTION:
            continue
        children = node.get("nodes") if isinstance(node, dict) else None
        count = len(children) if isinstance(children, list) else 0
        out[node_id] = _tab_labels(props.get("tabs"), count)
    return out


def _tab_labels(spec: Any, count: int) -> list[str]:
    """One label per child, numbered where unnamed and de-duplicated."""
    given = [name.strip() for name in str(spec or "").split(",")]
    labels: list[str] = []
    seen: set[str] = set()
    for index in range(count):
        base = (given[index] if index < len(given) else "") or f"Tab {index + 1}"
        name, suffix = base, 2
        while name in seen:
            name = f"{base} {suffix}"
            suffix += 1
        seen.add(name)
        labels.append(name)
    return labels


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
    actions: dict[str, list[str]] | None = None,
) -> dict[str, Event]:
    """Validate the `events` map of a module document.

    `layout` and `variables` are optional so this can be exercised on its own,
    but the save path passes both - most of the refusals here are about a
    reference resolving, and a reference cannot be checked against nothing.

    `actions` maps action type id -> editable property names, and is the one
    argument that describes the *workspace* rather than the document. It is
    passed when a document is being written and left out when one is being
    read, deliberately: an action deleted after an app was saved would
    otherwise make that app fail to open, which is a record of what somebody
    built becoming invalid because live state moved. A `run_action` naming an
    action that has since gone reports when it is clicked instead.
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
    collapsible = set(collapsible_sections(layout))
    tabbed = tab_sections(layout)
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
        effects = tuple(
            _parse_effect(eid, e, declared, nodes, page_ids, actions, collapsible, tabbed)
            for e in raw_effects
        )
        events[eid] = Event(id=eid, node=node, on=on, effects=effects)
    return events


def _parse_effect(
    eid: str,
    raw: Any,
    declared: dict[str, Any],
    nodes: set[str] | None = None,
    page_ids: set[str] | None = None,
    actions: dict[str, list[str]] | None = None,
    collapsible: set[str] | None = None,
    tabbed: dict[str, list[str]] | None = None,
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
    elif kind == "run_action":
        action = config.get("action")
        if not action or not isinstance(action, str):
            raise EventError(f"event {eid!r}: run_action needs an action to run")
        subject = config.get("subject")
        if not subject or not isinstance(subject, str):
            raise EventError(
                f"event {eid!r}: run_action needs a variable holding the object to act on"
            )
        if declared and subject not in declared:
            raise EventError(
                f"event {eid!r} acts on {subject!r}, which this module does not declare"
            )
        variable = declared.get(subject)
        if variable is not None and getattr(variable, "kind", None) != SUBJECT_KIND:
            raise EventError(
                f"event {eid!r} acts on {getattr(variable, 'label', subject)!r}, which holds "
                f"a {getattr(variable, 'kind', 'value')} rather than an object - an action "
                "runs against one object instance"
            )
        values = config.get("values") or {}
        if not isinstance(values, dict):
            raise EventError(f"event {eid!r}: run_action values must be an object")
        if len(values) > MAX_ACTION_VALUES:
            raise EventError(
                f"event {eid!r}: run_action may write at most {MAX_ACTION_VALUES} properties"
            )
        if not values:
            # `validate_submitted_values` refuses an empty write, so this would
            # save an event that fails every time it is clicked.
            raise EventError(
                f"event {eid!r}: run_action needs at least one property to write - "
                "an action with nothing to write has nothing to do"
            )
        for prop, template in values.items():
            if not isinstance(prop, str) or not prop:
                raise EventError(f"event {eid!r}: run_action has a value with no property name")
            if not isinstance(template, str):
                raise EventError(
                    f"event {eid!r}: run_action writes {prop!r} as {type(template).__name__} - "
                    "values are text, with {{...}} reading from the trigger"
                )
        if actions is not None:
            if action not in actions:
                raise EventError(
                    f"event {eid!r} runs an action this workspace does not have"
                )
            editable = set(actions[action])
            unknown = sorted(p for p in values if p not in editable)
            if unknown:
                # The write would be refused at click time with the same
                # sentence. Saying it now is the difference between the person
                # who made the mistake finding out and somebody else.
                raise EventError(
                    f"event {eid!r} writes {', '.join(repr(u) for u in unknown)}, which "
                    "this action does not make editable"
                )
    elif kind in SECTION_EFFECTS:
        target = config.get("section")
        if not target or not isinstance(target, str):
            raise EventError(f"event {eid!r}: {kind} needs a section to act on")
        if nodes is not None and target not in nodes:
            raise EventError(
                f"event {eid!r} {kind.split('_')[0]}s {target!r}, which this layout "
                "does not contain"
            )
        if collapsible is not None and nodes is not None and target not in collapsible:
            # p.82 offers these "for each collapsible section", and a section
            # that cannot collapse has no state for them to change. Saving one
            # would be saving a button that does nothing - and doing nothing is
            # the one outcome nobody can debug from the outside.
            raise EventError(
                f"event {eid!r} {kind.split('_')[0]}s {target!r}, which is not a "
                "collapsible section - turn on Collapsible in its settings first"
            )
    elif kind == "reset_variable":
        target = config.get("variable")
        if not target or not isinstance(target, str):
            raise EventError(f"event {eid!r}: reset_variable needs a variable to reset")
        if declared and target not in declared:
            raise EventError(
                f"event {eid!r} resets {target!r}, which this module does not declare"
            )
        variable = declared.get(target) if declared else None
        if variable is not None:
            # **p.85 offers this "for static variables", and the qualifier is
            # the refusal.** A derived variable is a function of its inputs, so
            # there is no stored value to put back - "its default value, which
            # is the value configured in the variable definition" names
            # something a derived variable does not have. An object-set
            # variable with its own definition is the same case by a different
            # route: it resolves to that definition whatever the viewer does,
            # so a reset would be a click with no effect.
            why = None
            if getattr(variable, "derivation", None) is not None:
                why = "a derived variable, whose value is computed from its inputs"
            elif getattr(variable, "object_set", None) is not None:
                why = "an object set with its own definition, which a viewer never overrides"
            if why:
                raise EventError(
                    f"event {eid!r} resets {target!r}, which is {why} - so it has no "
                    "stored value to put back. p.85 offers Reset for static variables"
                )
    elif kind == "recompute":
        target = config.get("variable")
        if not target or not isinstance(target, str):
            raise EventError(f"event {eid!r}: recompute needs a variable to recompute")
        if declared and target not in declared:
            raise EventError(
                f"event {eid!r} recomputes {target!r}, which this module does not declare"
            )
        variable = declared.get(target) if declared else None
        if variable is not None:
            # **p.85 offers this "for non-static variable types", and p.76 adds
            # the sharper rule**: the behaviours it triggers are configurable on
            # derived definitions only. So a static variable is refused for the
            # same reason Reset refuses a derived one - the two events are
            # complements, and each is meaningless on the other's half.
            if getattr(variable, "derivation", None) is None:
                raise EventError(
                    f"event {eid!r} recomputes {target!r}, which is static - there is "
                    "nothing to recompute. p.85 offers Recompute for non-static "
                    "variables, and Reset for static ones"
                )
            # And the sharper one still: a derived variable left on Automatic
            # already recomputes whenever its inputs change (p.76), so an event
            # aimed at one is a click with no effect - which is the whole class
            # of thing this module refuses.
            if getattr(variable, "recompute", "automatic") == "automatic":
                raise EventError(
                    f"event {eid!r} recomputes {target!r}, which is on Automatic "
                    "recompute - it already recomputes when its inputs change. Set its "
                    "recompute behaviour to one of the event-driven options first"
                )
    elif kind == "switch_tab":
        # **p.84's event, and the one Layout event that writes its variable.**
        # That difference lives in the browser (`tab-selection.ts` and
        # `CanvasSection`); what is checkable here is that the event names a
        # tab that exists, which is the same class of refusal as the three
        # above and fails the same way if it is not made: a click that does
        # nothing.
        target = config.get("section")
        if not target or not isinstance(target, str):
            raise EventError(f"event {eid!r}: switch_tab needs a section to act on")
        if nodes is not None and target not in nodes:
            raise EventError(
                f"event {eid!r} switches a tab in {target!r}, which this layout "
                "does not contain"
            )
        name = config.get("tab")
        if not name or not isinstance(name, str):
            raise EventError(f"event {eid!r}: switch_tab needs a tab to switch to")
        if tabbed is not None and nodes is not None:
            if target not in tabbed:
                raise EventError(
                    f"event {eid!r} switches a tab in {target!r}, which is not a Tabs "
                    "section - set its layout to Tabs first"
                )
            if name not in tabbed[target]:
                # Named against the tabs that *are* there, because the usual
                # cause is a rename: the event was right when it was written
                # and the section moved underneath it.
                offered = ", ".join(repr(t) for t in tabbed[target]) or "none"
                raise EventError(
                    f"event {eid!r} switches to tab {name!r}, which {target!r} does "
                    f"not have. Its tabs are: {offered}"
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
