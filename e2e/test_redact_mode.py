"""Redact mode (§413; `workshop` p.614-615).

> "Redact mode visually obfuscates the visible content of a Workshop
> application so you can share the layout and structure of a module without
> exposing the underlying data." (p.614)

`redact.test.ts` decides when the mode is on and what the address looks like.
What needs a browser is everything else, because the whole feature *is*
rendering — p.614 says so: "redact mode only changes how the page renders."

And p.614's warning is the reason two of these tests exist:

> "Redact mode is a visual aid only and is not a security feature. Workshop
> still loads and processes the underlying data; redact mode only changes how
> the page renders."

A test that only checked the page looked hidden would be checking the thing
p.614 says not to believe. So one test reads the values straight back out of
the DOM and asserts they are **still there** — which is the honest claim, and
the one a reader has to be told before they share their screen.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, publish, settled, viewer_url

PARAM = "workshop_enableRedactMode=true"
ROWS = [
    {"id": "R1", "customer": "Northwind Traders", "revenue": "1200"},
    {"id": "R2", "customer": "Southridge Video", "revenue": "800"},
]


@pytest.fixture(scope="module")
def module_with_data(api):
    """A table of readable values and a chart drawn over them."""
    mod = Module(api, "Redact")
    type_id = mod.object_type(
        columns=["id", "customer", "revenue"], rows=ROWS, key="id", title="customer",
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "table": {"resolvedName": "CanvasObjectTable",
                      "props": {"objectSetVariable": "v_all", "title": "Customers"}},
            # A chart, because p.615 treats a plot area differently from text
            # and the difference is only visible on one.
            "chart": {"resolvedName": "CanvasChart",
                      "props": {"objectSetVariable": "v_all", "kind": "bar",
                                "dimension": "customer", "aggregate": "count",
                                "title": "By customer"}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All customers",
                      "object_set": object_set(type_id)},
        },
        "events": {},
    })
    publish(mod)
    return mod, type_id


def open_redacted(page, mod, on: bool = True):
    page.goto(f"{viewer_url(mod)}{'?' + PARAM if on else ''}")
    settled(page)
    eventually(lambda: page.locator("tbody tr").count(), lambda n: n == len(ROWS),
               what="the table's rows")


def test_the_page_renders_its_data_unreadably(page, module_with_data):
    """p.614's purpose. The shell carries the mode, so the obfuscation is one
    fact about the page rather than a property each widget has to remember."""
    mod, _ = module_with_data
    open_redacted(page, mod)
    expect(page.locator("[data-redact='on']")).to_have_count(1)
    # `color: transparent` is what makes every glyph unreadable, and it is the
    # one property a reader would notice going missing.
    colour = page.eval_on_selector(
        "[data-redact='on']", "el => getComputedStyle(el).color")
    assert "rgba(0, 0, 0, 0)" == colour, colour


def test_the_data_is_still_in_the_page(page, module_with_data):
    """**p.614's warning, as a test rather than as a sentence.**

    "Workshop still loads and processes the underlying data; redact mode only
    changes how the page renders." A suite that only asserted the page looked
    hidden would be asserting the belief p.614 exists to correct — and the day
    somebody decided to make redact mode "better" by withholding the data,
    nothing here would have objected to the module quietly breaking instead.
    """
    mod, _ = module_with_data
    open_redacted(page, mod)
    body = page.locator("tbody").inner_text()
    assert "Northwind Traders" in body, body
    assert "1200" in body, body


def test_the_warning_is_readable_while_everything_else_is_not(page, module_with_data):
    """The banner is exempt from the blur on purpose. A warning nobody can read
    is worse than no warning: a reader who cannot make it out concludes the
    page is protecting something, which is the exact belief it is there to
    prevent."""
    mod, _ = module_with_data
    open_redacted(page, mod)
    banner = page.get_by_test_id("redact-banner")
    expect(banner).to_be_visible()
    expect(banner).to_contain_text("not a security feature")
    colour = page.eval_on_selector(
        "[data-testid='redact-banner'] span", "el => getComputedStyle(el).color")
    assert colour != "rgba(0, 0, 0, 0)", colour


def test_a_chart_becomes_a_striped_area_rather_than_a_blank(page, module_with_data):
    """p.615: "replaces icons and chart plot areas with a diagonal striped
    background". Striped rather than empty, because an empty box where a chart
    was reads as a chart that failed to load — and somebody would go looking
    for the bug."""
    mod, _ = module_with_data
    open_redacted(page, mod)
    chart = page.locator("[data-redact='on'] svg").first
    expect(chart).to_be_visible()
    background = page.eval_on_selector(
        "[data-redact='on'] svg", "el => getComputedStyle(el).backgroundImage")
    assert "gradient" in background, background


def test_leaving_the_mode_restores_the_page(page, module_with_data):
    """The Exit link, and the proof that the mode is the parameter rather than
    a state the page fell into: the same address without it renders normally."""
    mod, _ = module_with_data
    open_redacted(page, mod)
    page.get_by_test_id("redact-exit").click()
    settled(page)
    expect(page.locator("[data-redact='on']")).to_have_count(0)
    expect(page.get_by_test_id("redact-banner")).to_have_count(0)
    assert PARAM.split("=")[0] not in page.url, page.url


def test_a_module_opened_without_the_parameter_is_not_redacted(page, module_with_data):
    """The negative that makes every assertion above a fact about the
    parameter. §318: this follows a positive wait, so it cannot pass merely by
    running before the page rendered."""
    mod, _ = module_with_data
    open_redacted(page, mod, on=False)
    expect(page.locator("tbody tr").first).to_be_visible()
    expect(page.locator("[data-redact='on']")).to_have_count(0)
    colour = page.eval_on_selector("main.page", "el => getComputedStyle(el).color")
    assert colour != "rgba(0, 0, 0, 0)", colour
