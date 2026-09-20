"""Value formatting *inside a Workshop module* (parity `workshop.md` §9;
Foundry workshop p.174, and p.328's "Numeric formatting" which points at it).

> "In Workshop, value formatting can be used to render values when setting up
> **time series property columns in the Object Table widget** and **time series
> property displays in the Metric Card widget**. This formatting is local to
> the Workshop module, and not global to the ontology." (p.174)

> "Numeric formatting: … The user can specify a value formatting scheme to
> display the numeric value of the variable, including how many decimal places
> to display. To limit the decimals shown for a metric, set the max value in
> the Fraction digits field; values with more decimals are rounded to that
> length. For example, setting the maximum fraction digits to 2 displays
> 3.14159 as 3.14." (p.328-329)

The formatter itself is §157's and is tested to death in
`apps/web/src/lib/value-format.test.ts`; which stored formatters are *refused*
is `value-formats.test.ts`. What needs a browser is the part neither can see:

* that the props actually reach the two surfaces p.174 names, rather than
  reaching the document and stopping there;
* that "local to the module, not global to the ontology" is true of the same
  property in two modules at once;
* that §157's dialog, reused inside a Workshop settings panel, writes a
  formatter a reader then sees.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, save, settled

SENSORS = b"id,name\nS1,North sensor\nS2,South sensor\n"
# Deliberately not round. A formatter is invisible over integers: `40` is `40`
# whatever the fraction digits say, so every assertion below would pass against
# a widget that ignored the prop entirely.
READINGS = (
    b"sensor_id,taken_at,reading\n"
    b"S1,2026-01-01T00:00:00,1000.5\n"
    b"S1,2026-01-02T00:00:00,1234.5678\n"
    b"S2,2026-01-01T00:00:00,900.25\n"
)
#: What the unformatted column shows, and the thing every formatted expectation
#: has to differ from.
PLAIN_LATEST = "1,234.568"


def build(api, name: str, *, table_props=None, card_props=None, second_table=None):
    """A sensor type with a `time_series` property, a table and a card.

    Built directly rather than through `Module.object_type` for the reason
    `test_series_column.py` gives: the primary key column has to be mapped to
    the series property *as well* as being the key.
    """
    mod = Module(api, name)
    sensors = mod.api.upload_csv(
        f"{mod.base}/datasets/upload", f"sensors_{mod.tag}", SENSORS,
    )
    points = mod.api.upload_csv(
        f"{mod.base}/datasets/upload", f"readings_{mod.tag}", READINGS,
    )
    declared = mod.api.call(
        "POST", f"/workspaces/{mod.workspace_id}/object-types",
        {
            "api_name": f"sensor_{mod.tag}",
            "display_name": f"Sensor {mod.tag}",
            "properties": [
                {"api_name": "name", "display_name": "Name", "data_type": "string"},
                {"api_name": "readings", "display_name": "Readings",
                 "data_type": "time_series"},
            ],
            "title_property": "name",
        },
    )
    type_id = declared["id"]
    source = mod.api.call(
        "POST", f"{mod.base}/object-type-sources",
        {
            "object_type_id": type_id, "dataset_id": sensors["id"],
            "primary_key_column": "id",
            "column_mappings": {"name": "name", "id": "readings"},
        },
    )
    mod.api.call(
        "PUT", f"{mod.base}/object-type-sources/{source['id']}/series",
        {
            "property_api_name": "readings", "dataset_id": points["id"],
            "key_column": "sensor_id", "timestamp_column": "taken_at",
            "value_column": "reading",
        },
    )
    mod.api.call("POST", f"{mod.base}/object-type-sources/{source['id']}/sync", {})

    mod.define({
        "format": 2,
        "layout": layout({
            "tbl": {"resolvedName": "CanvasObjectTable",
                    "props": {"objectSetVariable": "v_all",
                              "columns": "name,readings", "pageSize": 25,
                              **(table_props or {})}},
            "card": {"resolvedName": "CanvasMetricCard",
                     "props": {"objectSetVariable": "v_all", "aggregation": "avg",
                               "property": "capacity", "label": "Average",
                               **(card_props or {})}},
            # A second table over the *same* property, for the one claim that
            # needs two widgets alive at once. Omitted unless asked for, so
            # every other test still reads `table` without an index.
            **({"tbl2": {"resolvedName": "CanvasObjectTable",
                         "props": {"objectSetVariable": "v_all",
                                   "columns": "name,readings", "pageSize": 25,
                                   **second_table}}}
               if second_table is not None else {}),
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All sensors",
                      "object_set": object_set(type_id)},
        },
        "events": {},
    })
    return mod


def row_for(page, name: str):
    return page.locator("tr", has=page.get_by_text(name, exact=True))


def latest(page, name: str):
    return row_for(page, name).get_by_test_id("series-latest")


def latest_in(page, index: int, name: str):
    """The same cell, but in a named table rather than the only one."""
    return (page.locator("table").nth(index)
            .locator("tr", has=page.get_by_text(name, exact=True))
            .get_by_test_id("series-latest"))


@pytest.fixture(scope="module")
def plain(api):
    """No formatter anywhere — the baseline every formatted expectation is
    measured against."""
    return build(api, "Workshop formatting plain")


def test_an_unformatted_column_is_the_plain_localised_number(page, plain):
    """The baseline, asserted rather than assumed.

    Every test below claims a formatter *changed* something; that claim is only
    worth making if what it changed from is pinned. It also holds §404's own
    compatibility promise: the column looked like this before p.174's option
    existed and looks like this with the option unset.
    """
    open_module(page, plain)
    eventually(lambda: page.get_by_test_id("series-latest").count(),
               lambda n: n == 2, what="a latest value per row")
    expect(latest(page, "North sensor")).to_have_text(PLAIN_LATEST)


def test_a_module_formatter_writes_the_time_series_column(page, api):
    """p.174's first surface. The formatter is on the *widget*, keyed by the
    property it formats, and what it changes is the latest value in the cell.
    """
    mod = build(api, "Workshop formatting column", table_props={
        "seriesFormats": {
            "readings": {"kind": "number", "style": "currency", "currency": "USD",
                         "maximum_fraction_digits": 0},
        },
    })
    open_module(page, mod)
    eventually(lambda: page.get_by_test_id("series-latest").count(),
               lambda n: n == 2, what="a latest value per row")
    expect(latest(page, "North sensor")).to_have_text("$1,235")
    # **Every row, not the one the assertion happens to read.** A formatter
    # applied at the head of the page and forgotten under it is the shape of
    # bug a single-row check cannot see.
    expect(latest(page, "South sensor")).to_have_text("$900")


def test_the_formatter_belongs_to_the_widget_and_not_to_the_property(page, api):
    """p.174's "local to the Workshop module, and not global to the ontology" —
    made here in the only shape a browser can make *fail*.

    **This replaces a two-module version that could not fail, and the mutation
    sweep is how that was found.** That test opened module A, asserted its
    formatting, then opened module B and asserted plain numbers. Opening B is a
    `page.goto`, which tears down the JS context — so a mutant that cached
    formatters by property name across tables was wiped before B's assertion
    ever ran, and passed all seven tests untouched. The claim was true; the
    check could not have noticed it being false.

    Two tables on **one page**, over the **same property**, is the same claim
    where a leak survives long enough to be seen. It is also the stronger
    statement: the formatter belongs to the *widget*, which is what makes it
    local to a module rather than to the ontology behind both tables.
    """
    mod = build(
        api, "Workshop formatting local",
        table_props={"seriesFormats": {"readings": {
            "kind": "number", "style": "affix", "suffix": " kPa",
            "maximum_fraction_digits": 1}}},
        # Deliberately no formatter. Two formatters would prove they differ;
        # one and none proves the unformatted table stayed unformatted, which
        # is the direction a leak actually travels.
        second_table={},
    )
    open_module(page, mod)
    # Both tables, before either is read: an assertion about "the second table"
    # passes vacuously if only one rendered.
    eventually(lambda: page.locator("table").count(), lambda n: n == 2,
               what="both tables")
    eventually(lambda: page.get_by_test_id("series-latest").count(),
               lambda n: n == 4, what="a latest value per row in each table")

    expect(latest_in(page, 0, "North sensor")).to_have_text("1,234.6 kPa")
    expect(latest_in(page, 1, "North sensor")).to_have_text(PLAIN_LATEST)


def test_a_formatter_that_could_not_apply_leaves_the_plain_number(page, api):
    """§212: the raw JSON editor can hold anything, and so can a document from
    an older build.

    A `datetime` formatter on a number is the case worth pinning, because it is
    the one that does *not* throw: `formatValue` would parse `1234.5678` as a
    date, fail to, and hand the digits straight back — so the column would lose
    its thousands separator for a reason nobody could see. Dropped whole, the
    cell is the plain number it was.
    """
    mod = build(api, "Workshop formatting junk", table_props={
        "seriesFormats": {
            "readings": {"kind": "datetime", "style": "datetime_short"},
            # And a crossed pair, which `Intl` throws on outright.
            "name": {"kind": "number", "style": "plain",
                     "minimum_fraction_digits": 6, "maximum_fraction_digits": 2},
        },
    })
    open_module(page, mod)
    eventually(lambda: page.get_by_test_id("series-latest").count(),
               lambda n: n == 2, what="a latest value per row")
    expect(latest(page, "North sensor")).to_have_text(PLAIN_LATEST)


def test_the_metric_card_formats_its_number(page, api):
    """p.174's second surface, configured by p.328's Numeric formatting.

    The card's number is an aggregate **this widget computed**, not a stored
    property value — so there is no ontology formatter it could have inherited,
    which is p.174's sentence from the other side.
    """
    mod = build(api, "Workshop formatting card", card_props={
        "aggregation": "count",
        "property": None,
        "valueFormat": {"kind": "number", "style": "affix", "prefix": "≈",
                        "minimum_fraction_digits": 2},
    })
    open_module(page, mod)
    expect(page.get_by_test_id("metric-value")).to_have_text("≈2.00")


def test_the_panel_offers_a_format_only_for_time_series_columns(page, api):
    """p.174 scopes Workshop value formatting to time series columns. `name` is
    a string and is written by the ontology's formatter (§157); a second place
    to format it would be two settings for one thing."""
    mod = build(api, "Workshop formatting scope")
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row").filter(has_text="Object table").first.click()
    # Waited for: the property list arrives with the object type, and a
    # snapshot taken before that finds no controls for a reason that has
    # nothing to do with p.174 (§271).
    eventually(lambda: page.get_by_test_id("series-format-readings").count(),
               lambda n: n == 1, what="the time series column's format control")
    expect(page.get_by_test_id("series-format-name")).to_have_count(0)


def test_setting_a_format_in_the_panel_reaches_the_cell(page, api):
    """The whole chain, and the reason this file needs a browser at all: §157's
    dialog, reused inside a Workshop panel, writing a prop a reader then sees.

    p.328's own worked example is the setting driven here — "set the max value
    in the Fraction digits field; values with more decimals are rounded to that
    length".
    """
    mod = build(api, "Workshop formatting panel")
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row").filter(has_text="Object table").first.click()
    button = page.get_by_test_id("series-format-readings")
    eventually(lambda: button.count(), lambda n: n == 1, what="the format control")
    # **The button says there is nothing set**, which is the state the next
    # assertion has to differ from.
    expect(button).to_have_text("Not formatted")

    button.click()
    page.get_by_test_id("format-on").select_option("on")
    page.get_by_test_id("format-style").select_option("percent")
    page.get_by_test_id("format-save").click()
    # The panel now describes the formatter by what it does, not by its fields.
    expect(button).not_to_have_text("Not formatted")

    save(page)
    open_module(page, mod)
    eventually(lambda: page.get_by_test_id("series-latest").count(),
               lambda n: n == 2, what="a latest value per row")
    # `Intl`'s percent style multiplies by 100, which is exactly why this is
    # asserted against the rendered text rather than against the saved prop: a
    # formatter that reached the document and not the cell would pass a check
    # on the document.
    expect(latest(page, "North sensor")).to_have_text("123,457%")
