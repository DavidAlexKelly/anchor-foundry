"""p.265-266's Property List widget (parity `workshop.md` §10).

> "The Property List widget displays a list of properties from a single provided
> object… If the object set contains more than one object, only the first object
> will be displayed within the widget. … **Layout**: … Property values can either
> be displayed adjacent to their corresponding property type labels or below. …
> **Hide null properties**: If enabled, null properties will be hidden from the
> list." (p.265-266)

Which properties and how many columns is
`apps/web/src/components/canvas/property-list.test.ts`, mutation-tested without
a browser.

**What needs one is that the list is of an actual object.** The values come from
a server-side evaluation of the set and the *labels* from a second fetch of the
object type — the widget has to put two responses together, and every way of
getting that wrong produces a list that looks perfectly reasonable.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import open_builder, open_module, settled

ROWS = [
    {"id": "S1", "name": "Alpha site", "region": "north", "note": ""},
    {"id": "S2", "name": "Bravo site", "region": "south", "note": "checked"},
]


def build(api, name: str, props: dict | None = None, *, filters=None):
    mod = Module(api, name)
    type_id = mod.object_type(
        columns=["id", "name", "region", "note"], rows=ROWS, key="id", title="name"
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "pl": {
                "resolvedName": "CanvasPropertyList",
                "props": {"objectSetVariable": "v_set", "layout": "adjacent",
                          "properties": "", "columns": 1, "hideNull": False,
                          **(props or {})},
            },
        }),
        "variables": {
            "v_set": {"id": "v_set", "kind": "object_set", "label": "The set",
                      "object_set": object_set(type_id, filters)},
        },
        "events": {},
    })
    return mod


def rows(page):
    return page.get_by_test_id("property-row")


def labels(page) -> list[str]:
    """**`text_content`, not `inner_text`.** The stylesheet upper-cases these,
    and `inner_text` returns what is *rendered* — so an assertion written
    against the real display names would fail on a styling choice, and one
    written against the upper-cased strings would pass just as happily if the
    labels were replaced by the api names in caps."""
    return [(rows(page).nth(i).locator("dt").text_content() or "").strip()
            for i in range(rows(page).count())]


def expect_labels(page, expected: list[str]) -> None:
    """Assert the labels, **through a wait**.

    `labels` reads `count()` and `text_content()`, neither of which retries, so
    calling it straight after `settled()` asks the page a question before it has
    the answer — and gets `[]`, which compares unequal for the wrong reason.
    Waiting on the count first is the clock (§202); the comparison is then about
    the labels rather than about how fast the assertion ran.
    """
    expect(rows(page)).to_have_count(len(expected))
    assert labels(page) == expected, labels(page)


def one(api, name: str, props: dict | None = None):
    """A module narrowed to S1, which is the row with the blank `note`."""
    return build(api, name, props,
                 filters=[{"property": "id", "op": "eq", "value": "S1"}])


def test_it_lists_the_properties_of_the_object(page, api) -> None:
    mod = one(api, "Property list basic")
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("property-list")).to_be_visible()
    expect(rows(page)).to_have_count(4)
    # **The labels are the type's display names, not the api names** — which is
    # the half that needs the second fetch.
    expect_labels(page, ["Id", "Name", "Region", "Note"])
    expect(page.get_by_test_id("property-list")).to_contain_text("Alpha site")


def test_only_the_first_object_of_a_larger_set_is_shown(page, api) -> None:
    """p.265: "If the object set contains more than one object, only the first
    object will be displayed within the widget"."""
    mod = build(api, "Property list first only")
    open_module(page, mod)
    settled(page)

    expect(rows(page)).to_have_count(4)
    expect(page.get_by_test_id("property-list")).to_contain_text("Alpha site")
    expect(page.get_by_test_id("property-list")).not_to_contain_text("Bravo site")


def test_the_chosen_properties_are_shown_in_the_chosen_order(page, api) -> None:
    mod = one(api, "Property list chosen", {"properties": "region,name"})
    open_module(page, mod)
    settled(page)

    expect_labels(page, ["Region", "Name"])


def test_a_property_that_no_longer_exists_is_dropped(page, api) -> None:
    """A property can be removed from the object type long after a widget was
    pointed at it. A blank row labelled with a name nobody recognises is worse
    than no row."""
    mod = one(api, "Property list stale name", {"properties": "name,gone,region"})
    open_module(page, mod)
    settled(page)

    expect_labels(page, ["Name", "Region"])


def test_null_properties_can_be_hidden(page, api) -> None:
    """p.266's toggle. S1's `note` is blank, which counts: a blank CSV column
    arrives as `""` rather than as `null`, and hiding one while keeping the
    other would look arbitrary to somebody who cannot see which the store
    holds."""
    shown = one(api, "Property list nulls shown")
    open_module(page, shown)
    settled(page)
    expect_labels(page, ["Id", "Name", "Region", "Note"])

    hidden = one(api, "Property list nulls hidden", {"hideNull": True})
    open_module(page, hidden)
    settled(page)
    # Three rather than four, and the missing one is the blank `note`.
    expect_labels(page, ["Id", "Name", "Region"])


def test_the_layout_moves_the_value_under_its_label(page, api) -> None:
    """p.265's Layout: "adjacent to their corresponding property type labels or
    below". Asserted by *position*, because a class that no rule matches passes
    every other kind of check."""
    beside = one(api, "Property list adjacent", {"layout": "adjacent"})
    open_module(page, beside)
    settled(page)
    expect(rows(page).first).to_be_visible()
    side_by_side = rows(page).first.evaluate(
        "e => e.querySelector('dd').getBoundingClientRect().left"
        " - e.querySelector('dt').getBoundingClientRect().left"
    )
    assert side_by_side > 10, side_by_side

    under = one(api, "Property list below", {"layout": "below"})
    open_module(page, under)
    settled(page)
    expect(rows(page).first).to_be_visible()
    stacked = rows(page).first.evaluate(
        "e => e.querySelector('dd').getBoundingClientRect().left"
        " - e.querySelector('dt').getBoundingClientRect().left"
    )
    assert abs(stacked) < 2, stacked


def test_more_columns_put_properties_side_by_side(page, api) -> None:
    """p.266's column count, asserted as a measurement: two properties that
    share a row are the whole point of the setting."""
    single = one(api, "Property list one column", {"columns": 1})
    open_module(page, single)
    settled(page)
    expect(rows(page).first).to_be_visible()
    assert same_row(page) is False

    double = one(api, "Property list two columns", {"columns": 2})
    open_module(page, double)
    settled(page)
    expect(rows(page).first).to_be_visible()
    assert same_row(page) is True


def same_row(page) -> bool:
    tops = [rows(page).nth(i).evaluate("e => e.getBoundingClientRect().top")
            for i in range(2)]
    return abs(tops[0] - tops[1]) < 2


def test_an_empty_set_says_so_rather_than_drawing_an_empty_list(page, api) -> None:
    """A list of no properties and a list of an object that is not there look
    identical, and only one of them is worth an author's attention."""
    mod = build(api, "Property list empty",
                filters=[{"property": "region", "op": "eq", "value": "nowhere"}])
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("property-list-empty")).to_be_visible()
    expect(page.get_by_test_id("property-list")).to_have_count(0)


def test_the_panel_names_the_properties_that_exist(page, api) -> None:
    """The list is free text, so the panel has to say what is available — an
    author naming a property that silently never appears is the failure the
    model drops the row for."""
    mod = one(api, "Property list panel")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Property list").first.click()
    hint = page.get_by_test_id("property-list-properties").locator("xpath=..")
    expect(hint).to_contain_text("region")
    expect(hint).to_contain_text("note")
