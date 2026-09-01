"""p.325-330's Metric Card (parity `workshop.md` §10).

> "The Metric Card widget displays Workshop variable values in a configurable
> card-like interface. Typically, metric cards are used to highlight key figures
> in a Workshop module." (p.325)

> "**Value type**: Specifies whether the value to be displayed is a String or a
> Number… The value used to populate the metric must be backed by a Workshop
> variable of the corresponding type." (p.328)

The rules are `apps/web/src/components/canvas/metric-card.test.ts`,
mutation-tested without a browser: which aggregations exist, which properties
each may run over, and what a card shows for a number it does not have.

**What needs a browser is that the card shows the number the server computed** —
and, more sharply, that it shows *nothing* when the server has nothing. §226
made an aggregation over an empty set answer `null` rather than `0`, and this is
the widget where that matters most: a card is one large figure somebody reads at
a glance and believes, so a `0` in place of "no data" is the kind of wrong
nobody re-reads.

The widget had no browser tests before §229.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import open_builder, open_module, settled

# `capacity` is what the numeric aggregations run over; `region` is what a
# distinct count counts. The numbers are chosen so the six answers are six
# different values - a card showing the wrong aggregation would otherwise be
# indistinguishable from one showing the right one.
ROWS = [
    {"id": "S1", "region": "north", "capacity": 10},
    {"id": "S2", "region": "north", "capacity": 20},
    {"id": "S3", "region": "south", "capacity": 60},
]
# count 3, count_distinct(region) 2, sum 90, avg 30, min 10, max 60.


@pytest.fixture(scope="module")
def sites(api):
    mod = Module(api, "Metric card")
    mod.site_type_id = mod.object_type(
        columns=["id", "region", "capacity"], rows=ROWS, key="id", title="id",
        types={"capacity": "integer"},
    )
    return mod


def build(api, sites, name: str, props: dict | None = None, *, empty: bool = False):
    """One card over the fixture, or over a set with nothing in it."""
    definition = object_set(
        sites.site_type_id,
        # A **legal** value that matches nothing, not an illegal one: `"nope"`
        # against an integer-mapped property is a query the store refuses, so it
        # would test the mapping rather than the empty answer.
        [{"property": "capacity", "op": "eq", "value": 999999}] if empty else None,
    )
    mod = Module(api, name, beside=sites)
    mod.define({
        "format": 2,
        "layout": layout({
            "card": {
                "resolvedName": "CanvasMetricCard",
                "props": {"objectSetVariable": "v_set", "aggregation": "count",
                          "property": None, "label": "Sites", **(props or {})},
            },
        }),
        "variables": {
            "v_set": {"id": "v_set", "kind": "object_set", "label": "The sites",
                      "object_set": definition},
        },
        "events": {},
    })
    return mod


def value(page):
    return page.get_by_test_id("metric-value")


# ---- the six aggregations ----------------------------------------------------
@pytest.mark.parametrize(
    "props, shown",
    [
        ({"aggregation": "count"}, "3"),
        ({"aggregation": "count_distinct", "property": "region"}, "2"),
        ({"aggregation": "sum", "property": "capacity"}, "90"),
        ({"aggregation": "avg", "property": "capacity"}, "30"),
        ({"aggregation": "min", "property": "capacity"}, "10"),
        ({"aggregation": "max", "property": "capacity"}, "60"),
    ],
    ids=["count", "count_distinct", "sum", "avg", "min", "max"],
)
def test_the_card_shows_the_aggregation_it_was_asked_for(
    page, api, sites, props, shown
) -> None:
    """**Six different numbers on purpose.** The fixture is arranged so no two
    aggregations agree, which is what makes each of these an assertion about
    *which* one ran rather than about the plumbing working at all.

    Four of the six were refused until §226, and this widget's own hint said so:
    "sums and averages need typed properties - see the ontology roadmap". True
    when written and untrue from §220.
    """
    mod = build(api, sites, f"Metric {props['aggregation']}", props)
    open_module(page, mod)
    settled(page)

    expect(value(page)).to_have_text(shown)


def test_an_aggregation_over_nothing_shows_nothing_rather_than_zero(
    page, api, sites
) -> None:
    """**The assertion this widget most needs.**

    §226 made a sum over an empty set answer `null`, because "total capacity: 0"
    and "there are no sites" are different facts that render identically. A
    Metric Card is exactly where that matters: one large figure, read at a
    glance, believed.
    """
    mod = build(api, sites, "Metric empty sum",
                {"aggregation": "sum", "property": "capacity"}, empty=True)
    open_module(page, mod)
    settled(page)

    expect(value(page)).to_have_text("—")


def test_a_count_over_nothing_is_still_zero(page, api, sites) -> None:
    """The other half of the same rule, and the one that stops the first being
    over-applied: "how many" always has an answer, and hiding a real zero would
    be its own lie."""
    mod = build(api, sites, "Metric empty count", {"aggregation": "count"}, empty=True)
    open_module(page, mod)
    settled(page)

    expect(value(page)).to_have_text("0")


def test_an_unfinished_setting_shows_no_number_and_no_error(page, api, sites) -> None:
    """A `sum` with no property yet is a panel somebody is halfway through. The
    server refuses it with a sentence about property types, and putting that on
    a card would report an author's unfinished setting as a failure of the
    data."""
    mod = build(api, sites, "Metric unset", {"aggregation": "sum"})
    open_module(page, mod)
    settled(page)

    # **Asserted on which state the card is in, not on the wording of an error
    # it must not show.** Naming the server's sentence would pass the moment
    # that sentence changed, which is a test of the message rather than of the
    # request that was never made.
    expect(page.get_by_test_id("metric-error")).to_have_count(0)
    expect(page.get_by_test_id("metric-value")).to_have_count(0)
    expect(page.get_by_test_id("metric-pending")).to_be_visible()


def test_a_document_naming_an_aggregation_this_platform_has_not_got_still_counts(
    page, api, sites
) -> None:
    """**The widget reads its own configuration before sending it** (§223).

    A document can hold anything - a hand-edit, a paste, the raw JSON tab, or a
    module written against a Foundry page listing an aggregation this platform
    does not answer. Sent on, `median` comes back as a 422 and the card shows an
    error where a number should be; read first, it falls back to counting, which
    is the answer that is never wrong.

    This is the only case that separates sending the props from sending what was
    read from them: every *legal* setting is identical either way.
    """
    mod = build(api, sites, "Metric unknown agg", {"aggregation": "median"})
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("metric-error")).to_have_count(0)
    expect(value(page)).to_have_text("3")


# ---- the panel ---------------------------------------------------------------
def test_the_panel_offers_all_six(page, api, sites) -> None:
    mod = build(api, sites, "Metric panel")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Metric card").first.click()
    assert page.get_by_test_id("metric-aggregation").locator("option").all_text_contents() == [
        "How many", "How many distinct values", "Sum of", "Average of",
        "Minimum of", "Maximum of",
    ]


def test_the_property_picker_narrows_for_arithmetic(page, api, sites) -> None:
    """**Two different lists, and this is the assertion that they are two.**

    A distinct count is a text-identity question and works on any property; the
    numeric four are arithmetic and the server takes only an integer or a float.
    Offering `region` to a `sum` would produce a sentence about arithmetic in
    place of a number.
    """
    mod = build(api, sites, "Metric panel property")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Metric card").first.click()
    # A plain count needs none at all.
    expect(page.get_by_test_id("metric-property")).to_have_count(0)

    page.get_by_test_id("metric-aggregation").select_option("count_distinct")
    assert page.get_by_test_id("metric-property").locator("option").all_text_contents() == [
        "Choose…", "id", "region", "capacity",
    ]

    page.get_by_test_id("metric-aggregation").select_option("sum")
    assert page.get_by_test_id("metric-property").locator("option").all_text_contents() == [
        "Choose…", "capacity",
    ]
