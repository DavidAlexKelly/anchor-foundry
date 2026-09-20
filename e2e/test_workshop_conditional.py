"""Conditional formatting *inside a Workshop module* (parity `workshop.md` §9;
Foundry workshop p.175, and p.329's Metric Card example).

> "Conditional formatting applies rules to determine how **numbers and
> sparklines** are styled. In Workshop, conditional formatting can be used to
> style time series property columns in the Object Table widget and time series
> property displays in the Metric Card widget. This formatting is local to the
> Workshop module, and not global to the ontology." (p.175)

> "Conditional formatting: This optional configuration allows the user to apply
> rule-based formatting to the metric value displayed, as in the example below
> that displays the metric in red if its value is less than or equal to zero,
> and in green otherwise." (p.329)

The rule grammar is §158's and is tested in `lib/conditional-format.test.ts`;
which stored lists are refused, and what the subject is, is
`conditional-formats.test.ts`. What needs a browser is what neither can see:

* that a rule reaches **both marks** — p.175's "the summarized value *and* the
  sparkline" is one rule painting two things, and a check on the number alone
  passes against a widget that never styles the line;
* that the match happens **per row**, not once for the column;
* that §158's dialog, reused inside a Workshop panel, writes rules a reader
  then sees.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, save, settled

SENSORS = b"id,name\nS1,North sensor\nS2,South sensor\n"
# **Opposite signs, on purpose.** p.329's example is "red at or below zero,
# green otherwise", so a fixture where both rows land on the same side of the
# threshold would pass against a column painted once from the first row.
READINGS = (
    b"sensor_id,taken_at,reading\n"
    b"S1,2026-01-01T00:00:00,20\n"
    b"S1,2026-01-02T00:00:00,40\n"
    b"S2,2026-01-01T00:00:00,-5\n"
    b"S2,2026-01-02T00:00:00,-12\n"
)
RED = "#cc0000"
GREEN = "#00aa00"
RED_RGB = "rgb(204, 0, 0)"
GREEN_RGB = "rgb(0, 170, 0)"

#: p.329's example as stored rules. First match wins, so the threshold rule is
#: first and the Always-true fallback last — which is the only order the server
#: and `rulesOf` accept.
BY_SIGN = [
    {"kind": "standard", "property": "latest value",
     "comparison": "numeric_range", "max": 0, "colour": RED},
    {"kind": "always", "colour": GREEN},
]


def build(api, name: str, *, table_props=None, card_props=None):
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
                     "props": {"objectSetVariable": "v_all", "aggregation": "count",
                               "label": "Sensors", **(card_props or {})}},
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


def colour_of(locator) -> str:
    """The *computed* colour, not the attribute.

    An inline `style` attribute proves a string was written; a computed colour
    proves the browser is painting with it. They differ whenever the value is
    one the browser will not accept.
    """
    return locator.evaluate("el => getComputedStyle(el).color")


def stroke_of(locator) -> str:
    return locator.evaluate("el => getComputedStyle(el).stroke")


def drawn(row) -> None:
    """Wait for the row's *reading*, not for the row.

    **The element is not the wait.** `series-latest` exists as soon as the row
    does: it renders empty while the series read is in flight and `—` when the
    series has no readings, and the paint is computed from those same points -
    so a colour read after waiting only for the element is a colour read one
    frame early, and the colour it reads is the unpainted one. That is exactly
    how this file first failed, under a full-file run and not in isolation.
    """
    eventually(lambda: row.get_by_test_id("series-latest").inner_text().strip(),
               lambda t: t not in ("", "—"), what="the row's latest reading")


def wait_colour(locator, expected: str, *, what: str) -> None:
    eventually(lambda: colour_of(locator), lambda c: c == expected, what=what)


def wait_stroke(locator, expected: str, *, what: str) -> None:
    eventually(lambda: stroke_of(locator), lambda c: c == expected, what=what)


@pytest.fixture(scope="module")
def painted(api):
    return build(api, "Workshop rules column",
                 table_props={"seriesRules": {"readings": BY_SIGN}})


def test_a_rule_paints_the_number_and_the_sparkline_together(page, painted):
    """p.175's whole sentence: *"how numbers **and sparklines** are styled"*,
    and *"the summarized value and the sparkline"*.

    **Both marks, from one rule.** A check on the number alone passes against a
    widget that drops the colour before it reaches the line — which is exactly
    what this widget did before §405, since the stroke came from a stylesheet.
    """
    open_module(page, painted)
    south = row_for(page, "South sensor")
    drawn(south)

    wait_colour(south.get_by_test_id("series-latest"), RED_RGB,
                what="the number painted by the threshold rule")
    wait_stroke(south.locator("path"), RED_RGB,
                what="the sparkline painted by the same rule")


def test_each_row_is_matched_on_its_own_value(page, painted):
    """The claim a one-row fixture cannot make.

    South's latest reading is `-12` and North's is `40`, so p.329's rule puts
    them on opposite sides of zero. A column painted once — from the first row,
    or from the whole page — would make these two assertions agree, and one of
    them would be wrong without ever failing.
    """
    open_module(page, painted)
    north = row_for(page, "North sensor")
    south = row_for(page, "South sensor")
    drawn(north)
    drawn(south)

    wait_colour(north.get_by_test_id("series-latest"), GREEN_RGB,
                what="the row above the threshold")
    wait_colour(south.get_by_test_id("series-latest"), RED_RGB,
                what="the row below it")
    wait_stroke(north.locator("path"), GREEN_RGB, what="the green sparkline")
    wait_stroke(south.locator("path"), RED_RGB, what="the red sparkline")


def test_an_unpainted_column_keeps_the_theme(page, api):
    """A module with no rules is the state every existing table is in, and the
    line must still follow `var(--accent)` rather than being resolved to a
    literal at render time. Asserted as *not either rule colour*, because the
    accent is a theme value this test has no business pinning."""
    mod = build(api, "Workshop rules none")
    open_module(page, mod)
    north = row_for(page, "North sensor")
    # §318: the negative assertions below only mean something once there is a
    # painted-or-not number to read. Before that they pass against a blank.
    drawn(north)
    assert colour_of(north.get_by_test_id("series-latest")) not in (RED_RGB, GREEN_RGB)
    assert stroke_of(north.locator("path")) not in (RED_RGB, GREEN_RGB)
    # And nothing inline, which is what "the stylesheet still decides" means.
    assert not (north.locator("path").get_attribute("style") or "")


def test_a_list_that_could_not_evaluate_paints_nothing(page, api):
    """§212, and the ordering rule that makes it matter here.

    p.105's Always-true rule is a *fallback*, and every rule after one is
    unreachable — so a document holding a misplaced one would paint the whole
    column the fallback's colour while the panel showed two rules. Refused
    whole, the column is the unpainted one it was.
    """
    mod = build(api, "Workshop rules junk", table_props={
        # The fallback first, which the server refuses and the raw JSON editor
        # does not.
        "seriesRules": {"readings": [{"kind": "always", "colour": GREEN},
                                     {"kind": "standard", "property": "latest value",
                                      "comparison": "numeric_range", "max": 0,
                                      "colour": RED}]},
    })
    open_module(page, mod)
    north = row_for(page, "North sensor")
    drawn(north)
    assert colour_of(north.get_by_test_id("series-latest")) not in (RED_RGB, GREEN_RGB)


def test_the_metric_card_paints_its_number_and_its_line(page, api):
    """p.329's own example, on p.329's own widget.

    The card's rules read the **metric**, not the sparkline's last point: the
    line beside it is the history of a different number entirely, and a rule
    that read it would colour the metric by something the metric does not show.
    Here the count is 2 and the threshold is 5, so a rule reading the series
    (whose latest values are 40 and -12) could not land on the same answer.
    """
    mod = build(api, "Workshop rules card", card_props={
        "valueRules": [
            {"kind": "standard", "property": "metric value",
             "comparison": "numeric_range", "max": 5, "colour": RED},
            {"kind": "always", "colour": GREEN},
        ],
        "showVisualization": False,
    })
    open_module(page, mod)
    expect(page.get_by_test_id("metric-value")).to_have_text("2")
    wait_colour(page.get_by_test_id("metric-value"), RED_RGB,
                what="the metric painted by its own rule")


def test_setting_a_rule_in_the_panel_reaches_the_cell(page, api):
    """The chain, and the reason this file needs a browser: §158's dialog,
    reused inside a Workshop settings panel, writing rules a reader then sees.
    """
    mod = build(api, "Workshop rules panel")
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row").filter(has_text="Object table").first.click()
    button = page.get_by_test_id("series-rules-readings")
    eventually(lambda: button.count(), lambda n: n == 1, what="the rules control")
    # The count, which is what an author of an ordered list keeps track of.
    expect(button).to_have_text("No rules")

    button.click()
    page.get_by_test_id("rule-add").click()
    # The default rule is `is_null`; p.329's example is a threshold.
    page.get_by_test_id("rule-1-comparison").select_option("numeric_range")
    page.get_by_test_id("rule-1-max").fill("0")
    page.get_by_test_id("rule-1-colour").fill(RED)
    page.get_by_test_id("rule-save").click()
    expect(button).to_have_text("1 rule")

    save(page)
    open_module(page, mod)
    south = row_for(page, "South sensor")
    north = row_for(page, "North sensor")
    drawn(south)
    drawn(north)
    wait_colour(south.get_by_test_id("series-latest"), RED_RGB,
                what="the rule written in the panel reaching the cell")
    # One rule and no fallback, so the row above the threshold is left alone —
    # which is what makes "first match wins" visible rather than asserted.
    assert colour_of(north.get_by_test_id("series-latest")) != RED_RGB
