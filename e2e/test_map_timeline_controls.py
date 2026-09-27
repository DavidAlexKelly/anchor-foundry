"""p.303's timeline open button and user controls on the Map (§576).

> "Enable timeline: Display the timeline open button at the bottom of the
> map interface. Allow user to change selected time: Enable user control of
> the selected time cursor in the timeline panel. Enable user facing live
> mode toggle: Enable the View latest option in the timeline panel. Open
> timeline by default: Open the timeline by default without selecting the
> timeline button." (p.303)
"""
from __future__ import annotations

from playwright.sync_api import expect

from conftest import eventually, open_builder, open_module, save, settled
from test_map_tracks import build, fleet, pin  # noqa: F401


def test_the_timeline_opens_by_default_and_closes(page, api, fleet) -> None:
    open_module(page, build(api, fleet, "Timeline open"))
    expect(pin(page, "Van one")).to_have_count(1, timeout=20000)
    toggle = page.get_by_test_id("map-timeline-toggle")
    expect(toggle).to_have_attribute("aria-expanded", "true")
    expect(toggle).to_have_text("Hide timeline")
    expect(page.get_by_test_id("map-timeline")).to_be_visible()
    toggle.click()
    expect(page.get_by_test_id("map-timeline")).to_have_count(0)
    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(toggle).to_have_text("Timeline")
    # The pins stay where the time put them: closing the panel is not a time.
    expect(pin(page, "Van two")).to_have_count(1)


def test_a_timeline_closed_by_default_opens_from_its_button(page, api, fleet) -> None:
    open_module(page, build(api, fleet, "Timeline closed", openTimelineByDefault=False))
    expect(pin(page, "Van one")).to_have_count(1, timeout=20000)
    expect(page.get_by_test_id("map-timeline")).to_have_count(0)
    page.get_by_test_id("map-timeline-toggle").click()
    expect(page.get_by_test_id("map-timeline")).to_be_visible()


def test_a_reader_who_may_not_change_the_time_cannot(page, api, fleet) -> None:
    open_module(page, build(api, fleet, "Timeline fixed", selectedTimeVariable="v_time",
                            allowTimeChange=False))
    expect(pin(page, "Van one")).to_have_count(1, timeout=20000)
    expect(page.get_by_test_id("map-timeline-slider")).to_be_disabled()
    # p.303 nests View latest under the cursor, so it goes with it.
    expect(page.get_by_test_id("map-timeline-latest")).to_have_count(0)
    expect(page.get_by_test_id("map-timeline-time")).to_have_text("2026-01-01T00:30:00Z")


def test_view_latest_can_be_left_out(page, api, fleet) -> None:
    open_module(page, build(api, fleet, "Timeline no latest", selectedTimeVariable="v_time",
                            liveModeToggle=False))
    expect(pin(page, "Van one")).to_have_count(1, timeout=20000)
    expect(page.get_by_test_id("map-timeline-slider")).to_be_enabled()
    expect(page.get_by_test_id("map-timeline-latest")).to_have_count(0)


def test_the_panel_sets_the_controls(page, api, fleet) -> None:
    mod = build(api, fleet, "Timeline panel")
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Map").first.click()
    page.get_by_test_id("map-openTimelineByDefault").uncheck()
    page.get_by_test_id("map-liveModeToggle").uncheck()
    page.get_by_test_id("map-allowTimeChange").uncheck()
    # View latest sits under the cursor, so it cannot be offered without it.
    expect(page.get_by_test_id("map-liveModeToggle")).to_be_disabled()
    save(page)
    eventually(lambda: mod.definition()["layout"]["mp"]["props"],
               lambda p: (p.get("openTimelineByDefault"), p.get("liveModeToggle"),
                          p.get("allowTimeChange")) == (False, False, False),
               what="the three controls, saved")
