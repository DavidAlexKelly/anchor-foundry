"""The Time Series (roadmap 1.5, `STATUS.md` §106).

Counts over time buckets on an object set, over `updated_at`. Three things here
are only checkable in a browser: that a gap renders as zeros rather than a line
drawn through it, that a bucket's *label* is its own bucket in UTC, and that
the caption naming which question the chart answers is actually on screen.

That last one is not decoration. A line of counts over time reads as "when
these things happened", and this is "when the platform last saw them change" -
the same shape, a different claim.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from api import Module, layout, object_set
from conftest import ADMIN_DSN, no_console_errors, open_module

# Monday, so week boundaries are unambiguous. (day offset, how many, region)
ANCHOR = datetime(2024, 3, 4, 9, 0, tzinfo=timezone.utc)
PLAN = [
    (0, 3, "north"), (1, 2, "north"), (2, 1, "south"),
    # ... four silent days, which have to appear as zeros ...
    (7, 4, "north"), (9, 2, "south"),
    # ... and one in the next month, which only the month bucket merges.
    (28, 1, "east"),
]
ROWS = [
    {"id": f"S{i:02d}", "region": region, "offset": offset}
    for i, (offset, region) in enumerate(
        [(offset, region) for offset, count, region in PLAN for _ in range(count)]
    )
]
TOTAL = len(ROWS)

BY_DAY = {}
for row in ROWS:
    BY_DAY[row["offset"]] = BY_DAY.get(row["offset"], 0) + 1
FIRST_DAY, LAST_DAY = min(BY_DAY), max(BY_DAY)
DAY_POINTS = [BY_DAY.get(d, 0) for d in range(FIRST_DAY, LAST_DAY + 1)]
DAY_STARTS = [
    (ANCHOR.replace(hour=0) + timedelta(days=d)).isoformat()
    for d in range(FIRST_DAY, LAST_DAY + 1)
]
# 2024-03-04 .. 2024-04-01 spans five ISO weeks and two months.
WEEK_POINTS = [6, 6, 0, 0, 1]
MONTH_POINTS = [12, 1]

NORTH = [r for r in ROWS if r["region"] == "north"]
_NORTH_BY_DAY: dict[int, int] = {}
for row in NORTH:
    _NORTH_BY_DAY[row["offset"]] = _NORTH_BY_DAY.get(row["offset"], 0) + 1
NORTH_POINTS = [
    _NORTH_BY_DAY.get(d, 0) for d in range(min(_NORTH_BY_DAY), max(_NORTH_BY_DAY) + 1)
]

DAY, WEEK, MONTH, NORTH_SERIES = 0, 1, 2, 3


@pytest.fixture(scope="module")
def module(api):
    built = Module(api, "Series")
    type_id = built.object_type(
        columns=["id", "region", "name"],
        rows=[{**r, "name": f"Site {r['id']}"} for r in ROWS],
        key="id",
        title="name",
    )
    built.spread_updated_at(
        ADMIN_DSN, {r["id"]: ANCHOR + timedelta(days=r["offset"]) for r in ROWS}
    )
    built.define(
        {
            "format": 2,
            "layout": layout(
                {
                    name: {
                        "resolvedName": "CanvasTimeSeries",
                        "props": {
                            "objectSetVariable": variable,
                            "interval": interval,
                            "title": title,
                        },
                    }
                    for name, variable, interval, title in [
                        ("day", "v_all", "day", "By day"),
                        ("week", "v_all", "week", "By week"),
                        ("month", "v_all", "month", "By month"),
                        # A series over a narrowed set: the point of plotting a
                        # *set* is that a filter elsewhere moves this too.
                        ("north", "v_north", "day", "North by day"),
                    ]
                }
            ),
            "variables": {
                "v_all": {
                    "id": "v_all", "kind": "object_set", "label": "All",
                    "object_set": object_set(type_id),
                },
                "v_north": {
                    "id": "v_north", "kind": "object_set", "label": "North",
                    "object_set": object_set(
                        type_id, [{"property": "region", "op": "eq", "value": "north"}]
                    ),
                },
            },
            "events": {},
        }
    )
    return built


def block(page, index):
    return page.locator("svg[aria-label='Line chart']").nth(index).locator("xpath=..")


def titles(page, index) -> list[str]:
    """Each point's tooltip, as "<label>: <count>".

    `text_content`, not `inner_text`: an SVG `<title>` is not an HTMLElement and
    Playwright refuses it outright rather than returning something wrong, which
    is the good kind of failure.
    """
    return block(page, index).locator("svg circle title").evaluate_all(
        "nodes => nodes.map(n => n.textContent)"
    )


def counts(page, index) -> list[int]:
    return [int(t.split(": ")[-1]) for t in titles(page, index)]


def labels(page, index) -> list[str]:
    return [t.rsplit(": ", 1)[0] for t in titles(page, index)]


def test_each_bucket_size_is_a_different_picture_of_one_set(page, module):
    open_module(page, module)
    assert page.locator("svg[aria-label='Line chart']").count() == 4
    assert counts(page, DAY) == DAY_POINTS
    assert counts(page, WEEK) == WEEK_POINTS
    assert counts(page, MONTH) == MONTH_POINTS
    assert sum(counts(page, DAY)) == sum(counts(page, WEEK)) == sum(counts(page, MONTH)) == TOTAL
    assert not no_console_errors(page)


def test_a_silent_stretch_is_zeros_not_a_line_drawn_through_it(page, module):
    """Both stores return only populated buckets. A line sloping gently across
    a week when nothing happened is a different claim, not a smaller one."""
    open_module(page, module)
    assert counts(page, DAY)[3:7] == [0, 0, 0, 0]
    assert len(counts(page, DAY)) == len(DAY_POINTS)


def test_every_label_is_its_own_bucket_in_utc(page, module):
    """The reference is formatted by the same browser from the known bucket
    starts, pinned to UTC.

    Checking only the *shape* of a label - "looks like a date" - let a mutation
    that formatted in another time zone survive: a bucket starting 00:00 UTC
    still renders as a plausible date elsewhere, just the wrong one.
    """
    open_module(page, module)
    expected = page.evaluate(
        """(isos) => isos.map((iso) => new Intl.DateTimeFormat(undefined,
             { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(new Date(iso)))""",
        DAY_STARTS,
    )
    assert labels(page, DAY) == expected
    assert labels(page, WEEK)[0].startswith("w/c "), "a week is labelled as a week"
    assert not labels(page, DAY)[0].startswith("w/c ")
    assert labels(page, MONTH)[0].split()[-1] == "2024"


def test_the_caption_says_which_question_the_chart_answers(page, module):
    open_module(page, module)
    caption = block(page, DAY).inner_text()
    assert "When each object last changed" in caption
    assert "not a business date" in caption
    assert "UTC" in caption
    assert f"{TOTAL} objects" in caption


def test_a_series_over_a_narrowed_set_plots_the_narrowed_set(page, module):
    open_module(page, module)
    assert counts(page, NORTH_SERIES) == NORTH_POINTS
    assert sum(counts(page, NORTH_SERIES)) == len(NORTH) < TOTAL
