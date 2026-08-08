"""The Pivot Table (roadmap 1.5, `STATUS.md` §105).

Counts by two properties at once, with clicking a cell narrowing the table
beside it. What the API tests cannot see, and these can: whether the grid a
viewer reads is the grid the server computed, whether a click on a number
reaches the widget listening for it, and whether the two sentences the widget
owes a viewer are actually on screen.

Locator note that cost real time the first time: `.canvas-block` matches
*ancestors*, so a container holding two widgets "has_text" both their titles.
Everything here is scoped to `table.canvas-pivot` and picked by index.
"""
from __future__ import annotations

import pytest

from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, no_console_errors, open_module, settled

# No ties on either axis, so "biggest first" has one right answer and a wrong
# order is a failed assertion rather than a coin toss.
GRID = {
    "north": {"open": 5, "closed": 3, "pending": 1},
    "south": {"open": 4, "closed": 1},
    "east": {"open": 2},
}
ROW_ORDER = ["north", "south", "east"]
COLUMN_ORDER = ["open", "closed", "pending"]
TOTAL = sum(sum(v.values()) for v in GRID.values())
# `MAX_PIVOT_COLUMNS` in services/object_sets.py. Repeated rather than imported
# because these tests talk to the API over HTTP like any other client, and a
# client that imported the server's constants could not notice it changing.
COLUMN_CAP = 12


@pytest.fixture(scope="module")
def module(api):
    rows = []
    index = 0
    for region, statuses in GRID.items():
        for status, count in statuses.items():
            for _ in range(count):
                rows.append(
                    # `code` is unique per row: 16 distinct values against a cap
                    # of 12, so the second grid has to report both truncation
                    # and what its cells leave out.
                    {"id": f"S{index:02d}", "region": region, "status": status,
                     "code": f"C{index:02d}", "name": f"Site {index:02d}"}
                )
                index += 1
    built = Module(api, "Pivot")
    type_id = built.object_type(
        columns=["id", "region", "status", "code", "name"], rows=rows, key="id", title="name"
    )
    built.define(
        {
            "format": 2,
            "layout": layout(
                {
                    "pv": {
                        "resolvedName": "CanvasPivotTable",
                        "props": {
                            "title": "By region and status",
                            "objectSetVariable": "v_all",
                            "rowProperty": "region",
                            "columnProperty": "status",
                            "drilldownVariable": "v_clauses",
                        },
                    },
                    # A second grid with nothing wired to it, and with a column
                    # axis wider than the cap - so "a report is not clickable"
                    # and both honesty notes are checkable in one place.
                    "pv2": {
                        "resolvedName": "CanvasPivotTable",
                        "props": {
                            "title": "By region and code",
                            "objectSetVariable": "v_all",
                            "rowProperty": "region",
                            "columnProperty": "code",
                        },
                    },
                    "tbl": {
                        "resolvedName": "CanvasObjectTable",
                        "props": {
                            "objectSetVariable": "v_narrow",
                            "columns": "id,region,status",
                            "pageSize": 50,
                        },
                    },
                }
            ),
            "variables": {
                "v_all": {
                    "id": "v_all", "kind": "object_set", "label": "All sites",
                    "object_set": object_set(type_id),
                },
                "v_clauses": {"id": "v_clauses", "kind": "array", "label": "Pivot pick"},
                "v_narrow": {
                    "id": "v_narrow", "kind": "object_set", "label": "Narrowed",
                    "derivation": {"transform": "narrow_set", "inputs": ["v_all", "v_clauses"]},
                },
            },
            "events": {},
        }
    )
    return built


def pivot(page, index=0):
    return page.locator("table.canvas-pivot").nth(index)


def table_locator(page):
    return page.locator(".canvas-block table:not(.canvas-pivot) tbody tr")


def table_rows(page) -> int:
    return table_locator(page).count()


def cells(page, index=0) -> list[list[int]]:
    """The grid, without its margins: the last row is Total and the last column
    is Total, and both are asserted separately."""
    body = pivot(page, index).locator("tbody tr")
    return [
        [
            int(body.nth(r).locator("td").nth(c).inner_text().strip())
            for c in range(body.nth(r).locator("td").count() - 1)
        ]
        for r in range(body.count() - 1)
    ]


def test_the_grid_counts_both_properties_at_once(page, module):
    open_module(page, module)
    expected = [[GRID[r].get(c, 0) for c in COLUMN_ORDER] for r in ROW_ORDER]
    eventually(lambda: cells(page), lambda got: got == expected, what="the grid")

    heads = pivot(page).locator("thead th")
    assert [heads.nth(i + 1).inner_text().split()[0] for i in range(len(COLUMN_ORDER))] == (
        COLUMN_ORDER
    ), "columns biggest first"
    body_heads = pivot(page).locator("tbody tr th")
    assert [body_heads.nth(i).inner_text().split()[0] for i in range(len(ROW_ORDER))] == (
        ROW_ORDER
    ), "rows biggest first"
    assert not no_console_errors(page)


def test_the_margins_are_whole_rows_and_columns(page, module):
    """Not the sum of the drawn cells. Making them add up would look tidier and
    would disagree with a bar chart over the same property - which is the
    disagreement this widget lives inside."""
    open_module(page, module)
    last_column = pivot(page).locator("tbody tr td:last-child")
    eventually(
        lambda: [int(last_column.nth(i).inner_text()) for i in range(len(ROW_ORDER))],
        lambda got: got == [sum(GRID[r].values()) for r in ROW_ORDER],
        what="the total column",
    )
    total_row = pivot(page).locator("tbody tr").last.locator("td")
    assert [int(total_row.nth(i).inner_text()) for i in range(len(COLUMN_ORDER))] == [
        sum(g.get(c, 0) for g in GRID.values()) for c in COLUMN_ORDER
    ]
    assert int(total_row.last.inner_text()) == TOTAL


def test_clicking_a_cell_narrows_to_that_pair(page, module):
    open_module(page, module)
    expect(table_locator(page)).to_have_count(TOTAL)

    cell = page.get_by_role(
        "button", name="Filter to region = north, status = closed", exact=True
    )
    cell.click()
    expect(table_locator(page)).to_have_count(GRID["north"]["closed"])
    expect(cell).to_have_attribute("aria-pressed", "true")
    expect(pivot(page).locator("xpath=../..")).to_contain_text(
        "Narrowed to region = north and status = closed"
    )

    # Clicking what is already picked clears it: a filter you cannot remove
    # from inside the widget is one you have to remember you applied.
    cell.click()
    expect(table_locator(page)).to_have_count(TOTAL)


def test_a_heading_narrows_one_axis(page, module):
    open_module(page, module)
    expect(table_locator(page)).to_have_count(TOTAL)

    page.get_by_role("button", name="Filter to region = south", exact=True).click()
    expect(table_locator(page)).to_have_count(sum(GRID["south"].values()))

    page.get_by_role("button", name="Filter to status = open", exact=True).click()
    # The other axis replaces rather than stacks.
    expect(table_locator(page)).to_have_count(sum(g.get("open", 0) for g in GRID.values()))

    page.get_by_role("button", name="Clear").first.click()
    expect(table_locator(page)).to_have_count(TOTAL)


def test_nothing_promises_an_interaction_it_will_not_perform(page, module):
    """An empty cell narrows to nothing, which is something a viewer does by
    accident and never on purpose; and a grid with no variable wired to it has
    nowhere to write."""
    open_module(page, module)
    # **Presence before absence.** `to_have_count(0)` passes instantly on a page
    # that has not drawn yet, so both checks below would be green before the
    # grids existed. Waiting for a cell that *should* be a button first makes
    # the absences mean something.
    expect(page.get_by_role(
        "button", name="Filter to region = north, status = closed", exact=True
    )).to_be_visible()
    expect(page.get_by_role(
        "button", name="Filter to region = east, status = pending", exact=True
    )).to_have_count(0), "an empty cell is not a click target"

    report = pivot(page, 1)
    settled(page, report)
    assert report.locator("tbody tr").count() > 0
    expect(report.locator("button")).to_have_count(0)  # an unwired grid is a picture


def test_a_capped_grid_says_so_and_says_what_it_leaves_out(page, module):
    open_module(page, module)
    report = pivot(page, 1)
    # corner + columns + Total
    expect(report.locator("thead th")).to_have_count(COLUMN_CAP + 2)

    note = report.locator("xpath=../..")
    expect(note).to_contain_text(f"largest {COLUMN_CAP} of {TOTAL} code values")
    expect(note).to_contain_text(f"{TOTAL - COLUMN_CAP} of {TOTAL} are outside the grid")

    # And the margins are still whole rows here, where the cells provably
    # cannot add up - the uncapped grid cannot tell those two apart.
    shown = report.locator("tbody tr td:last-child")
    assert [int(shown.nth(i).inner_text()) for i in range(len(ROW_ORDER))] == [
        sum(GRID[r].values()) for r in ROW_ORDER
    ]
    assert [sum(row) for row in cells(page, 1)] != [sum(GRID[r].values()) for r in ROW_ORDER]
