"""p.250's Selectable render hint, read where a set is grouped (§727;
`object-link-types` p.250).

> "Selectable - Enable on string properties to allow users to perform
> aggregations on this property. For example, this property will be
> aggregated in Object Explorer histograms and Object View charts. Enable on
> numeric and date properties to allow users to perform aggregation on exact
> term values and not only distributions." (p.250)

That every group, a pivot's two axes and a union's parts refuse it is
`test_render_hints.py` (API). What needs a browser is a chart saying which
property and why rather than "couldn't", and its panel not offering the
property in the first place.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import open_builder, open_module, settled

ROWS = [
    {"id": "G1", "status": "open", "region": "north"},
    {"id": "G2", "status": "closed", "region": "south"},
]


@pytest.fixture(scope="module")
def gauges(api):
    mod = Module(api, "Selectable hint")
    mod.object_type_id = mod.object_type(
        columns=["id", "status", "region"], rows=ROWS, key="id", title="id",
        hints={"region": ["searchable"]},
    )
    return mod


def pie(api, gauges, name: str, group_by: str) -> Module:
    mod = Module(api, name, beside=gauges)
    mod.define({
        "format": 2,
        "layout": layout({
            "pie": {"resolvedName": "CanvasPieChart",
                    "props": {"objectSetVariable": "v_set", "groupBy": group_by}},
        }),
        "variables": {"v_set": {"id": "v_set", "kind": "object_set", "label": "Gauges",
                                "object_set": object_set(gauges.object_type_id)}},
        "events": {},
    })
    return mod


def test_a_pie_says_which_property_is_not_selectable(page, api, gauges) -> None:
    open_module(page, pie(api, gauges, "Selectable pie refused", "region"))
    settled(page)
    expect(page.get_by_test_id("pie-error")).to_contain_text(
        "region is not Selectable", timeout=30000)
    # The same pie over a property that is draws.
    open_module(page, pie(api, gauges, "Selectable pie drawn", "status"))
    settled(page)
    expect(page.get_by_test_id("pie-chart")).to_be_visible(timeout=30000)


def test_the_pie_s_panel_does_not_offer_it(page, api, gauges) -> None:
    mod = pie(api, gauges, "Selectable pie panel", "status")
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row").filter(has_text="Pie chart").first.click()
    choice = page.get_by_test_id("pie-group-by")
    expect(choice.locator("option")).to_have_text(["Choose…", "Id", "Status"])


def test_the_pivot_s_panel_offers_neither_axis_it(page, api, gauges) -> None:
    """A pivot's rows and columns are each a group (the server refuses either
    axis), so neither picker offers a property that is not Selectable."""
    mod = Module(api, "Selectable pivot panel", beside=gauges)
    mod.define({
        "format": 2,
        "layout": layout({
            "pv": {"resolvedName": "CanvasPivotTable",
                   "props": {"title": "Gauges", "objectSetVariable": "v_set",
                             "rowProperty": None, "columnProperty": None}},
        }),
        "variables": {"v_set": {"id": "v_set", "kind": "object_set", "label": "Gauges",
                                "object_set": object_set(gauges.object_type_id)}},
        "events": {},
    })
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row").filter(has_text="Pivot").first.click()
    expect(page.get_by_label("Rows").locator("option")).to_have_text(["Choose…", "id", "status"])
    expect(page.get_by_label("Columns").locator("option")).to_have_text(
        ["Choose…", "id", "status"])
