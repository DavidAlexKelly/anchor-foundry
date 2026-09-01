"""p.309-310's Pie Chart (parity `workshop.md` §10).

> "The Pie Chart widget is used to visualize objects data in a pie or donut
> chart via grouping of objects by a specified property type into proportional
> slices." (p.309)

> "**Group by**… **Enable ontology colors**… **Radius**: The inner radius of the
> space within the chart can be adjusted to switch chart's visualization from a
> pie to a donut chart. **Legend**… **Segment display**… **Selection as
> filter**." (p.310)

The slice arithmetic and the SVG geometry are
`apps/web/src/components/canvas/pie-chart.test.ts`, mutation-tested without a
browser — which is new: it used to be inline in `charts.tsx`, where nothing but
a browser could reach it, and no browser test drew a pie at all.

**What needs one is that the slices are of the right data.** A pie is a picture
of proportions, so every assertion here is about *which* slices exist and what
they are of — the counts come from a server-side grouping, and a widget that
drew a beautiful chart of the wrong set would look entirely convincing.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import open_builder, open_module, settled

# Three open, one closed — so the two slices are *different sizes* and a chart
# that divided the circle evenly would be visibly wrong rather than plausibly
# right.
ROWS = [
    {"id": "S1", "status": "open", "region": "north", "capacity": 10},
    {"id": "S2", "status": "open", "region": "south", "capacity": 10},
    {"id": "S3", "status": "open", "region": "north", "capacity": 10},
    {"id": "S4", "status": "closed", "region": "east", "capacity": 90},
]
# **`capacity` inverts the chart on purpose.** By count, `open` is three of four
# and covers three quarters; by *total capacity* it is 30 of 120 and covers one.
# So a pie sized by the count when the author asked for a sum is not merely
# wrong, it is backwards — which is what makes p.310's Aggregation testable
# rather than plausible.
CAPACITIES = {"open": 30, "closed": 90}


@pytest.fixture(scope="module")
def sites(api):
    mod = Module(api, "Pie chart")
    mod.site_type_id = mod.object_type(
        columns=["id", "status", "region", "capacity"], rows=ROWS, key="id",
        title="id",
        # `capacity` declared `integer`, which is what p.310's Aggregation needs
        # behind it: `object_sets.AGGREGATABLE_TYPES` refuses anything else, so
        # a string column here would test the refusal rather than the feature.
        types={"capacity": "integer"},
        # p.102-109's ordered rules, in the shape `test_conditional_formatting`
        # uses. Only `open` is painted, so p.310's setting has to change one
        # slice and leave the other alone.
        rules={"status": [
            {"comparison": "string", "operator": "is_exactly", "value": "open",
             "background": "#123456"},
        ]},
    )
    return mod


def build(api, sites, name: str, props: dict | None = None, *, with_filter: bool = False):
    """The pie, and — when asked — a table reading the set its clicks narrow."""
    nodes = {
        "pie": {
            "resolvedName": "CanvasPieChart",
            "props": {"objectSetVariable": "v_set", "groupBy": "status", "inner": 0,
                      "legend": "right", "showLegend": True, "segments": [],
                      "ontologyColors": False,
                      **({"filterVariable": "v_clauses"} if with_filter else {}),
                      **(props or {})},
        },
    }
    variables = {
        "v_set": {"id": "v_set", "kind": "object_set", "label": "Every site",
                  "object_set": object_set(sites.site_type_id)},
    }
    if with_filter:
        nodes["tbl"] = {
            "resolvedName": "CanvasObjectTable",
            "props": {"objectSetVariable": "v_picked", "columns": "id",
                      "pageSize": 25, "activeVariable": None, "autoSelect": False},
        }
        variables["v_clauses"] = {"id": "v_clauses", "kind": "array",
                                  "label": "The slice"}
        variables["v_picked"] = {
            "id": "v_picked", "kind": "object_set", "label": "The picked set",
            "derivation": {"transform": "narrow_set", "inputs": ["v_set", "v_clauses"]},
        }
    mod = Module(api, name, beside=sites)
    mod.define({"format": 2, "layout": layout(nodes), "variables": variables, "events": {}})
    return mod


def slices(page):
    return page.get_by_test_id("pie-slice")


def slice_for(page, label: str):
    return page.locator(f"[data-testid='pie-slice'][data-label='{label}']")


def test_it_draws_one_slice_per_distinct_value(page, api, sites) -> None:
    mod = build(api, sites, "Pie basic")
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("pie-chart")).to_be_visible()
    expect(slices(page)).to_have_count(2)
    expect(slice_for(page, "open")).to_have_count(1)
    expect(slice_for(page, "closed")).to_have_count(1)


def test_the_slices_are_proportional(page, api, sites) -> None:
    """**The widget's whole claim.** Three of four objects are open, so that
    slice covers three quarters — asserted through the title text, which is the
    only place the share is stated in words, and by the arc's own sweep flag,
    which is what actually draws it."""
    mod = build(api, sites, "Pie proportions")
    open_module(page, mod)
    settled(page)

    expect(slice_for(page, "open").locator("title")).to_have_text("open: 3 (75.0%)")
    expect(slice_for(page, "closed").locator("title")).to_have_text("closed: 1 (25.0%)")
    # Three quarters is more than a half turn, so the large-arc flag is set —
    # and a quarter is not. A chart drawing both the same is drawing one of
    # them wrong by half a circle.
    assert " 1 1 " in (slice_for(page, "open").get_attribute("d") or "")
    assert " 0 1 " in (slice_for(page, "closed").get_attribute("d") or "")


# ---- p.310's Aggregation (§228) ----------------------------------------------
def test_a_sum_sizes_the_slices_rather_than_the_count(page, api, sites) -> None:
    """**The assertion this unit exists for, and the fixture is built to invert
    it.**

    By count, `open` is three of four objects and covers three quarters. By
    total capacity it is 30 of 120 and covers one quarter. So a pie still sized
    by the count when the author asked for a sum is not subtly wrong — it is
    backwards, and the large-arc flag moves from one slice to the other.
    """
    mod = build(api, sites, "Pie sum",
                {"aggregation": "sum", "aggregationProperty": "capacity"})
    open_module(page, mod)
    settled(page)

    expect(slice_for(page, "closed").locator("title")).to_have_text("closed: 90 (75.0%)")
    expect(slice_for(page, "open").locator("title")).to_have_text("open: 30 (25.0%)")
    # And the arcs agree with the words: the larger share is the one that takes
    # more than half the circle.
    assert " 1 1 " in (slice_for(page, "closed").get_attribute("d") or "")
    assert " 0 1 " in (slice_for(page, "open").get_attribute("d") or "")


def test_an_average_is_not_a_sum(page, api, sites) -> None:
    """Three open sites of 10 average 10; one closed site of 90 averages 90. A
    widget that sent the aggregation but ignored which one would draw the sum's
    chart here, and the shares differ."""
    mod = build(api, sites, "Pie average",
                {"aggregation": "avg", "aggregationProperty": "capacity"})
    open_module(page, mod)
    settled(page)

    expect(slice_for(page, "closed").locator("title")).to_have_text("closed: 90 (90.0%)")
    expect(slice_for(page, "open").locator("title")).to_have_text("open: 10 (10.0%)")


def test_the_legend_shows_what_the_wedge_is_drawn_from(page, api, sites) -> None:
    """A legend reading "open — 3" beside a wedge covering a quarter of the
    circle states a count next to a percentage of a total: two true numbers
    arranged to look like one, which is worse than either alone."""
    mod = build(api, sites, "Pie sum legend",
                {"aggregation": "sum", "aggregationProperty": "capacity"})
    open_module(page, mod)
    settled(page)

    legend = page.get_by_test_id("pie-chart")
    expect(legend).to_contain_text("open — 30")
    expect(legend).to_contain_text("closed — 90")


def test_an_unfinished_aggregation_draws_nothing_rather_than_an_error(
    page, api, sites
) -> None:
    """A `sum` with no property yet is a panel somebody is halfway through. The
    server refuses it with a sentence about property types, and showing that to
    a viewer in place of a chart would report an author's unfinished setting as
    a failure."""
    mod = build(api, sites, "Pie sum unset", {"aggregation": "sum"})
    open_module(page, mod)
    settled(page)

    expect(slices(page)).to_have_count(0)
    expect(page.get_by_text("is a string property")).to_have_count(0)


def test_a_count_still_counts(page, api, sites) -> None:
    """p.310's default, unchanged - every pie saved before §228 holds no
    aggregation at all and must keep drawing the chart it drew."""
    mod = build(api, sites, "Pie count default")
    open_module(page, mod)
    settled(page)

    expect(slice_for(page, "open").locator("title")).to_have_text("open: 3 (75.0%)")


def test_a_donut_has_a_hole(page, api, sites) -> None:
    """p.310's Radius. Measured on the path itself: a wedge starts at the
    centre and an annulus segment never goes there, which is the difference
    between the two shapes rather than a class name."""
    pie = build(api, sites, "Pie solid")
    open_module(page, pie)
    settled(page)
    solid = slice_for(page, "open").get_attribute("d") or ""

    donut = build(api, sites, "Pie donut", {"inner": 0.5})
    open_module(page, donut)
    settled(page)
    ring = slice_for(page, "open").get_attribute("d") or ""

    # A wedge has a straight line from the centre out; a ring has a second arc
    # instead, drawn back the other way.
    assert " L " in solid, solid
    assert ring.count(" A ") == 2, ring
    assert solid != ring

    # **A radius that is not a number at all**, which the raw JSON editor can
    # hold. Read through the model it is zero; passed on raw it makes every
    # coordinate `NaN` and the browser draws nothing — and the harness found
    # that nothing here had asked, because every other radius in this file is
    # already legal.
    broken = build(api, sites, "Pie bad radius", {"inner": "abc"})
    open_module(page, broken)
    settled(page)
    d = slice_for(page, "open").get_attribute("d") or ""
    assert "NaN" not in d, d
    assert d == solid, d


def test_the_legend_names_every_slice_and_can_be_turned_off(page, api, sites) -> None:
    shown = build(api, sites, "Pie legend")
    open_module(page, shown)
    settled(page)
    expect(page.get_by_test_id("pie-legend-entry")).to_have_count(2)
    expect(page.get_by_test_id("pie-chart")).to_contain_text("open")

    hidden = build(api, sites, "Pie no legend", {"showLegend": False})
    open_module(page, hidden)
    settled(page)
    # The chart is still there — what is missing is the key.
    expect(slices(page)).to_have_count(2)
    expect(page.get_by_test_id("pie-legend-entry")).to_have_count(0)


def test_the_legend_moves(page, api, sites) -> None:
    """p.310: "left, right, top, or bottom relative to the chart". Measured,
    because a position that no rule acts on passes every other kind of check."""
    right = build(api, sites, "Pie legend right", {"legend": "right"})
    open_module(page, right)
    settled(page)
    on_the_right = page.get_by_test_id("pie-legend-entry").first.evaluate(
        "e => e.getBoundingClientRect().left"
    )
    pie_right = slices(page).first.evaluate("e => e.getBoundingClientRect().left")

    left = build(api, sites, "Pie legend left", {"legend": "left"})
    open_module(page, left)
    settled(page)
    on_the_left = page.get_by_test_id("pie-legend-entry").first.evaluate(
        "e => e.getBoundingClientRect().left"
    )
    assert on_the_left < on_the_right, (on_the_left, on_the_right)
    # And the pie moved out of its way rather than the legend landing on top.
    assert slices(page).first.evaluate("e => e.getBoundingClientRect().left") > pie_right

    # **Bottom, too, and the harness had to say so**: left and right are both
    # *beside* the chart, so a renderer that ignored the distinction between
    # beside and stacked passed both halves above. This one is below the pie.
    below = build(api, sites, "Pie legend bottom", {"legend": "bottom"})
    open_module(page, below)
    settled(page)
    legend_top = page.get_by_test_id("pie-legend-entry").first.evaluate(
        "e => e.getBoundingClientRect().top"
    )
    pie_bottom = slices(page).first.evaluate("e => e.getBoundingClientRect().bottom")
    assert legend_top > pie_bottom - 40, (legend_top, pie_bottom)


def test_a_segment_can_be_relabelled_and_recoloured(page, api, sites) -> None:
    """p.310's Segment display: "Enter the label key for the segment you want to
    override"."""
    mod = build(api, sites, "Pie segments", {
        "segments": [{"value": "open", "label": "Still open", "color": "#ff0000"}],
    })
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("pie-chart")).to_contain_text("Still open")
    expect(slice_for(page, "Still open")).to_have_attribute("fill", "#ff0000")
    # The other slice keeps the palette, which is what makes it an override.
    expect(slice_for(page, "closed")).not_to_have_attribute("fill", "#ff0000")


def test_a_hidden_segment_is_gone_and_the_rest_fill_the_circle(page, api, sites) -> None:
    """p.310's "Hide series". **The proportions change**, which is why hiding is
    a removal rather than a transparent slice: `open` alone is the whole
    circle, not three quarters of one with a gap."""
    mod = build(api, sites, "Pie hidden", {
        "segments": [{"value": "closed", "hidden": True}],
    })
    open_module(page, mod)
    settled(page)

    expect(slices(page)).to_have_count(1)
    expect(slice_for(page, "open").locator("title")).to_have_text("open: 3 (100.0%)")


def test_ontology_colours_are_used_when_asked_for(page, api, sites) -> None:
    """p.310's "Enable ontology colors": the conditional formatting rules set
    for that property in the Ontology. The fixture paints `open` and says
    nothing about `closed`, so the setting has to change one slice and leave
    the other alone."""
    plain = build(api, sites, "Pie plain colours")
    open_module(page, plain)
    settled(page)
    expect(slice_for(page, "open")).not_to_have_attribute("fill", "#123456")

    coloured = build(api, sites, "Pie ontology colours", {"ontologyColors": True})
    open_module(page, coloured)
    settled(page)
    expect(slice_for(page, "open")).to_have_attribute("fill", "#123456")
    expect(slice_for(page, "closed")).not_to_have_attribute("fill", "#123456")


def test_a_segment_colour_beats_the_ontology(page, api, sites) -> None:
    """p.310 offers both, and the one written on this widget is the more
    specific statement."""
    mod = build(api, sites, "Pie colour precedence", {
        "ontologyColors": True,
        "segments": [{"value": "open", "color": "#00ff00"}],
    })
    open_module(page, mod)
    settled(page)
    expect(slice_for(page, "open")).to_have_attribute("fill", "#00ff00")


def test_clicking_a_slice_narrows_a_downstream_set(page, api, sites) -> None:
    """p.310's "Selection as filter", asserted through a *second widget*: the
    clauses are what the module acts on, and a slice that highlights itself
    while writing nothing looks identical from the chart's side."""
    # **With a label override on the slice being clicked.** Without one the
    # label and the value are the same string, so a widget writing the wrong
    # one of them narrows correctly anyway — which is exactly what the harness
    # found this test doing.
    mod = build(api, sites, "Pie filter", {
        "segments": [{"value": "closed", "label": "Shut"}],
    }, with_filter=True)
    open_module(page, mod)
    settled(page)

    rows = page.locator(".data-grid tbody tr")
    expect(rows).to_have_count(len(ROWS))

    # **`closed`, not `open`, and the geometry is why.** A wedge's *bounding
    # box* centre is where Playwright aims, and for a three-quarter slice that
    # point lies in the quarter next to it — so clicking `open` was intercepted
    # by `closed` sitting on top of the aim point. A quarter wedge contains its
    # own bbox centre. The narrowing is sharper this way round anyway: one row
    # of four rather than three.
    slice_for(page, "Shut").click()
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("S4")

    # And clicking the same slice again clears it, so the control is the same
    # one both ways round.
    slice_for(page, "Shut").click()
    expect(rows).to_have_count(len(ROWS))


def test_a_slice_is_not_clickable_without_somewhere_to_put_the_answer(
    page, api, sites
) -> None:
    """A pointer cursor promising a narrowing that never happens is worse than
    a picture that admits it is one."""
    mod = build(api, sites, "Pie no filter")
    open_module(page, mod)
    settled(page)

    expect(slices(page).first).to_be_visible()
    expect(slice_for(page, "open")).not_to_have_attribute("role", "button")


def test_two_pies_over_different_sets_do_not_share_an_answer(page, api, sites) -> None:
    """**One widget per page hides a caching mistake.** Every other test here
    has a single pie, so a chart keyed on anything at all — even a constant —
    shows the right slices. Two pies over different sets is the state that
    tells them apart, and it is an ordinary page: a chart of everything beside
    a chart of one region.
    """
    mod = Module(api, "Pie two sets", beside=sites)
    mod.define({
        "format": 2,
        "layout": layout({
            "all": {"resolvedName": "CanvasPieChart",
                    "props": {"objectSetVariable": "v_all", "groupBy": "status"}},
            "north": {"resolvedName": "CanvasPieChart",
                      "props": {"objectSetVariable": "v_north", "groupBy": "status"}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "Every site",
                      "object_set": object_set(sites.site_type_id)},
            "v_north": {
                "id": "v_north", "kind": "object_set", "label": "The north",
                "object_set": object_set(
                    sites.site_type_id,
                    [{"property": "region", "op": "eq", "value": "north"}],
                ),
            },
        },
        "events": {},
    })
    open_module(page, mod)
    settled(page)

    charts = page.get_by_test_id("pie-chart")
    expect(charts).to_have_count(2)
    # Everything: three open and one closed. The north: two open and none
    # closed — so the second chart has *one* slice, and a chart showing the
    # first one's answer would have two.
    expect(charts.nth(0).get_by_test_id("pie-slice")).to_have_count(2)
    expect(charts.nth(1).get_by_test_id("pie-slice")).to_have_count(1)
    expect(charts.nth(1).locator("title")).to_have_text("open: 2 (100.0%)")


def test_ontology_colours_stay_off_when_something_else_loaded_the_type(
    page, api, sites
) -> None:
    """The colours-off half of the pair, **on a page where the object type is
    already in the query cache**.

    Without the table beside it the type is never fetched — the widget only
    asks for it when the setting is on — so "the setting is off" and "the rules
    are not here" were the same state, and a widget ignoring the setting passed.
    A table and a chart of the same objects is the ordinary page this happens on.
    """
    mod = Module(api, "Pie cached type", beside=sites)
    mod.define({
        "format": 2,
        "layout": layout({
            "tbl": {"resolvedName": "CanvasObjectTable",
                    "props": {"objectSetVariable": "v_set", "columns": "id,status",
                              "pageSize": 25, "activeVariable": None, "autoSelect": False}},
            "pie": {"resolvedName": "CanvasPieChart",
                    "props": {"objectSetVariable": "v_set", "groupBy": "status",
                              "ontologyColors": False}},
        }),
        "variables": {
            "v_set": {"id": "v_set", "kind": "object_set", "label": "Every site",
                      "object_set": object_set(sites.site_type_id)},
        },
        "events": {},
    })
    open_module(page, mod)
    settled(page)

    expect(page.locator(".data-grid tbody tr")).to_have_count(len(ROWS))
    expect(slice_for(page, "open")).not_to_have_attribute("fill", "#123456")


def test_the_panel_offers_the_bound_type_s_properties(page, api, sites) -> None:
    """Group by is a property of the *bound set's* type — a free-text field
    would let an author name one the server would refuse to group on."""
    mod = build(api, sites, "Pie panel")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Pie chart").first.click()
    options = page.get_by_test_id("pie-group-by").locator("option")
    expect(options).to_have_count(5)  # Choose… plus id, status, region, capacity
    expect(page.get_by_test_id("pie-group-by")).to_contain_text("Region")


def test_the_panel_offers_five_of_p310s_six_aggregations(page, api, sites) -> None:
    """This control was **disabled** until §228, with a hint saying a grouped
    sum needed declared property types. It does not any more (§220, §226,
    §227), so the hint would have been a refusal that was no longer true —
    §216's stale line, in a settings panel."""
    mod = build(api, sites, "Pie panel aggregation")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Pie chart").first.click()
    control = page.get_by_test_id("pie-aggregation")
    expect(control).to_be_enabled()
    assert control.locator("option").all_text_contents() == [
        "Count of objects", "Sum of", "Average of", "Minimum of", "Maximum of",
    ]


def test_the_property_picker_appears_only_for_an_aggregation_that_needs_one(
    page, api, sites
) -> None:
    """A count runs over no property, so a field asking which one would be a
    control with nothing to do — and an author who filled it in would reasonably
    expect it to change the chart."""
    mod = build(api, sites, "Pie panel property")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Pie chart").first.click()
    expect(page.get_by_test_id("pie-aggregation-property")).to_have_count(0)

    page.get_by_test_id("pie-aggregation").select_option("sum")
    picker = page.get_by_test_id("pie-aggregation-property")
    expect(picker).to_be_visible()
    # **Only what the server will aggregate.** `capacity` is the one integer;
    # `status` and `region` are strings and `object_sets` refuses them, so
    # offering them would produce a sentence about arithmetic in place of a
    # chart. A narrower list than Group by's, deliberately.
    assert picker.locator("option").all_text_contents() == ["Choose…", "Capacity"]
