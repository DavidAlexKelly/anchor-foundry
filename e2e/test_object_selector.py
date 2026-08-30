"""p.444's Object Selector (parity `workshop.md` §10).

> "Object Selector: Allow the user to select multiple objects from a list of
> objects." (p.444)

That line is the whole specification — unlike every other filtering widget it
has no page of its own — so the widget is the Object Dropdown with a different
selection, and it shares that widget's model. What p.458's search rules mean is
`apps/web/src/components/canvas/object-dropdown.test.ts`, mutation-tested
without a browser.

**What needs one is that "several" reaches the rest of the module.** Every
selection test here reads a *downstream table* bound to the narrowed set rather
than the selector's own ticks: a widget can draw the right ticks while writing
the wrong clauses, and the clauses are what everything else acts on.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import open_builder, open_module, settled

ROWS = [
    {"id": "S1", "name": "North West Depot", "region": "north", "note": ""},
    {"id": "S2", "name": "Bravo Yard", "region": "south", "note": "checked"},
    {"id": "S3", "name": "Charlie Depot", "region": "east", "note": "sealed"},
]


@pytest.fixture(scope="module")
def sites(api):
    mod = Module(api, "Object selector")
    mod.site_type_id = mod.object_type(
        columns=["id", "name", "region", "note"], rows=ROWS, key="id", title="name",
    )
    return mod


def build(api, sites, name: str, props: dict | None = None):
    """The selector, plus a table reading the set its clauses narrow to."""
    mod = Module(api, name, beside=sites)
    mod.define({
        "format": 2,
        "layout": layout({
            "sel": {
                "resolvedName": "CanvasObjectSelector",
                "props": {"objectSetVariable": "v_set", "selectedVariable": "v_clauses",
                          "label": "", "properties": "", "hideNull": False,
                          "sortProperty": "key", "searchMode": "on_screen",
                          "searchPropertyNames": "", **(props or {})},
            },
            # The downstream reader. A *table* rather than a title, because the
            # question a multiple selection raises is which objects, and a
            # count would be satisfied by the wrong ones.
            "tbl": {
                "resolvedName": "CanvasObjectTable",
                "props": {"objectSetVariable": "v_picked", "columns": "name",
                          "pageSize": 25, "activeVariable": None, "autoSelect": False},
            },
        }),
        "variables": {
            "v_set": {"id": "v_set", "kind": "object_set", "label": "Every site",
                      "object_set": object_set(sites.site_type_id)},
            "v_clauses": {"id": "v_clauses", "kind": "array", "label": "The selection"},
            "v_picked": {
                "id": "v_picked", "kind": "object_set", "label": "The picked objects",
                "derivation": {"transform": "narrow_set", "inputs": ["v_set", "v_clauses"]},
            },
        },
        "events": {},
    })
    return mod


def open_list(page):
    page.get_by_test_id("selector-toggle").click()
    expect(page.get_by_test_id("selector-search")).to_be_visible()


def picked_rows(page):
    """The downstream table's rows — the whole point of the widget."""
    return page.locator(".data-grid tbody tr")


def tick(page, key: str):
    page.get_by_test_id(f"selector-tick-{key}").click()


def test_it_lists_the_objects_with_a_tick_each(page, api, sites) -> None:
    mod = build(api, sites, "Selector basic")
    open_module(page, mod)
    settled(page)

    open_list(page)
    expect(page.get_by_test_id("selector-option")).to_have_count(3)
    expect(page.get_by_test_id("selector-option").first).to_contain_text("North West Depot")


def test_the_ticks_show_what_is_selected(page, api, sites) -> None:
    """**The reader's own feedback, and nothing else here was asserting it.**

    Every other test in this file reads the downstream table, which is right —
    the clauses are what the module acts on — but a widget whose boxes never
    tick, or tick all at once, would pass all of them: the clicks still write
    the right clauses. The harness caught both, in the same run.
    """
    mod = build(api, sites, "Selector ticks")
    open_module(page, mod)
    settled(page)

    open_list(page)
    for key in ("S1", "S2", "S3"):
        expect(page.get_by_test_id(f"selector-tick-{key}")).not_to_be_checked()

    tick(page, "S2")
    expect(page.get_by_test_id("selector-tick-S2")).to_be_checked()
    # And only that one — a widget ticking everything is as wrong as one
    # ticking nothing, and looks more plausible.
    expect(page.get_by_test_id("selector-tick-S1")).not_to_be_checked()
    expect(page.get_by_test_id("selector-tick-S3")).not_to_be_checked()

    tick(page, "S2")
    expect(page.get_by_test_id("selector-tick-S2")).not_to_be_checked()


def test_the_tick_sits_beside_its_title(page, api, sites) -> None:
    """Asserted by position, because a class no rule matches passes every other
    kind of check (§211). A box stacked above its own label reads as belonging
    to the row before it."""
    # **Two property lines, on a row that has both values.** A one-line row
    # cannot tell `align-items: start` from `center`: the difference is how far
    # the box drops as the row grows, so a short row makes the two identical.
    mod = build(api, sites, "Selector layout", {"properties": "region,note"})
    open_module(page, mod)
    settled(page)

    open_list(page)
    row = page.get_by_test_id("selector-option").filter(has_text="Bravo Yard").first
    expect(row).to_be_visible()
    box, title, whole = row.evaluate(
        "e => [e.querySelector('input').getBoundingClientRect(),"
        " e.querySelector('.canvas-dropdown-title').getBoundingClientRect(),"
        " e.getBoundingClientRect()]"
    )
    assert whole["height"] > 40, whole  # the row really is several lines tall
    assert box["right"] <= title["left"] + 1, (box, title)
    assert abs(box["top"] - title["top"]) < 6, (box, title)


def test_the_property_lines_sit_beneath_the_title(page, api, sites) -> None:
    """p.457: "a property to display **beneath** the object title".

    Counting the lines is not enough — they were running *inline* after the
    title for a while and every count passed. The measurement is what says
    beneath.
    """
    mod = build(api, sites, "Selector stacked", {"properties": "region,note"})
    open_module(page, mod)
    settled(page)

    open_list(page)
    row = page.get_by_test_id("selector-option").filter(has_text="Bravo Yard").first
    expect(row).to_be_visible()
    title, first_detail = row.evaluate(
        "e => [e.querySelector('.canvas-dropdown-title').getBoundingClientRect(),"
        " e.querySelector('.canvas-dropdown-detail').getBoundingClientRect()]"
    )
    assert first_detail["top"] >= title["bottom"] - 1, (title, first_detail)


def test_search_can_cover_a_property_that_is_not_shown(page, api, sites) -> None:
    """p.458's modes reach this widget too — the harness found that nothing here
    exercised them, so the mode could have been hardcoded and every other test
    would still pass. `region` is not displayed, so the default mode must *not*
    find it and "all searchable" must."""
    default = build(api, sites, "Selector search default")
    open_module(page, default)
    settled(page)
    open_list(page)
    page.get_by_test_id("selector-search").fill("south")
    expect(page.get_by_test_id("selector-option")).to_have_count(0)

    everything = build(api, sites, "Selector search all", {"searchMode": "all"})
    open_module(page, everything)
    settled(page)
    open_list(page)
    page.get_by_test_id("selector-search").fill("south")
    expect(page.get_by_test_id("selector-option")).to_have_count(1)
    expect(page.get_by_test_id("selector-option").first).to_contain_text("Bravo Yard")


def test_nothing_is_selected_on_load_and_that_narrows_to_nothing(page, api, sites) -> None:
    """**The difference between "none" and "nobody has said".**

    A variable nothing has written means *no narrowing*, so a downstream table
    would show all three rows — which is the failure §207 taught
    `object_sets.parse` to express. The widget states `in []` instead, and the
    table below is empty.
    """
    mod = build(api, sites, "Selector empty")
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("selector-value")).to_have_text("Select objects...")
    expect(picked_rows(page)).to_have_count(0)


def test_ticking_two_objects_sends_both_downstream(page, api, sites) -> None:
    """p.444's whole line, asserted where it matters: **two**, and the right
    two — the fixture has three so "everything" and "the selection" are
    different answers."""
    mod = build(api, sites, "Selector two")
    open_module(page, mod)
    settled(page)

    open_list(page)
    tick(page, "S1")
    tick(page, "S3")
    expect(picked_rows(page)).to_have_count(2)
    expect(picked_rows(page)).to_contain_text(["North West Depot", "Charlie Depot"])


def test_unticking_removes_one_and_keeps_the_rest(page, api, sites) -> None:
    mod = build(api, sites, "Selector untick")
    open_module(page, mod)
    settled(page)

    open_list(page)
    tick(page, "S1")
    tick(page, "S2")
    expect(picked_rows(page)).to_have_count(2)

    tick(page, "S1")
    expect(picked_rows(page)).to_have_count(1)
    expect(picked_rows(page).first).to_contain_text("Bravo Yard")


def test_the_list_stays_open_while_ticking(page, api, sites) -> None:
    """The whole point is choosing several; a panel that closed on each click
    would make that four clicks instead of one."""
    mod = build(api, sites, "Selector stays open")
    open_module(page, mod)
    settled(page)

    open_list(page)
    tick(page, "S1")
    expect(page.get_by_test_id("selector-search")).to_be_visible()
    tick(page, "S2")
    expect(page.get_by_test_id("selector-option")).to_have_count(3)


def test_the_control_names_one_object_and_counts_several(page, api, sites) -> None:
    """A reader who has picked one can see which; a count there would withhold
    an answer the widget has."""
    mod = build(api, sites, "Selector summary")
    open_module(page, mod)
    settled(page)

    open_list(page)
    tick(page, "S2")
    expect(page.get_by_test_id("selector-value")).to_have_text("Bravo Yard")
    tick(page, "S3")
    expect(page.get_by_test_id("selector-value")).to_have_text("2 selected")


def test_the_selection_can_be_cleared(page, api, sites) -> None:
    mod = build(api, sites, "Selector clear")
    open_module(page, mod)
    settled(page)

    open_list(page)
    tick(page, "S1")
    tick(page, "S2")
    expect(picked_rows(page)).to_have_count(2)

    page.get_by_test_id("selector-clear").click()
    expect(page.get_by_test_id("selector-value")).to_have_text("Select objects...")
    # Cleared is the *empty* set, not the whole one — the same distinction the
    # load-time state makes, reached from the other direction.
    expect(picked_rows(page)).to_have_count(0)


def test_the_clear_control_appears_only_when_there_is_something_to_clear(
    page, api, sites
) -> None:
    mod = build(api, sites, "Selector clear absent")
    open_module(page, mod)
    settled(page)

    open_list(page)
    expect(page.get_by_test_id("selector-option").first).to_be_visible()
    expect(page.get_by_test_id("selector-clear")).to_have_count(0)
    tick(page, "S1")
    expect(page.get_by_test_id("selector-clear")).to_be_visible()


def test_a_selection_survives_searching_for_something_else(page, api, sites) -> None:
    """**The one thing multiple selection gets wrong most often.** Ticks live in
    the variable, not in the list, so filtering the list must not drop what is
    already chosen — a reader narrowing to find their second object would
    otherwise lose their first."""
    mod = build(api, sites, "Selector search keeps")
    open_module(page, mod)
    settled(page)

    open_list(page)
    tick(page, "S1")
    page.get_by_test_id("selector-search").fill("bravo")
    expect(page.get_by_test_id("selector-option")).to_have_count(1)
    tick(page, "S2")

    page.get_by_test_id("selector-search").fill("")
    expect(picked_rows(page)).to_have_count(2)
    expect(picked_rows(page)).to_contain_text(["North West Depot", "Bravo Yard"])


def test_search_narrows_the_list(page, api, sites) -> None:
    mod = build(api, sites, "Selector search")
    open_module(page, mod)
    settled(page)

    open_list(page)
    # The middle of a word, so a `starts_with` implementation would fail here.
    page.get_by_test_id("selector-search").fill("depot")
    expect(page.get_by_test_id("selector-option")).to_have_count(2)
    page.get_by_test_id("selector-search").fill("nothing here")
    expect(page.get_by_test_id("selector-no-matches")).to_be_visible()


def test_properties_are_drawn_beneath_each_title_and_nulls_can_hide(
    page, api, sites
) -> None:
    """p.458's per-object hiding, shared with the Dropdown. S1's note is blank
    and the others' are not, so the setting removes one line from one row."""
    shown = build(api, sites, "Selector properties", {"properties": "region,note"})
    open_module(page, shown)
    settled(page)
    open_list(page)
    first = page.get_by_test_id("selector-option").first
    expect(first).to_contain_text("north")
    expect(first.get_by_test_id("selector-detail")).to_have_count(2)

    hidden = build(api, sites, "Selector properties hidden",
                   {"properties": "region,note", "hideNull": True})
    open_module(page, hidden)
    settled(page)
    open_list(page)
    expect(page.get_by_test_id("selector-option").first
           .get_by_test_id("selector-detail")).to_have_count(1)
    expect(page.get_by_test_id("selector-option").nth(1)
           .get_by_test_id("selector-detail")).to_have_count(2)


def test_the_list_can_be_sorted(page, api, sites) -> None:
    mod = build(api, sites, "Selector sorted", {"sortProperty": "-key"})
    open_module(page, mod)
    settled(page)

    open_list(page)
    expect(page.get_by_test_id("selector-option").first).to_contain_text("Charlie Depot")
    expect(page.get_by_test_id("selector-option").last).to_contain_text("North West Depot")


def test_the_label_is_drawn_only_when_there_is_one(page, api, sites) -> None:
    blank = build(api, sites, "Selector blank label", {"label": "   "})
    open_module(page, blank)
    settled(page)
    expect(page.get_by_test_id("object-selector")).to_be_visible()
    expect(page.get_by_test_id("selector-label")).to_have_count(0)

    named = build(api, sites, "Selector label", {"label": "  Sites  "})
    open_module(page, named)
    settled(page)
    label = page.get_by_test_id("selector-label")
    expect(label).to_be_visible()
    # `text_content`, not `to_have_text`: that matcher normalises whitespace and
    # could not see the trim (§214).
    assert label.text_content() == "Sites", repr(label.text_content())


def test_the_panel_offers_the_same_settings_as_the_dropdown(page, api, sites) -> None:
    """p.444 gives the Selector no configuration of its own, so it has the
    Dropdown's — **minus Allow no selection**, which is meaningless for a
    multiple selection whose resting state is already none."""
    mod = build(api, sites, "Selector panel")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Object selector").first.click()
    expect(page.get_by_test_id("selector-sort")).to_be_visible()
    expect(page.get_by_test_id("selector-search-mode")).to_be_visible()
    expect(page.get_by_test_id("dropdown-allow-none")).to_have_count(0)
    hint = page.get_by_test_id("selector-properties").locator("xpath=..")
    expect(hint).to_contain_text("region")
