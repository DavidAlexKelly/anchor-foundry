"""p.463–464's Date and Time Picker (parity `workshop.md` §10; decision 0011).

> "**Selected timestamp**: Output variable of the widget… **Time precision**: …
> down to the millisecond, second, or minute. **Timezone user editable**: Toggle
> controlling whether or not the timezone of the widget is adjustable in view
> mode by the user. **Default timezone**: … set statically by manually selecting
> the timezone, dynamically using a variable, or set to **local** which uses the
> viewer's local timezone." (p.463–464)

Instants, offsets, DST and the round trip are checked in
`apps/web/src/components/canvas/date-time.test.ts` without a browser.

What needs one is what a pure function cannot see: that the control is wired to
the variable at all, that a timezone read from a **variable** arrives through a
server resolve, and — the rule this widget exists to keep — that **changing the
timezone changes what is displayed and never what is stored.**
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder, open_module, settled


def module_with(api, name: str, props: dict | None = None):
    """One picker, a mirror of the stored instant, and a clock.

    The mirror is the point: the *stored* value is an instant, and the control
    shows a wall clock in some zone. Reading the control back only ever confirms
    the control (§204).
    """
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({
            "dt": {"resolvedName": "CanvasDateTimePicker",
                   "props": {"name": "v_when", "label": "When",
                             "dateFormat": "iso", "timeFormat": "h24",
                             "precision": "minute", "zoneMode": "fixed",
                             "timezone": "UTC", "timezoneVariable": "",
                             "zoneEditable": False, **(props or {})}},
            "btn": {"resolvedName": "CanvasButton", "props": {"label": "Go"}},
            "echo": {"resolvedName": "CanvasText",
                     "props": {"tag": "p",
                               "text": "stored: [{{v_when}}] clock: {{v_clock}}"}},
        }),
        "variables": {
            "v_when": {"id": "v_when", "kind": "timestamp", "label": "When"},
            "v_zone": {"id": "v_zone", "kind": "string", "label": "Zone",
                       "default": "Asia/Kolkata"},
            "v_clock": {"id": "v_clock", "kind": "string", "label": "Clock", "default": "no"},
        },
        "events": {
            "e_go": {"id": "e_go", "trigger": {"node": "btn", "on": "click"},
                     "effects": [{"type": "set_variable",
                                  "config": {"variable": "v_clock", "value": "ticked"}}]},
        },
    })
    return mod


def field(page):
    return page.get_by_test_id("datetime-input")


def echo(page):
    return page.locator(".canvas-block", has_text="stored:").first


def test_picking_a_time_stores_an_instant(page, api) -> None:
    """The control shows a wall clock; the variable holds the instant. In UTC
    the two read the same, which is what makes this the baseline the zone tests
    are measured against."""
    mod = module_with(api, "Datetime basics")
    open_module(page, mod)
    settled(page)

    field(page).fill("2026-03-01T12:00")
    expect(echo(page)).to_contain_text("stored: [2026-03-01T12:00:00.000Z]")


def test_the_zone_changes_what_is_shown_and_not_what_is_stored(page, api) -> None:
    """**The rule this widget exists to keep**, and the inversion of p.468's
    percent suffix: the zone decides how the instant reads, never what it is.

    New York is five hours behind UTC on 1 March, so 07:00 there is the same
    instant as 12:00 UTC — and the variable holds exactly what the UTC picker
    above stored.
    """
    mod = module_with(api, "Datetime zone", {"timezone": "America/New_York"})
    open_module(page, mod)
    settled(page)

    field(page).fill("2026-03-01T07:00")
    expect(echo(page)).to_contain_text("stored: [2026-03-01T12:00:00.000Z]")
    # And the control still shows the wall clock it was given, not the instant.
    expect(field(page)).to_have_value("2026-03-01T07:00")


def test_a_half_hour_zone_round_trips(page, api) -> None:
    """Where an implementation holding offsets as whole hours falls over."""
    mod = module_with(api, "Datetime half hour", {"timezone": "Asia/Kolkata"})
    open_module(page, mod)
    settled(page)

    field(page).fill("2026-03-01T17:30")
    expect(echo(page)).to_contain_text("stored: [2026-03-01T12:00:00.000Z]")
    expect(field(page)).to_have_value("2026-03-01T17:30")


def test_the_hour_after_a_dst_change_is_the_right_instant(page, api) -> None:
    """New York springs forward at 02:00 local on 8 March 2026, so 03:00 local
    that morning is 07:00 UTC — which a single-pass offset lookup gets wrong,
    on the one day somebody is most likely to be picking that hour."""
    mod = module_with(api, "Datetime dst", {"timezone": "America/New_York"})
    open_module(page, mod)
    settled(page)

    field(page).fill("2026-03-08T03:00")
    expect(echo(page)).to_contain_text("stored: [2026-03-08T07:00:00.000Z]")


def test_the_precision_is_dropped_from_the_stored_instant(page, api) -> None:
    """p.464's Time precision. Not merely hidden: a value shown as 12:34 that is
    really 12:34:56 will not compare equal to the 12:34 somebody else picked."""
    mod = module_with(api, "Datetime precision", {"precision": "second"})
    open_module(page, mod)
    settled(page)

    field(page).fill("2026-03-01T12:34:56")
    expect(echo(page)).to_contain_text("stored: [2026-03-01T12:34:56.000Z]")


def test_the_precision_sets_the_controls_step(page, api) -> None:
    """Which is also what makes the browser show the seconds box at all."""
    mod = module_with(api, "Datetime step")
    open_module(page, mod)
    settled(page)
    expect(field(page)).to_have_attribute("step", "60")

    fine = module_with(api, "Datetime step fine", {"precision": "millisecond"})
    open_module(page, fine)
    settled(page)
    expect(field(page)).to_have_attribute("step", "0.001")


def test_clearing_the_field_stores_nothing(page, api) -> None:
    """Matching §202 and §203: a picker nobody has touched has no value."""
    mod = module_with(api, "Datetime clear")
    open_module(page, mod)
    settled(page)

    field(page).fill("2026-03-01T12:00")
    expect(echo(page)).to_contain_text("stored: [2026-03-01T12:00:00.000Z]")
    field(page).fill("")
    expect(echo(page)).to_contain_text("stored: []")


def test_the_zone_is_named_even_when_it_cannot_be_changed(page, api) -> None:
    """**Two viewers in different zones otherwise see different times in a field
    that looks identical**, and neither can tell why. The offset is included
    because the name alone does not say what time it is."""
    mod = module_with(api, "Datetime zone label", {"timezone": "America/New_York"})
    open_module(page, mod)
    settled(page)

    label = page.get_by_test_id("datetime-zone-label")
    expect(label).to_contain_text("America/New_York")
    expect(label).to_contain_text("GMT-")


def test_a_viewer_may_change_the_zone_without_moving_the_instant(page, api) -> None:
    """p.464's "Timezone user editable". The displayed wall clock moves; the
    stored instant does not — which is the whole claim, and the reason the
    mirror is in the module."""
    mod = module_with(api, "Datetime editable zone", {
        "timezone": "UTC", "zoneEditable": True,
    })
    open_module(page, mod)
    settled(page)

    field(page).fill("2026-03-01T12:00")
    expect(echo(page)).to_contain_text("stored: [2026-03-01T12:00:00.000Z]")

    page.get_by_test_id("datetime-zone").select_option("America/New_York")
    expect(field(page)).to_have_value("2026-03-01T07:00")
    # **Unchanged**, and asserted after a full write-and-resolve cycle so this
    # is a claim about what happened rather than about how fast the assertion
    # ran (§202, §203).
    page.get_by_role("button", name="Go", exact=True).click()
    expect(echo(page)).to_contain_text("clock: ticked")
    expect(echo(page)).to_contain_text("stored: [2026-03-01T12:00:00.000Z]")


def test_the_zone_picker_keeps_the_configured_zone_even_if_it_is_uncommon(page, api) -> None:
    """Otherwise a module pinned to a zone the short list omits would silently
    move its viewers somewhere else the moment the picker rendered."""
    mod = module_with(api, "Datetime uncommon zone", {
        "timezone": "Pacific/Chatham", "zoneEditable": True,
    })
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("datetime-zone")).to_have_value("Pacific/Chatham")


def test_the_zone_can_come_from_a_variable(page, api) -> None:
    """p.464's "dynamically using a variable" — and the value arrives through a
    **server resolve**, which is the part no pure function can stand in for."""
    mod = module_with(api, "Datetime zone variable", {
        "zoneMode": "variable", "timezoneVariable": "v_zone",
    })
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("datetime-zone-label")).to_contain_text("Asia/Kolkata")
    field(page).fill("2026-03-01T17:30")
    expect(echo(page)).to_contain_text("stored: [2026-03-01T12:00:00.000Z]")


def test_a_nonsense_zone_falls_back_rather_than_blanking_the_module(page, api) -> None:
    """A variable holds whatever a derivation put in it, and `Intl` throwing
    inside a render is a blank module rather than a wrong time."""
    mod = Module(api, "Datetime bad zone")
    mod.define({
        "format": 2,
        "layout": layout({
            "dt": {"resolvedName": "CanvasDateTimePicker",
                   "props": {"name": "v_when", "label": "When", "dateFormat": "iso",
                             "timeFormat": "h24", "precision": "minute",
                             "zoneMode": "variable", "timezone": "UTC",
                             "timezoneVariable": "v_zone", "zoneEditable": False}},
            "echo": {"resolvedName": "CanvasText",
                     "props": {"tag": "p", "text": "stored: [{{v_when}}]"}},
        }),
        "variables": {
            "v_when": {"id": "v_when", "kind": "timestamp", "label": "When"},
            "v_zone": {"id": "v_zone", "kind": "string", "label": "Zone",
                       "default": "Mars/Olympus"},
        },
        "events": {},
    })
    open_module(page, mod)
    settled(page)

    expect(field(page)).to_be_visible()
    field(page).fill("2026-03-01T12:00")
    expect(echo(page)).to_contain_text("stored: [")


def test_the_settings_panel_offers_only_timestamp_variables(page, api) -> None:
    """The widget writes an instant. `v_zone` is a string and must not be
    offered — the same rule as every other widget's picker."""
    mod = module_with(api, "Datetime settings")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Date and time").first.click()
    picker = page.get_by_test_id("datetime-variable")
    labels = [picker.locator("option").nth(i).inner_text()
              for i in range(picker.locator("option").count())]
    assert "When" in labels and "Zone" not in labels, labels


def test_the_zone_settings_follow_the_chosen_mode(page, api) -> None:
    """p.464's three modes each ask a different question, and a control that
    does nothing under the selected mode is a control that lies about it."""
    mod = module_with(api, "Datetime zone mode")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Date and time").first.click()
    # Starts on `fixed`, so it offers a zone and not a variable.
    expect(page.get_by_test_id("datetime-timezone")).to_be_visible()
    expect(page.get_by_test_id("datetime-timezone-variable")).to_have_count(0)

    page.get_by_test_id("datetime-zone-mode").select_option("variable")
    expect(page.get_by_test_id("datetime-timezone")).to_have_count(0)
    expect(page.get_by_test_id("datetime-timezone-variable")).to_be_visible()

    page.get_by_test_id("datetime-zone-mode").select_option("local")
    expect(page.get_by_test_id("datetime-timezone")).to_have_count(0)
    expect(page.get_by_test_id("datetime-timezone-variable")).to_have_count(0)
