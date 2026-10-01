"""Diagnose on a connection (§646; `data-connection` TOC §6, *Where to start*).

A source that works passes every step. The same source on a port nothing
listens on stops at "Port accepts a connection", says so above the list, and
names what to check, with the steps after it skipped rather than failed.
"""
from __future__ import annotations

from playwright.sync_api import expect

from conftest import WEB_BASE
from test_source_explorer import a_source, build, source  # noqa: F401


def open_diagnose(page, mod, name: str) -> None:
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/connections")
    row = page.get_by_role("row").filter(has_text=name)
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Diagnose").click()
    expect(page.get_by_test_id("diagnose-summary")).to_be_visible(timeout=30000)


def status(page, step: str):
    return page.locator(f"[data-testid='diagnose-steps'] li[data-step='{step}']")


def test_a_working_source_passes_every_step(page, api, source) -> None:
    mod = build(api, "Diagnose ok")
    conn = a_source(api, mod, source)
    open_diagnose(page, mod, conn["name"])
    expect(page.get_by_test_id("diagnose-summary")).to_have_text("Every step passed.")
    for step in ("destination", "egress", "dns", "tcp", "credentials"):
        expect(status(page, step)).to_have_attribute("data-status", "ok")
    expect(status(page, "tls")).to_have_attribute("data-status", "info")


def test_a_closed_port_stops_at_the_port_and_says_what_to_check(page, api, source) -> None:
    mod = build(api, "Diagnose port")
    conn = a_source(api, mod, {**source, "port": 1})
    open_diagnose(page, mod, conn["name"])
    expect(page.get_by_test_id("diagnose-summary")).to_contain_text(
        "Stopped at port accepts a connection")
    expect(page.get_by_test_id("diagnose-summary")).to_contain_text("firewall")
    expect(status(page, "tcp")).to_have_attribute("data-status", "failed")
    expect(status(page, "credentials")).to_have_attribute("data-status", "skipped")
    expect(page.get_by_test_id("diagnose-hint-tcp")).to_be_visible()
    # The fix is made elsewhere; Run again asks again rather than showing the
    # last answer.
    api.call("PATCH", f"{mod.base}/connections/{conn['id']}", {"config": source})
    page.get_by_role("button", name="Run again").click()
    expect(page.get_by_test_id("diagnose-summary")).to_have_text("Every step passed.")
