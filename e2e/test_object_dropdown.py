"""p.455-458's Object Dropdown (parity `workshop.md` §10).

> "The Object Dropdown widget is used to select a single object from a list of
> objects… **Selected object**: This is an output variable for the widget that
> outputs a single object set of the currently selected object. This object set
> can be used in downstream widgets… **Allow no selection**: If enabled, the
> widget will be allowed to have no object selected." (p.455, p.457)

> "**Hide null properties**: If enabled, null properties will be hidden on a per
> object basis within the list. **Sort items by**… **Search items by**: Specify
> which object properties search is performed on." (p.458)

Which properties a search runs on and what matching means is
`apps/web/src/components/canvas/object-dropdown.test.ts`, mutation-tested
without a browser.

**What needs one is that the selection is an object set somebody else can
read.** p.457's output is the widget's whole reason to exist, and a dropdown
that showed the right title while writing the wrong clauses looks perfect from
the outside — so every test here that is about selection asserts it through a
*second widget* reading the same variable.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import open_builder, open_module, settled

# `note` is blank on Alpha and filled on the others, so p.458's per-object
# hiding has something to do on one row and nothing on the rest. `capacity` is
# an integer so the search-mode tests have a displayed property that is not
# searchable.
ROWS = [
    {"id": "S1", "name": "North West Depot", "region": "north", "note": "", "capacity": "40"},
    {"id": "S2", "name": "Bravo Yard", "region": "south", "note": "checked", "capacity": "10"},
    {"id": "S3", "name": "Charlie Depot", "region": "east", "note": "sealed", "capacity": "25"},
]


@pytest.fixture(scope="module")
def sites(api):
    mod = Module(api, "Object dropdown")
    mod.site_type_id = mod.object_type(
        columns=["id", "name", "region", "note", "capacity"], rows=ROWS,
        key="id", title="name", types={"capacity": "integer"},
    )
    return mod


def build(api, sites, name: str, props: dict | None = None):
    """The dropdown, plus a text widget reading its output through a narrowed
    set — so "what was selected" is asked of a *different* widget."""
    mod = Module(api, name, beside=sites)
    mod.define({
        "format": 2,
        "layout": layout({
            "dd": {
                "resolvedName": "CanvasObjectDropdown",
                "props": {"objectSetVariable": "v_set", "selectedVariable": "v_clauses",
                          "label": "", "properties": "", "hideNull": False,
                          "sortProperty": "", "searchMode": "on_screen",
                          "searchPropertyNames": "", "allowNoSelection": False,
                          **(props or {})},
            },
            # **A second widget reading the same variable.** Object Set Title
            # with "contains single object" names the object the set holds, and
            # renders nothing at all when the set is empty - so both "which one
            # was picked" and "none was" are answered by something other than
            # the dropdown.
            "echo": {
                "resolvedName": "CanvasObjectSetTitle",
                "props": {"objectSetVariable": "v_picked", "single": True,
                          "renderWhenEmpty": False},
            },
        }),
        "variables": {
            "v_set": {"id": "v_set", "kind": "object_set", "label": "Every site",
                      "object_set": object_set(sites.site_type_id)},
            # **An `array`, not an `object_set`.** What the widget writes is a
            # list of clauses; the *set* is what `narrow_set` makes of them
            # against the widget's own set, which is the whole reason a
            # selection is clauses rather than a definition (§207).
            "v_clauses": {"id": "v_clauses", "kind": "array", "label": "The selection"},
            # The selection means whatever it means *against the widget's set*,
            # which is why the widget writes clauses and this derives the set.
            "v_picked": {
                "id": "v_picked", "kind": "object_set", "label": "The picked object",
                "derivation": {"transform": "narrow_set", "inputs": ["v_set", "v_clauses"]},
            },
        },
        "events": {},
    })
    return mod


def options(page):
    return page.get_by_test_id("dropdown-option")


def open_list(page):
    page.get_by_test_id("dropdown-toggle").click()
    expect(page.get_by_test_id("dropdown-search")).to_be_visible()


def option_titles(page) -> list[str]:
    titles = page.locator(".canvas-dropdown-title")
    return [(titles.nth(i).text_content() or "").strip() for i in range(titles.count())]


def expect_titles(page, expected: list[str]) -> None:
    """Assert the option titles **through a wait**: `count()` and
    `text_content()` do not retry, so reading them straight after a click asks
    the page before it has re-rendered (§202)."""
    expect(options(page)).to_have_count(len(expected))
    assert option_titles(page) == expected, option_titles(page)


def test_it_lists_the_objects_by_their_title(page, api, sites) -> None:
    mod = build(api, sites, "Dropdown basic")
    open_module(page, mod)
    settled(page)

    open_list(page)
    expect_titles(page, ["North West Depot", "Bravo Yard", "Charlie Depot"])


def test_the_selection_reaches_a_downstream_widget(page, api, sites) -> None:
    """**p.457's whole reason to exist.** Asserted through a second widget
    reading the same variable, because a dropdown that showed the right title
    while writing the wrong clauses looks perfect from outside."""
    mod = build(api, sites, "Dropdown selection", {"allowNoSelection": True})
    open_module(page, mod)
    settled(page)

    open_list(page)
    options(page).filter(has_text="Charlie Depot").first.click()
    expect(page.get_by_test_id("dropdown-value")).to_have_text("Charlie Depot")
    expect(page.get_by_test_id("set-title")).to_have_text("Charlie Depot")


def test_the_first_object_is_selected_on_load(page, api, sites) -> None:
    """p.457's Allow no selection, **off**: the unconfigured widget picks the
    first object so downstream widgets have something to read. Asserted
    downstream, where it matters."""
    mod = build(api, sites, "Dropdown auto select")
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("dropdown-value")).to_have_text("North West Depot")
    expect(page.get_by_test_id("set-title")).to_have_text("North West Depot")


def test_allowing_no_selection_leaves_the_widget_empty_on_load(page, api, sites) -> None:
    """p.457 the other way round, and the pair is the point: with the setting on
    nothing is chosen, and the downstream variable is the *empty set* rather
    than the whole one — `in []`, which is why `object_sets.parse` had to learn
    it (§207)."""
    mod = build(api, sites, "Dropdown allow none", {"allowNoSelection": True})
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("dropdown-value")).to_have_text("Select an object...")
    # Nothing downstream at all: `narrow_set` over `in []` is the empty set,
    # and the title widget renders nothing for one.
    expect(page.get_by_test_id("set-title")).to_have_count(0)


def test_a_selection_can_be_cleared_when_no_selection_is_allowed(page, api, sites) -> None:
    """A viewer who *may* have no selection needs a way back to having none —
    the permission is not a control on its own."""
    mod = build(api, sites, "Dropdown clear", {"allowNoSelection": True})
    open_module(page, mod)
    settled(page)

    open_list(page)
    options(page).filter(has_text="Bravo Yard").first.click()
    expect(page.get_by_test_id("set-title")).to_have_text("Bravo Yard")

    open_list(page)
    page.get_by_test_id("dropdown-clear").click()
    expect(page.get_by_test_id("dropdown-value")).to_have_text("Select an object...")
    expect(page.get_by_test_id("set-title")).to_have_count(0)


def test_the_clear_control_is_absent_when_a_selection_is_required(page, api, sites) -> None:
    mod = build(api, sites, "Dropdown no clear")
    open_module(page, mod)
    settled(page)

    open_list(page)
    expect(options(page).first).to_be_visible()
    expect(page.get_by_test_id("dropdown-clear")).to_have_count(0)


def test_search_narrows_the_list(page, api, sites) -> None:
    """p.458's search, and **the middle of a word**: "starts with" would pass a
    test typed against "north", so the query here is one no prefix match
    finds."""
    mod = build(api, sites, "Dropdown search")
    open_module(page, mod)
    settled(page)

    open_list(page)
    page.get_by_test_id("dropdown-search").fill("depot")
    expect_titles(page, ["North West Depot", "Charlie Depot"])

    page.get_by_test_id("dropdown-search").fill("nothing here")
    expect(options(page)).to_have_count(0)
    expect(page.get_by_test_id("dropdown-no-matches")).to_be_visible()


def test_search_looks_only_at_what_is_on_screen_by_default(page, api, sites) -> None:
    """p.458's default mode is "all string properties that are **displayed**",
    so a property the widget does not show is not searched — which is the
    difference between this mode and the next one."""
    mod = build(api, sites, "Dropdown search on screen")
    open_module(page, mod)
    settled(page)

    open_list(page)
    # `region` holds "south" on Bravo Yard and is not displayed.
    page.get_by_test_id("dropdown-search").fill("south")
    expect(options(page)).to_have_count(0)


def test_search_can_be_pointed_at_a_property_that_is_not_shown(page, api, sites) -> None:
    mod = build(api, sites, "Dropdown search specific",
                {"searchMode": "specific", "searchPropertyNames": "region"})
    open_module(page, mod)
    settled(page)

    open_list(page)
    page.get_by_test_id("dropdown-search").fill("south")
    expect_titles(page, ["Bravo Yard"])
    # And the title is *not* searched in this mode, which is what makes it
    # different from "all".
    page.get_by_test_id("dropdown-search").fill("depot")
    expect(options(page)).to_have_count(0)


def test_search_can_cover_every_string_property(page, api, sites) -> None:
    mod = build(api, sites, "Dropdown search all", {"searchMode": "all"})
    open_module(page, mod)
    settled(page)

    open_list(page)
    page.get_by_test_id("dropdown-search").fill("south")
    expect_titles(page, ["Bravo Yard"])
    page.get_by_test_id("dropdown-search").fill("depot")
    expect_titles(page, ["North West Depot", "Charlie Depot"])


def test_properties_are_drawn_beneath_the_title(page, api, sites) -> None:
    """p.457's "Add property": what appears under each object's title."""
    mod = build(api, sites, "Dropdown properties", {"properties": "region,note"})
    open_module(page, mod)
    settled(page)

    open_list(page)
    bravo = options(page).filter(has_text="Bravo Yard").first
    expect(bravo).to_contain_text("south")
    expect(bravo).to_contain_text("checked")


def test_null_properties_hide_per_object(page, api, sites) -> None:
    """p.458: "hidden on a **per object** basis". Alpha's note is blank and the
    others' are not, so the setting has to remove one line from one row rather
    than the column from every row."""
    shown = build(api, sites, "Dropdown nulls shown", {"properties": "region,note"})
    open_module(page, shown)
    settled(page)
    open_list(page)
    expect(options(page).filter(has_text="North West Depot").first
           .get_by_test_id("dropdown-detail")).to_have_count(2)

    hidden = build(api, sites, "Dropdown nulls hidden",
                   {"properties": "region,note", "hideNull": True})
    open_module(page, hidden)
    settled(page)
    open_list(page)
    # One line gone from the blank row, both kept on a row that has values.
    expect(options(page).filter(has_text="North West Depot").first
           .get_by_test_id("dropdown-detail")).to_have_count(1)
    expect(options(page).filter(has_text="Bravo Yard").first
           .get_by_test_id("dropdown-detail")).to_have_count(2)


def test_the_list_can_be_sorted(page, api, sites) -> None:
    """p.458's Sort items by, **as far as the object-set language goes**.

    Not by property: `object_sets.parse_sort` refuses those, because instance
    properties are stored untyped and the two stores would order 250 and 40
    differently (decision 0006). What is here is the key, both ways round —
    and the fixture's keys run S1, S2, S3, so descending has to come back
    reversed rather than merely in some order.
    """
    ascending = build(api, sites, "Dropdown sorted up", {"sortProperty": "key"})
    open_module(page, ascending)
    settled(page)
    open_list(page)
    expect_titles(page, ["North West Depot", "Bravo Yard", "Charlie Depot"])

    descending = build(api, sites, "Dropdown sorted down", {"sortProperty": "-key"})
    open_module(page, descending)
    settled(page)
    open_list(page)
    expect_titles(page, ["Charlie Depot", "Bravo Yard", "North West Depot"])


def test_a_property_sort_a_document_holds_does_not_break_the_list(page, api, sites) -> None:
    """A document written against p.458's wording would name a property, and
    sending that to the server is a 422 in place of a list. The model reads it
    back to the default instead, so a stale setting costs the ordering rather
    than the widget."""
    mod = build(api, sites, "Dropdown stale sort", {"sortProperty": "name"})
    open_module(page, mod)
    settled(page)

    open_list(page)
    expect_titles(page, ["North West Depot", "Bravo Yard", "Charlie Depot"])


def test_the_label_is_drawn_only_when_there_is_one(page, api, sites) -> None:
    """p.457's optional label.

    **The blank case is whitespace, not the empty string** — the harness had to
    say so. `""` is falsy whether or not it has been read through the model, so
    a test using it asks nothing; `"   "` is truthy, and a widget that skipped
    the read would draw a row of nothing above itself that no author can see to
    remove.
    """
    blank = build(api, sites, "Dropdown blank label", {"label": "   "})
    open_module(page, blank)
    settled(page)
    expect(page.get_by_test_id("object-dropdown")).to_be_visible()
    expect(page.get_by_test_id("dropdown-label")).to_have_count(0)

    with_one = build(api, sites, "Dropdown label", {"label": "  Site  "})
    open_module(page, with_one)
    settled(page)
    label = page.get_by_test_id("dropdown-label")
    expect(label).to_be_visible()
    # **`text_content`, not `to_have_text`.** Playwright normalises whitespace
    # for that matcher, so "  Site  " and "Site" compare equal to it and the
    # trim would have been invisible.
    assert label.text_content() == "Site", repr(label.text_content())


def test_opening_the_list_does_not_move_the_page(page, api, sites) -> None:
    """A picker that shoves everything below it down the page as it opens makes
    the reader lose their place, and — §195's finding — anything that reflows
    under a pointer stops receiving the clicks aimed at it.

    Measured on a *second* widget, because the toggle itself sits above the
    panel and would not move even in flow.
    """
    mod = build(api, sites, "Dropdown float")
    open_module(page, mod)
    settled(page)

    echo = page.get_by_test_id("set-title")
    expect(echo).to_be_visible()
    before = echo.evaluate("e => e.getBoundingClientRect().top")
    open_list(page)
    expect(options(page).first).to_be_visible()
    after = echo.evaluate("e => e.getBoundingClientRect().top")
    assert abs(after - before) < 2, (before, after)


def test_the_panel_names_the_properties_that_exist(page, api, sites) -> None:
    """The property list is free text, so the panel has to say what is
    available — an author naming a property that silently never appears is the
    failure the model drops the name for."""
    mod = build(api, sites, "Dropdown panel")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Object dropdown").first.click()
    hint = page.get_by_test_id("dropdown-properties").locator("xpath=..")
    expect(hint).to_contain_text("region")
    expect(hint).to_contain_text("capacity")


def test_the_search_property_field_appears_only_for_the_specific_mode(page, api, sites) -> None:
    """p.458 gives the list of properties to only one of the three modes.
    Offering it under the others would be a control that changes nothing."""
    mod = build(api, sites, "Dropdown panel modes")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Object dropdown").first.click()
    expect(page.get_by_test_id("dropdown-search-mode")).to_be_visible()
    expect(page.get_by_test_id("dropdown-search-properties")).to_have_count(0)

    page.get_by_test_id("dropdown-search-mode").select_option("specific")
    expect(page.get_by_test_id("dropdown-search-properties")).to_be_visible()
