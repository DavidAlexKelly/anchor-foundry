"""p.470–471's Exploration Filter Pills (parity `workshop.md` §10).

> "Use the Exploration Filter Pills widget to visualize and apply filters to an
> object set." (p.470)

**The first widget that reads a set's filters rather than writing them**, which
is why the browser matters here more than usual: the claim is that what the
pills say is what the set actually is, and the only way to check that is to put
a table beside them and compare.

The variable graph:

    v_base     (object_set)   every site, filtered to band=new in its definition
    v_clauses  (array)        what the pills write
    v_narrow   (object_set)   narrow_set(v_base, v_clauses)

**The base set carries a filter of its own, and that is the fixture's argument.**
A pill for `band = new` comes from the definition and is not in `v_clauses`, so
the widget cannot take it off; a pill for `region = north` came from the variable
and can. A fixture whose base set had no filters could not tell a widget that
knows the difference from one that offers ✕ on everything.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, settled, stays

ROWS = [
    {"id": "N1", "region": "north", "band": "new", "capacity": "10"},
    {"id": "N2", "region": "north", "band": "new", "capacity": "40"},
    {"id": "N3", "region": "north", "band": "old", "capacity": "25"},
    {"id": "S1", "region": "south", "band": "new", "capacity": "30"},
    {"id": "S2", "region": "south", "band": "new", "capacity": "5"},
]
NEW = [r for r in ROWS if r["band"] == "new"]
NEW_NORTH = [r for r in NEW if r["region"] == "north"]


@pytest.fixture(scope="module")
def sites(api):
    mod = Module(api, "Filter pills")
    mod.site_type_id = mod.object_type(
        columns=["id", "region", "band", "capacity"], rows=ROWS, key="id",
        title="id", types={"capacity": "integer"},
    )
    return mod


def build(api, sites, name: str, props: dict | None = None, clauses=None):
    mod = Module(api, name, beside=sites)
    mod.define({
        "format": 2,
        "layout": layout({
            "pills": {
                "resolvedName": "CanvasFilterPills",
                "props": {
                    "objectSetVariable": "v_narrow", "variable": "v_clauses",
                    "mode": "read_only", "showTypePill": False, "title": "",
                    **(props or {}),
                },
            },
            "tbl": {
                "resolvedName": "CanvasObjectTable",
                "props": {"objectSetVariable": "v_narrow",
                          "columns": "id,region,band", "pageSize": 25},
            },
        }),
        "variables": {
            "v_base": {
                "id": "v_base", "kind": "object_set", "label": "New band",
                # p.470's "a specified object set": this one has a filter of its
                # own, which is what makes a structural pill possible.
                "object_set": object_set(
                    sites.site_type_id,
                    filters=[{"property": "band", "op": "eq", "value": "new"}],
                ),
            },
            "v_clauses": {
                "id": "v_clauses", "kind": "array", "label": "Applied filters",
                # `default`, not `value` — a variable's starting contents are
                # its default, and the resolver reads `variable.default` when
                # nothing has been set.
                **({"default": clauses} if clauses is not None else {}),
            },
            "v_narrow": {
                "id": "v_narrow", "kind": "object_set", "label": "What is shown",
                "derivation": {"transform": "narrow_set", "inputs": ["v_base", "v_clauses"]},
            },
        },
        "events": {},
    })
    return mod


NORTH = [{"property": "region", "op": "eq", "value": "north"}]


def pills(page):
    return page.get_by_test_id("filter-pill")


def texts(page) -> list[str]:
    got = page.get_by_test_id("filter-pill-text")
    return [(got.nth(i).text_content() or "").strip() for i in range(got.count())]


def pill_for(page, text: str):
    return pills(page).filter(has_text=text).first


def table_rows(page) -> int:
    return page.locator(".data-grid tbody tr").count()


def test_the_pills_are_the_filters_the_set_actually_has(page, api, sites) -> None:
    """p.470's whole job. Both filters are shown — one from the base set's own
    definition, one from the variable — because the resolved set is the sum of
    them and that is what the table beside it is showing."""
    mod = build(api, sites, "Pills read", clauses=NORTH)
    open_module(page, mod)
    settled(page)

    eventually(lambda: texts(page), lambda t: len(t) == 2, what="two pills")
    assert texts(page) == ["Band is new", "Region is north"], texts(page)
    eventually(lambda: table_rows(page), lambda n: n == len(NEW_NORTH),
               what="the table agreeing with the pills")


def test_a_set_with_no_filters_says_so(page, api, sites) -> None:
    """Said rather than left blank: an empty row of pills is indistinguishable
    from a widget that failed to load."""
    mod = Module(api, "Pills none", beside=sites)
    mod.define({
        "format": 2,
        "layout": layout({
            "pills": {"resolvedName": "CanvasFilterPills",
                      "props": {"objectSetVariable": "v_all", "variable": None,
                                "mode": "read_only"}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "Everything",
                      "object_set": object_set(sites.site_type_id)},
        },
        "events": {},
    })
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("filter-pills-none")).to_be_visible()
    expect(pills(page)).to_have_count(0)


def test_read_only_offers_no_way_to_change_anything(page, api, sites) -> None:
    """p.470's first mode: "a non-editable view of any filters applied"."""
    mod = build(api, sites, "Pills read only", {"mode": "read_only"}, clauses=NORTH)
    open_module(page, mod)
    settled(page)

    eventually(lambda: pills(page).count(), lambda n: n == 2, what="two pills")
    expect(page.get_by_test_id("filter-pill-remove")).to_have_count(0)
    expect(page.get_by_test_id("filter-pill-edit")).to_have_count(0)
    expect(page.get_by_test_id("filter-pill-add")).to_have_count(0)


def test_remove_only_takes_a_filter_off_and_the_set_widens(page, api, sites) -> None:
    """p.470's second mode. Asserted through the table, because a pill that
    disappears while the set stays narrow is the failure that looks like
    success."""
    mod = build(api, sites, "Pills remove", {"mode": "remove"}, clauses=NORTH)
    open_module(page, mod)
    settled(page)

    eventually(lambda: table_rows(page), lambda n: n == len(NEW_NORTH),
               what="the narrowed table")
    pill_for(page, "Region is north").get_by_test_id("filter-pill-remove").click()
    eventually(lambda: table_rows(page), lambda n: n == len(NEW),
               what="the table widening to the whole base set")
    eventually(lambda: texts(page), lambda t: t == ["Band is new"],
               what="only the structural pill left")


def test_a_filter_the_widget_cannot_remove_offers_no_remove(page, api, sites) -> None:
    """**The rule no other widget needs.** `band is new` is in the base set's
    own definition, not in the variable this widget writes — so removing it is
    something no amount of writing to that variable can do. A ✕ on it would
    write a list that changes nothing while the pill sat there, which is §214's
    control that looks like it works.

    `region is north` is beside it and does have one, so this is a difference
    between two pills on one screen rather than an absence.
    """
    mod = build(api, sites, "Pills fixed", {"mode": "add"}, clauses=NORTH)
    open_module(page, mod)
    settled(page)

    eventually(lambda: pills(page).count(), lambda n: n == 2, what="two pills")
    structural = pill_for(page, "Band is new")
    expect(structural).to_have_attribute("data-removable", "false")
    expect(structural.get_by_test_id("filter-pill-remove")).to_have_count(0)
    expect(structural.get_by_test_id("filter-pill-edit")).to_have_count(0)

    written = pill_for(page, "Region is north")
    expect(written).to_have_attribute("data-removable", "true")
    expect(written.get_by_test_id("filter-pill-remove")).to_be_visible()


def test_update_mode_edits_a_value_and_the_set_follows(page, api, sites) -> None:
    """p.470's third mode: "remove or edit any applied filters"."""
    mod = build(api, sites, "Pills update", {"mode": "update"}, clauses=NORTH)
    open_module(page, mod)
    settled(page)

    eventually(lambda: table_rows(page), lambda n: n == len(NEW_NORTH),
               what="the northern rows")
    pill_for(page, "Region is north").get_by_test_id("filter-pill-edit").click()
    box = page.get_by_test_id("filter-pill-input")
    expect(box).to_be_visible()
    # The box opens holding the value it is about to replace, so an edit is an
    # edit rather than a retype.
    expect(box).to_have_value("north")
    box.fill("south")
    box.press("Enter")

    eventually(lambda: texts(page), lambda t: t == ["Band is new", "Region is south"],
               what="the pill naming the new value")
    eventually(lambda: table_rows(page),
               lambda n: n == len([r for r in NEW if r["region"] == "south"]),
               what="the table following the edit")


def test_an_abandoned_edit_changes_nothing(page, api, sites) -> None:
    """Escape closes the box without writing. A viewer who opens an editor and
    thinks better of it has not filtered anything."""
    mod = build(api, sites, "Pills escape", {"mode": "update"}, clauses=NORTH)
    open_module(page, mod)
    settled(page)

    eventually(lambda: pills(page).count(), lambda n: n == 2, what="two pills")
    pill_for(page, "Region is north").get_by_test_id("filter-pill-edit").click()
    page.get_by_test_id("filter-pill-input").fill("south")
    page.get_by_test_id("filter-pill-input").press("Escape")

    expect(page.get_by_test_id("filter-pill-input")).to_have_count(0)

    # **`stays`, and it took three attempts to get here.** Escape closes the box
    # at once while a commit takes a round trip, so every one-shot read taken
    # straight afterwards — of the pills, of the table — happens *before* the
    # write it is meant to rule out. `settled` does not help (it waits for a
    # canvas block already on screen), and neither does re-reading through
    # `expect`, which stops at the first read that matches and that is the one
    # taken too early. The only honest form of "nothing happened" here is to
    # keep looking for longer than the write would have taken.
    stays(lambda: texts(page), lambda t: t == ["Band is new", "Region is north"],
          what="the pill after an abandoned edit")
    assert table_rows(page) == len(NEW_NORTH)


def test_add_mode_applies_a_new_filter(page, api, sites) -> None:
    """p.470's fourth mode: "add new property filters to be applied on the
    object set"."""
    mod = build(api, sites, "Pills add", {"mode": "add"})
    open_module(page, mod)
    settled(page)

    eventually(lambda: table_rows(page), lambda n: n == len(NEW), what="the base set")
    page.get_by_test_id("filter-add-property").select_option("region")
    page.get_by_test_id("filter-add-value").fill("north")
    page.get_by_test_id("filter-add-apply").click()

    eventually(lambda: table_rows(page), lambda n: n == len(NEW_NORTH),
               what="the table after the new filter")
    eventually(lambda: texts(page), lambda t: t == ["Band is new", "Region is north"],
               what="the new pill")


def test_the_add_row_offers_ordered_operators_only_where_they_work(
    page, api, sites
) -> None:
    """**§221's rule at the viewer's end.** `capacity` is an integer, so the two
    stores order it identically and `is at least` is offered. `region` is text,
    which has no order they agree on (decision 0006 §2, permanently) — offering
    it there would produce a 422 in place of a narrowed set.

    The list is `filter-clause.ts`'s, which an API test compares against
    `object_sets` — so this asserts the widget uses it, not that it is right.
    """
    mod = build(api, sites, "Pills operators", {"mode": "add"})
    open_module(page, mod)
    settled(page)

    page.get_by_test_id("filter-add-property").select_option("capacity")
    ops = page.get_by_test_id("filter-add-op")
    expect(ops.locator("option")).to_have_count(8)
    numeric = ops.locator("option").evaluate_all("nodes => nodes.map(n => n.value)")
    assert numeric == ["eq", "neq", "in", "starts_with", "gt", "gte", "lt", "lte"], numeric

    page.get_by_test_id("filter-add-property").select_option("region")
    expect(ops.locator("option")).to_have_count(4)
    text = ops.locator("option").evaluate_all("nodes => nodes.map(n => n.value)")
    assert text == ["eq", "neq", "in", "starts_with"], text


def test_an_operator_the_new_property_cannot_take_is_reset(page, api, sites) -> None:
    """Picking `capacity is at least`, then changing the property to `region`,
    must not leave `gte` held — the server refuses an ordered comparison on
    text, so the next Apply would be a 422 the viewer never asked for.

    **Asserted by applying it, not by reading the select**, and a mutant is what
    said so. A `<select>` whose `value` is not among its options *displays* the
    first one, so `to_have_value("eq")` passes while React still holds `gte` —
    the DOM and the state disagree and only the state is sent. The filter
    working is the only assertion that can tell them apart.
    """
    mod = build(api, sites, "Pills operator reset", {"mode": "add"})
    open_module(page, mod)
    settled(page)

    page.get_by_test_id("filter-add-property").select_option("capacity")
    page.get_by_test_id("filter-add-op").select_option("gte")
    page.get_by_test_id("filter-add-property").select_option("region")
    expect(page.get_by_test_id("filter-add-op")).to_have_value("eq")

    page.get_by_test_id("filter-add-value").fill("north")
    page.get_by_test_id("filter-add-apply").click()
    eventually(lambda: texts(page), lambda t: t == ["Band is new", "Region is north"],
               what="an `is` filter rather than a refused `is at least`")
    eventually(lambda: table_rows(page), lambda n: n == len(NEW_NORTH),
               what="the table narrowing rather than erroring")


def test_without_an_output_variable_the_pills_stay_read_only(page, api, sites) -> None:
    """p.470 calls the output "optional", and for Read only it is. For the other
    three there is nowhere for a change to go, so the controls are not drawn —
    a ✕ that writes to nothing is §214's control that looks like it works.

    The panel says so too, and that is a different assertion: the panel warns
    the *author*, this is what the *viewer* sees.
    """
    mod = build(api, sites, "Pills no output", {"mode": "add", "variable": None})
    open_module(page, mod)
    settled(page)

    # The set still has its own filter, so there is a pill to not-offer-to-remove.
    eventually(lambda: texts(page), lambda t: t == ["Band is new"],
               what="the structural pill")
    expect(page.get_by_test_id("filter-pill-remove")).to_have_count(0)
    expect(page.get_by_test_id("filter-pill-edit")).to_have_count(0)
    expect(page.get_by_test_id("filter-pill-add")).to_have_count(0)


def test_an_ordered_filter_a_viewer_adds_narrows_numerically(page, api, sites) -> None:
    """The end-to-end version of §221: `capacity >= 25` over the new band is
    N2 (40) and S1 (30), which is **not** what a text comparison would give —
    "5" > "25" as text, so S2 would be in it."""
    mod = build(api, sites, "Pills ordered", {"mode": "add"})
    open_module(page, mod)
    settled(page)

    page.get_by_test_id("filter-add-property").select_option("capacity")
    page.get_by_test_id("filter-add-op").select_option("gte")
    page.get_by_test_id("filter-add-value").fill("25")
    page.get_by_test_id("filter-add-apply").click()

    eventually(lambda: table_rows(page), lambda n: n == 2,
               what="the two rows at or above 25")
    eventually(lambda: texts(page),
               lambda t: t == ["Band is new", "Capacity is at least 25"],
               what="the pill in the ontology's words")


def test_an_unfinished_filter_cannot_be_applied(page, api, sites) -> None:
    """A blank value is not a filter: `eq ""` matches rows whose property is the
    empty string, which is never what an unfinished row means."""
    mod = build(api, sites, "Pills unfinished", {"mode": "add"})
    open_module(page, mod)
    settled(page)

    page.get_by_test_id("filter-add-property").select_option("region")
    expect(page.get_by_test_id("filter-add-apply")).to_be_disabled()
    page.get_by_test_id("filter-add-value").fill("   ")
    expect(page.get_by_test_id("filter-add-apply")).to_be_disabled()
    page.get_by_test_id("filter-add-value").fill("north")
    expect(page.get_by_test_id("filter-add-apply")).to_be_enabled()


def test_the_object_type_pill_names_the_type(page, api, sites) -> None:
    """p.471's Display object type pill. Named from the ontology, because the
    set definition holds an id."""
    off = build(api, sites, "Pills no type", {"showTypePill": False})
    open_module(page, off)
    settled(page)
    expect(page.get_by_test_id("filter-pill-type")).to_have_count(0)

    on = build(api, sites, "Pills type", {"showTypePill": True})
    open_module(page, on)
    settled(page)
    expect(page.get_by_test_id("filter-pill-type")).to_be_visible()
    assert (page.get_by_test_id("filter-pill-type").text_content() or "").strip() not in (
        "", "Object type",
    )


def test_the_pills_are_inert_in_the_builder(page, api, sites) -> None:
    """Editing a filter in the builder would write a viewer's state into the
    document being edited. The pills are shown — an author has to see what they
    configured — and they carry no controls."""
    mod = build(api, sites, "Pills builder", {"mode": "add"}, clauses=NORTH)
    open_builder(page, mod)
    settled(page)

    eventually(lambda: pills(page).count(), lambda n: n == 2, what="two pills")
    expect(page.get_by_test_id("filter-pill-remove")).to_have_count(0)
    expect(page.get_by_test_id("filter-pill-add")).to_have_count(0)


def test_the_panel_says_an_editable_mode_needs_an_output(page, api, sites) -> None:
    """p.470 calls the output optional, and it is — for Read only. The other
    three change filters, and without a variable there is nowhere for a change
    to go, so the panel says so rather than leaving controls that do nothing."""
    mod = build(api, sites, "Pills panel", {"mode": "remove", "variable": None})
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Filter pills").first.click()
    expect(page.get_by_test_id("pills-needs-output")).to_be_visible()

    page.get_by_test_id("pills-mode").select_option("read_only")
    expect(page.get_by_test_id("pills-needs-output")).to_have_count(0)


def test_the_panel_says_why_there_is_no_operator_toggle(page, api, sites) -> None:
    """p.470's "Prevent users from changing operators (or, and)". Every clause
    an object set takes is an `and`, so there is no or/and for a viewer to
    change and nothing for a toggle to prevent. Said where the toggle would be,
    because an absent control reads as an oversight (§214)."""
    mod = build(api, sites, "Pills operator toggle")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Filter pills").first.click()
    expect(page.get_by_test_id("pills-no-operator-toggle")).to_contain_text("and")
