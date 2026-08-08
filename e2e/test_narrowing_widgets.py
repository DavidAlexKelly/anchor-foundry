"""Chart drill-down, the Card List and Search (roadmap 1.5, `STATUS.md` §101–§103).

Three widgets in one module, because the claim that matters spans them: they
all narrow the same object set, none of them *holds* one, and they **compose**
rather than compete. Each writes equality clauses into its own `array`
variable, and a chain of `narrow_set` derivations the server resolves does the
narrowing — so what the table shows and what the chart claims cannot disagree.

The variable graph is the test:

    v_all      (object_set)   the whole set
    v_clauses  (array)        what the chart writes when a bar is clicked
    v_drilled  (object_set)   narrow_set(v_all, v_clauses)
    v_search   (array)        what the search box writes
    v_narrow   (object_set)   narrow_set(v_drilled, v_search)

**Two narrowing widgets, two clause variables, chained.** Sharing one would
make them overwrite each other and leave the set depending on which was touched
last — a bug nobody would report as a bug.
"""
from __future__ import annotations

import pytest

from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, no_console_errors, open_module, settled

# North is deliberately bigger than the card list's page size, so paging is
# reachable — and so is the rule that narrowing while on page 2 sends you back
# to page 1 rather than to an empty widget that claims rows.
COUNTS = {"north": 14, "south": 2, "east": 3}
TOTAL = sum(COUNTS.values())
CARDS_PER_PAGE = 12


@pytest.fixture(scope="module")
def module(api):
    rows = [
        {"id": f"{region[0].upper()}{i}", "region": region, "name": f"Site {region} {i}"}
        for region, count in COUNTS.items()
        for i in range(1, count + 1)
    ]
    built = Module(api, "Narrowing")
    type_id = built.object_type(
        columns=["id", "region", "name"], rows=rows, key="id", title="name"
    )
    built.define(
        {
            "format": 2,
            "layout": layout(
                {
                    "cht": {
                        "resolvedName": "CanvasChart",
                        "props": {
                            "kind": "bar", "title": "Sites by region",
                            "objectSetVariable": "v_all", "dimension": "region",
                            "drilldownVariable": "v_clauses", "aggregate": "count",
                        },
                    },
                    # The same chart with nothing to drill into. A chart that
                    # cannot narrow anything must be a picture: no affordance
                    # promising something that will not happen.
                    "plain": {
                        "resolvedName": "CanvasChart",
                        "props": {
                            "kind": "bar", "title": "Sites by region (no drill)",
                            "objectSetVariable": "v_all", "dimension": "region",
                            "aggregate": "count",
                        },
                    },
                    "srch": {
                        "resolvedName": "CanvasSearch",
                        "props": {
                            "objectSetVariable": "v_all", "variable": "v_search",
                            "property": "name", "label": "Find a site",
                        },
                    },
                    "tbl": {
                        "resolvedName": "CanvasObjectTable",
                        "props": {
                            "objectSetVariable": "v_narrow",
                            "columns": "id,region,name", "pageSize": 25,
                        },
                    },
                    # The card list reads the same narrowed set the table does,
                    # and its click sets the same variable a table row would —
                    # so the two are interchangeable rather than merely similar.
                    "cards": {
                        "resolvedName": "CanvasObjectCards",
                        "props": {
                            "objectSetVariable": "v_narrow", "fields": "region,name",
                            "pageSize": CARDS_PER_PAGE,
                        },
                    },
                    "plaincards": {
                        "resolvedName": "CanvasObjectCards",
                        "props": {
                            "objectSetVariable": "v_narrow", "fields": "region",
                            "pageSize": 50,
                        },
                    },
                    "txt": {
                        "resolvedName": "CanvasText",
                        "props": {"tag": "p", "text": "Picked: {{v_picked_name}}"},
                    },
                }
            ),
            "variables": {
                "v_all": {
                    "id": "v_all", "kind": "object_set", "label": "All sites",
                    "object_set": object_set(type_id),
                },
                "v_clauses": {"id": "v_clauses", "kind": "array", "label": "Drill-down"},
                "v_drilled": {
                    "id": "v_drilled", "kind": "object_set", "label": "Drilled",
                    "derivation": {"transform": "narrow_set", "inputs": ["v_all", "v_clauses"]},
                },
                "v_search": {"id": "v_search", "kind": "array", "label": "Search"},
                "v_narrow": {
                    "id": "v_narrow", "kind": "object_set", "label": "Narrowed",
                    "derivation": {
                        "transform": "narrow_set", "inputs": ["v_drilled", "v_search"]
                    },
                },
                "v_picked": {
                    "id": "v_picked", "kind": "single_object", "label": "Picked site"
                },
                "v_picked_name": {
                    "id": "v_picked_name", "kind": "string", "label": "Picked name",
                    "derivation": {
                        "transform": "object_property", "inputs": ["v_picked"],
                        "config": {"property": "name"},
                    },
                },
            },
            "events": {
                "e_card": {
                    "id": "e_card",
                    "trigger": {"node": "cards", "on": "row_select"},
                    "effects": [
                        {"type": "set_variable",
                         "config": {"variable": "v_picked", "from": "object"}}
                    ],
                }
            },
        }
    )
    return built


def table_locator(page):
    return page.locator(".canvas-block table tbody tr")


def table_rows(page) -> int:
    return table_locator(page).count()


def regions(page) -> list[str]:
    """Which regions the table is showing, read from whole rows rather than a
    column index — the table renders a key column ahead of the configured ones,
    so index 1 is not `region`."""
    rows = page.locator(".canvas-block table tbody tr")
    texts = [rows.nth(i).inner_text() for i in range(rows.count())]
    return sorted({r for r in COUNTS if any(r in text for text in texts)})


def bar(page, region: str):
    return page.locator(f"svg rect[aria-label='Filter to {region}']")


def cards(page):
    return page.locator(".canvas-cards").first.locator(".canvas-card")


# ---- the chart -------------------------------------------------------------
def test_a_bar_is_operable_and_says_what_it_would_do(page, module):
    open_module(page, module)
    bars = page.locator("svg rect[role='button']")
    expect(bars).to_have_count(len(COUNTS))
    assert (bars.first.get_attribute("aria-label") or "").startswith("Filter to ")
    expect(table_locator(page)).to_have_count(TOTAL)  # starts with the whole set
    assert not no_console_errors(page)


def test_a_chart_with_nothing_to_drill_into_is_a_picture(page, module):
    """An affordance that promises nothing is worse than no affordance.

    `.last`, not `.first`: `.canvas-block` matches ancestors too, and the
    container holding *both* charts also contains this text — which is how an
    earlier version of this read six bars instead of three.
    """
    open_module(page, module)
    # Presence before absence: `to_have_count(0)` is true of a page that has
    # not drawn yet, so the assertion below would be green before either chart
    # existed.
    expect(page.locator("svg rect[role='button']")).to_have_count(len(COUNTS))
    plain = page.locator(".canvas-block", has_text="Sites by region (no drill)").last
    assert plain.locator("svg rect").count() > 0
    expect(plain.locator("svg rect[role='button']")).to_have_count(0)


def test_clicking_a_bar_narrows_the_table_to_that_category(page, module):
    open_module(page, module)
    north = bar(page, "north")
    north.click()

    expect(table_locator(page)).to_have_count(COUNTS["north"])
    assert regions(page) == ["north"], "that category and nothing else"
    assert north.get_attribute("aria-pressed") == "true"
    # Dimmed rather than removed: the others are still the shape of the data.
    assert page.locator("svg rect[role='button']").count() == len(COUNTS)
    assert float(bar(page, "south").get_attribute("opacity") or "1") < 1
    assert "Drilled into region = north" in page.locator(".canvas-block").first.inner_text()


def test_drilling_switches_rather_than_stacks_and_can_be_undone(page, module):
    open_module(page, module)
    bar(page, "north").click()
    bar(page, "south").click()
    expect(table_locator(page)).to_have_count(COUNTS["south"])
    assert regions(page) == ["south"], "switched to south, not added to north"

    # Clicking what is already drilled into clears it. Without that there is no
    # way back out from inside the chart, and a filter you cannot remove is one
    # you have to remember you applied.
    bar(page, "south").click()
    expect(table_locator(page)).to_have_count(TOTAL)

    bar(page, "east").click()
    page.get_by_role("button", name="Clear").first.click()
    expect(table_locator(page)).to_have_count(TOTAL)


# ---- the card list ---------------------------------------------------------
def test_a_card_leads_with_the_title_property_and_still_shows_the_key(page, module):
    open_module(page, module)
    expect(cards(page)).to_have_count(min(TOTAL, CARDS_PER_PAGE))
    assert cards(page).first.locator("h4").inner_text().startswith("Site ")
    # The key is always shown, even when it is also the heading: it is what
    # identifies the object to every other part of the platform.
    assert cards(page).first.locator(".canvas-card-key").inner_text().strip() != ""


def test_a_card_list_with_nothing_wired_is_not_clickable(page, module):
    open_module(page, module)
    expect(cards(page)).to_have_count(min(TOTAL, CARDS_PER_PAGE))
    plain = page.locator(".canvas-cards").last.locator(".canvas-card")
    assert plain.count() > 0
    assert plain.first.get_attribute("role") is None


def test_narrowing_while_on_page_two_returns_to_the_first_page(page, module):
    """Otherwise the widget shows nothing while claiming a total that has rows,
    which reads as "the filter broke"."""
    open_module(page, module)
    expect(cards(page)).to_have_count(min(TOTAL, CARDS_PER_PAGE))
    first_heading = cards(page).first.locator("h4").inner_text()
    page.locator(".canvas-cards").first.locator("xpath=..").get_by_role(
        "button", name="Next"
    ).click()
    eventually(lambda: cards(page).first.locator("h4").inner_text(),
               lambda got: got != first_heading, what="the second page")

    bar(page, "east").click()
    expect(cards(page)).to_have_count(COUNTS["east"])
    assert cards(page).count() == table_rows(page), "and the table agrees"


def test_clicking_a_card_selects_that_object(page, module):
    open_module(page, module)
    expect(cards(page)).to_have_count(min(TOTAL, CARDS_PER_PAGE))
    picked = page.get_by_text("Picked:", exact=False).last
    before = picked.inner_text()
    heading = cards(page).first.locator("h4").inner_text()
    cards(page).first.click()

    after = eventually(lambda: picked.inner_text(), lambda got: got != before,
                       what="the picked object")
    assert heading in after, "and it is the object on the card"


# ---- search, and whether it composes ---------------------------------------
def test_search_narrows_what_is_already_narrowed(page, module):
    """Two narrowing widgets, chained through separate clause variables. If they
    shared one, the set would depend on which was touched last."""
    open_module(page, module)
    bar(page, "east").click()

    box = page.get_by_label("Find a site")
    box.fill("Site east 2")
    expect(table_locator(page)).to_have_count(1)
    # The drill-down is still in force.
    expect(page.locator(".canvas-block").first).to_contain_text("Drilled into region = east")
    assert cards(page).count() == table_rows(page), "the cards agree"


def test_search_matches_a_prefix_and_only_a_prefix(page, module):
    """Said on the widget, so it has to be true — and it is the server's
    decision showing through: a substring match uses no index on either store.

    **Three cases, because a prefix sits between two wrong answers.** An
    earlier version of this checked only the substring side, and a mutation
    that made the box an *equality* match sailed through it: "east 2" matches
    nothing either way, and "Site east 2" matches exactly one row either way.
    A partial prefix matching several rows is what separates the three.
    """
    open_module(page, module)
    box = page.get_by_label("Find a site")

    box.fill("east 2")
    expect(table_locator(page)).to_have_count(0)

    box.fill("Site east")
    expect(table_locator(page)).to_have_count(COUNTS["east"])

    box.fill("Site east 2")
    expect(table_locator(page)).to_have_count(1)


def test_an_empty_box_is_no_filter_not_a_filter_for_nothing(page, module):
    open_module(page, module)
    box = page.get_by_label("Find a site")
    box.fill("Site east")
    expect(table_locator(page)).to_have_count(COUNTS["east"])

    box.fill("")
    expect(table_locator(page)).to_have_count(TOTAL)
