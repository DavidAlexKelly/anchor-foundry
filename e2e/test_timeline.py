"""p.347-349's Timeline (parity `workshop.md` §7).

> "The Timeline widget is used to visualize temporal data, rendering objects as
> events in a chronologically ordered timeline." (p.347)

> "**Multiple timeline layers** can be used to aggregate temporal data across
> multiple object types as events on a single timeline widget… **Object set**…
> **Date / timestamp property**: select the date or timestamp property to be
> used for visualizing **and ordering** the objects by." (p.348)

> "**Timeline orientation**… **Timeline events order**… **Show legend**: toggle
> on an interactive legend card that can be toggled to show or hide selected
> timeline layers. **Show time between events in tooltip on hover**…
> **Active object**: outputs an object set of the currently selected object in
> the widget." (p.349)

The rules are `apps/web/src/components/canvas/timeline.test.ts`, mutation-tested
without a browser: which order a layer asks the server for, what a layer is,
how two layers interleave, and how a gap reads in words.

**What needs a browser is that the events are the right ones, in the right
order, from the right sets.** p.348's date property is "visualizing *and
ordering*", and the ordering happens on the server — this widget is the first
thing in the platform to depend on §221's property sort, so the assertion that
matters is that a timeline of objects whose *date* order differs from their
*sync* order comes back in date order.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import open_builder, open_module, settled

# **Written in an order that is not their date order**, which is the whole
# point: a sync stamps `updated_at` in write order, so a timeline that fell back
# to the platform's old `recent` sort would come back in *this* order rather
# than in `seen` order. Every date-order assertion below would pass on the old
# platform if these were written chronologically.
SITES = [
    {"id": "S2", "name": "Bravo", "seen": "2026-03-01", "region": "south"},
    {"id": "S4", "name": "Delta", "seen": "2026-11-30", "region": "east"},
    {"id": "S1", "name": "Alpha", "seen": "2026-01-05", "region": "north"},
    {"id": "S3", "name": "Charlie", "seen": "2026-06-15", "region": "north"},
]

# A second type, for p.348's "aggregate temporal data across multiple object
# types". Its dates interleave with the sites' rather than sitting after them —
# two layers that did not interleave would be indistinguishable from a
# concatenation, which is the merge bug that does nothing.
ORDERS = [
    {"ref": "O1", "placed": "2026-02-01", "total": "40"},
    {"ref": "O2", "placed": "2026-09-09", "total": "12"},
]


@pytest.fixture(scope="module")
def ontology(api):
    mod = Module(api, "Timeline")
    mod.site_type_id = mod.object_type(
        columns=["id", "name", "seen", "region"], rows=SITES, key="id", title="name",
        # `seen` declared a real date, which is what §220 and §221 made
        # meaningful: it is a `date` field in the index and a guarded cast in
        # Postgres, so ordering by it is a server-side sort rather than a hope.
        types={"seen": "date"},
        # p.348's "ontology-defined prominent properties" — `region` is
        # prominent and `name` is not, so a default layer shows one and not the
        # other. A type with everything prominent could not tell the two apart.
        visibility={"region": "prominent"},
    )
    # **A second module in the same project**, because `object_type` names its
    # dataset after the module's tag - so two types on one module collide on the
    # dataset slug. The project is shared via `beside`, which is what makes both
    # types visible to one app's variables.
    orders = Module(api, "Timeline orders", beside=mod)
    mod.order_type_id = orders.object_type(
        columns=["ref", "placed", "total"], rows=ORDERS, key="ref", title="ref",
        types={"placed": "date"},
    )
    return mod


def build(api, ontology, name: str, props: dict | None = None, *, layers=None,
          with_output: bool = False):
    """One timeline over one or two layers, and optionally a table reading the
    set its selection narrows."""
    variables = {
        "v_sites": {"id": "v_sites", "kind": "object_set", "label": "Every site",
                    "object_set": object_set(ontology.site_type_id)},
        "v_orders": {"id": "v_orders", "kind": "object_set", "label": "Every order",
                     "object_set": object_set(ontology.order_type_id)},
    }
    nodes = {
        "tl": {
            "resolvedName": "CanvasTimeline",
            "props": {
                "layers": layers if layers is not None else [
                    {"label": "Sites", "objectSetVariable": "v_sites",
                     "dateProperty": "seen"},
                ],
                "orientation": "vertical", "order": "newest_first",
                "showLegend": True, "showGaps": False,
                "activeVariable": "v_picked_clauses" if with_output else None,
                "highlightSelection": True, "pageSize": 50,
                **(props or {}),
            },
        },
    }
    if with_output:
        variables["v_picked_clauses"] = {
            "id": "v_picked_clauses", "kind": "array", "label": "The picked event",
        }
        variables["v_picked"] = {
            "id": "v_picked", "kind": "object_set", "label": "The picked set",
            "derivation": {"transform": "narrow_set",
                           "inputs": ["v_sites", "v_picked_clauses"]},
        }
        nodes["tbl"] = {
            "resolvedName": "CanvasObjectTable",
            "props": {"objectSetVariable": "v_picked", "columns": "id,name",
                      "pageSize": 25, "activeVariable": None, "autoSelect": False},
        }
    mod = Module(api, name, beside=ontology)
    mod.define({"format": 2, "layout": layout(nodes), "variables": variables,
                "events": {}})
    return mod


def events(page):
    return page.get_by_test_id("timeline-event")


def titles(page) -> list[str]:
    return [t.strip() for t in page.locator(".canvas-timeline-title").all_text_contents()]


# ---- p.348's ordering, which is what this widget waited for -------------------
def test_events_come_back_in_date_order_not_sync_order(page, api, ontology) -> None:
    """**The assertion the whole of §220 and §221 was for.**

    The fixture is written in an order that is not its date order, so a timeline
    ordered by `updated_at` — which is all the platform could do before decision
    0006 was built — comes back as Bravo, Delta, Alpha, Charlie. In date order,
    newest first, it is Delta, Charlie, Bravo, Alpha.
    """
    mod = build(api, ontology, "Timeline order")
    open_module(page, mod)
    settled(page)

    expect(events(page)).to_have_count(4)
    assert titles(page) == ["Delta", "Charlie", "Bravo", "Alpha"]


def test_oldest_first_reverses_it(page, api, ontology) -> None:
    """p.349's other order. Asserted as the *reverse* rather than as a second
    literal list, because a widget that ignored the setting would pass one
    hard-coded expectation and fail the pair."""
    mod = build(api, ontology, "Timeline oldest", {"order": "oldest_first"})
    open_module(page, mod)
    settled(page)

    assert titles(page) == ["Alpha", "Bravo", "Charlie", "Delta"]


def test_the_date_of_each_event_is_shown(page, api, ontology) -> None:
    mod = build(api, ontology, "Timeline dates", {"order": "oldest_first"})
    open_module(page, mod)
    settled(page)

    stamps = [t.strip() for t in page.get_by_test_id("timeline-when").all_text_contents()]
    assert stamps == ["2026-01-05", "2026-03-01", "2026-06-15", "2026-11-30"]


# ---- p.348's layers ----------------------------------------------------------
def test_two_layers_interleave_rather_than_concatenate(page, api, ontology) -> None:
    """p.348's "aggregate temporal data across multiple object types as events
    on a single timeline widget".

    **The merge bug is doing nothing**: each layer is a separate query, already
    ordered, so a concatenation is every site then every order. The orders'
    dates fall *between* the sites' precisely so the two are distinguishable.
    """
    mod = build(api, ontology, "Timeline two layers", {"order": "oldest_first"}, layers=[
        {"label": "Sites", "objectSetVariable": "v_sites", "dateProperty": "seen"},
        {"label": "Orders", "objectSetVariable": "v_orders", "dateProperty": "placed"},
    ])
    open_module(page, mod)
    settled(page)

    expect(events(page)).to_have_count(6)
    assert titles(page) == ["Alpha", "O1", "Bravo", "Charlie", "O2", "Delta"]


def test_each_layer_reads_its_own_date_property(page, api, ontology) -> None:
    """The two types name their dates differently — `seen` and `placed`. A merge
    reading one property for every layer would drop the other layer entirely,
    and a fixture whose types shared a property name could not tell."""
    mod = build(api, ontology, "Timeline own dates", layers=[
        {"label": "Sites", "objectSetVariable": "v_sites", "dateProperty": "seen"},
        {"label": "Orders", "objectSetVariable": "v_orders", "dateProperty": "placed"},
    ])
    open_module(page, mod)
    settled(page)

    layers = {e.get_attribute("data-layer") for e in events(page).all()}
    assert layers == {"0", "1"}


def test_a_layer_with_no_date_property_draws_nothing(page, api, ontology) -> None:
    """A layer is its set *and* its date property: without one the events have
    nowhere to go. Drawn anyway it would take a legend entry and a colour while
    contributing nothing, which reads as "no data in this period"."""
    mod = build(api, ontology, "Timeline half layer", layers=[
        {"label": "Sites", "objectSetVariable": "v_sites", "dateProperty": "seen"},
        {"label": "Unfinished", "objectSetVariable": "v_orders", "dateProperty": ""},
    ])
    open_module(page, mod)
    settled(page)

    expect(events(page)).to_have_count(4)
    expect(page.get_by_test_id("timeline-legend").locator("button")).to_have_count(1)


def test_a_timeline_with_no_layers_says_so(page, api, ontology) -> None:
    mod = build(api, ontology, "Timeline empty", layers=[])
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("timeline")).to_have_count(0)
    expect(page.get_by_text("Timeline - add a layer in Settings")).to_be_visible()


# ---- p.349's legend ----------------------------------------------------------
def test_the_legend_hides_and_restores_a_layer(page, api, ontology) -> None:
    """p.349: "an interactive legend card that can be toggled to show or hide
    selected timeline layers". Both directions, because a control that only
    hides is one a viewer cannot undo."""
    mod = build(api, ontology, "Timeline legend", layers=[
        {"label": "Sites", "objectSetVariable": "v_sites", "dateProperty": "seen"},
        {"label": "Orders", "objectSetVariable": "v_orders", "dateProperty": "placed"},
    ])
    open_module(page, mod)
    settled(page)
    expect(events(page)).to_have_count(6)

    page.get_by_test_id("timeline-legend-1").click()
    expect(events(page)).to_have_count(4)
    assert "O1" not in titles(page)

    page.get_by_test_id("timeline-legend-1").click()
    expect(events(page)).to_have_count(6)


def test_the_legend_can_be_turned_off(page, api, ontology) -> None:
    shown = build(api, ontology, "Timeline legend on")
    open_module(page, shown)
    settled(page)
    expect(page.get_by_test_id("timeline-legend")).to_be_visible()

    hidden = build(api, ontology, "Timeline legend off", {"showLegend": False})
    open_module(page, hidden)
    settled(page)
    # The events are still there — what is missing is the key.
    expect(events(page)).to_have_count(4)
    expect(page.get_by_test_id("timeline-legend")).to_have_count(0)


def test_a_layer_keeps_its_own_colour(page, api, ontology) -> None:
    """The one thing p.348 says layers are for is telling several types apart on
    one timeline, so two layers drawn identically is the widget failing at its
    purpose."""
    mod = build(api, ontology, "Timeline colours", layers=[
        {"label": "Sites", "objectSetVariable": "v_sites", "dateProperty": "seen"},
        {"label": "Orders", "objectSetVariable": "v_orders", "dateProperty": "placed"},
    ])
    open_module(page, mod)
    settled(page)

    first = page.locator("[data-testid='timeline-event'][data-layer='0'] .canvas-timeline-mark")
    second = page.locator("[data-testid='timeline-event'][data-layer='1'] .canvas-timeline-mark")
    a = first.first.evaluate("el => getComputedStyle(el).backgroundColor")
    b = second.first.evaluate("el => getComputedStyle(el).backgroundColor")
    assert a != b, (a, b)


def test_a_static_colour_overrides_the_default(page, api, ontology) -> None:
    mod = build(api, ontology, "Timeline static colour", layers=[
        {"label": "Sites", "objectSetVariable": "v_sites", "dateProperty": "seen",
         "colourMode": "static", "colour": "rgb(1, 2, 3)"},
    ])
    open_module(page, mod)
    settled(page)

    expect(page.locator(".canvas-timeline-mark").first).to_have_css(
        "background-color", "rgb(1, 2, 3)"
    )


# ---- p.348's event title and properties --------------------------------------
def test_a_property_title_replaces_the_object_title(page, api, ontology) -> None:
    """p.348's three title modes. Asserted against the *object* title so the two
    are distinguishable — a fixture whose title property equalled its object
    title would pass whichever the widget picked."""
    mod = build(api, ontology, "Timeline property title", layers=[
        {"label": "Sites", "objectSetVariable": "v_sites", "dateProperty": "seen",
         "titleMode": "property", "titleValue": "region"},
    ])
    open_module(page, mod)
    settled(page)

    assert set(titles(page)) == {"north", "south", "east"}


def test_a_custom_title_is_the_same_on_every_event(page, api, ontology) -> None:
    mod = build(api, ontology, "Timeline custom title", layers=[
        {"label": "Sites", "objectSetVariable": "v_sites", "dateProperty": "seen",
         "titleMode": "custom", "titleValue": "Visit"},
    ])
    open_module(page, mod)
    settled(page)

    assert titles(page) == ["Visit"] * 4


def test_prominent_properties_are_the_ontology_s_choice(page, api, ontology) -> None:
    """p.348: "**only** display the ontology-defined prominent properties".
    `region` is prominent on this type and `name` is not, so a widget showing
    everything would be visible here rather than merely plausible."""
    mod = build(api, ontology, "Timeline prominent")
    open_module(page, mod)
    settled(page)

    keys = [t.strip() for t in page.locator(".canvas-timeline-props dt").all_text_contents()]
    assert set(keys) == {"region"}, keys


def test_specific_properties_are_the_author_s_choice(page, api, ontology) -> None:
    mod = build(api, ontology, "Timeline specific", layers=[
        {"label": "Sites", "objectSetVariable": "v_sites", "dateProperty": "seen",
         "propertyMode": "specific", "properties": "name,region"},
    ])
    open_module(page, mod)
    settled(page)

    first = page.get_by_test_id("timeline-props").first
    keys = [t.strip() for t in first.locator("dt").all_text_contents()]
    assert keys == ["name", "region"], "the author's order, not the ontology's"


# ---- p.349's appearance ------------------------------------------------------
def test_the_orientation_changes_how_the_track_flows(page, api, ontology) -> None:
    """p.349's Vertical and Horizontal. Measured on the rendered box rather than
    on the attribute: a setting no rule acts on passes every other check."""
    vertical = build(api, ontology, "Timeline vertical")
    open_module(page, vertical)
    settled(page)
    first = page.get_by_test_id("timeline-event").first.bounding_box()
    second = page.get_by_test_id("timeline-event").nth(1).bounding_box()
    assert second["y"] > first["y"], "vertical stacks downwards"
    assert abs(second["x"] - first["x"]) < 2

    horizontal = build(api, ontology, "Timeline horizontal", {"orientation": "horizontal"})
    open_module(page, horizontal)
    settled(page)
    first = page.get_by_test_id("timeline-event").first.bounding_box()
    second = page.get_by_test_id("timeline-event").nth(1).bounding_box()
    assert second["x"] > first["x"], "horizontal runs across"


def test_the_time_between_events_can_be_shown(page, api, ontology) -> None:
    """p.349's "calculated time between two events". Off by default, and the
    values are the real gaps rather than a placeholder."""
    off = build(api, ontology, "Timeline no gaps")
    open_module(page, off)
    settled(page)
    expect(page.get_by_test_id("timeline-gap")).to_have_count(0)

    on = build(api, ontology, "Timeline gaps", {"showGaps": True, "order": "oldest_first"})
    open_module(page, on)
    settled(page)
    gaps = [t.strip() for t in page.get_by_test_id("timeline-gap").all_text_contents()]
    # Three gaps for four events, and the first is 5 Jan to 1 Mar.
    assert len(gaps) == 3, gaps
    assert gaps[0] == "55 days", gaps


# ---- p.349's selection -------------------------------------------------------
def test_selecting_an_event_narrows_the_set_it_outputs(page, api, ontology) -> None:
    """p.349's "Active object: outputs an object set of the currently selected
    object in the widget".

    Asserted through a table reading the narrowed set, because that is what the
    output is *for* — a variable nothing consumes could hold anything.
    """
    mod = build(api, ontology, "Timeline output", with_output=True)
    open_module(page, mod)
    settled(page)

    page.get_by_test_id("timeline-title-S3").click()
    rows = page.locator(".canvas-block:has(> .data-grid)").locator("tbody tr")
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("Charlie")


def test_the_selected_event_is_highlighted_and_can_be_turned_off(page, api, ontology) -> None:
    """p.349's Enable highlight of event on selection."""
    on = build(api, ontology, "Timeline highlight", with_output=True)
    open_module(page, on)
    settled(page)
    page.get_by_test_id("timeline-title-S3").click()
    expect(page.locator("[data-testid='timeline-event'][data-selected='yes']")).to_have_count(1)

    off = build(api, ontology, "Timeline no highlight",
                {"highlightSelection": False}, with_output=True)
    open_module(page, off)
    settled(page)
    page.get_by_test_id("timeline-title-S3").click()
    # The selection still happened — what is off is the highlight, so the table
    # beside it still narrows.
    expect(page.locator(".canvas-block:has(> .data-grid)").locator("tbody tr")).to_have_count(1)
    expect(page.locator("[data-testid='timeline-event'][data-selected='yes']")).to_have_count(0)


# ---- the builder -------------------------------------------------------------
def test_a_layer_s_object_set_counts_as_a_usage(page, api, ontology) -> None:
    """§219's `NESTED_REFERENCE_PROPS`, for the second widget. A layer's set
    lives inside the `layers` array, where the flat scan cannot see it — and a
    binding nothing counts as a usage is a variable the panel offers to delete,
    after which the layer draws an empty band with a legend entry and a colour."""
    mod = build(api, ontology, "Timeline usage")
    open_builder(page, mod)
    settled(page)

    page.get_by_role("button", name="Variables", exact=False).first.click()
    row = page.locator(".vars-row", has_text="Every site").first
    expect(row.locator(".vars-usage")).not_to_have_text("unused")
    # And the set no layer names still reads as unused, so the check above is
    # about the binding rather than about the widget existing.
    spare = page.locator(".vars-row", has_text="Every order").first
    expect(spare.locator(".vars-usage")).to_have_text("unused")


def test_the_layer_editor_adds_and_removes_layers(page, api, ontology) -> None:
    """**Edited against the raw list, drawn against the parsed one.** A new
    layer has no set and no date property, so `layersOf` drops it — and an
    editor reading the parsed list would make a layer vanish the moment it was
    added, which is a control nobody can use."""
    mod = build(api, ontology, "Timeline editor")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Timeline").first.click()
    expect(page.get_by_test_id("timeline-layers")).to_be_visible()
    page.get_by_test_id("timeline-add").click()
    expect(page.get_by_test_id("timeline-set-1")).to_be_visible()

    page.get_by_test_id("timeline-remove-1").click()
    expect(page.get_by_test_id("timeline-set-1")).to_have_count(0)
    expect(page.get_by_test_id("timeline-set-0")).to_be_visible()


def test_the_layer_editor_offers_only_object_set_variables(page, api, ontology) -> None:
    mod = build(api, ontology, "Timeline set picker", with_output=True)
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Timeline").first.click()
    options = page.get_by_test_id("timeline-set-0").locator("option").all_text_contents()
    assert "Every site" in options
    assert "The picked event" not in options, "an array variable is not an object set"
