"""Kiosk mode, end to end (§684; `workshop` p.610-612).

> "Once a module has been added to the kiosk mode setting's allowlist,
> builders with permissions to launch kiosk mode sessions can do so by
> navigating to the Advanced Functionalities section of the module's Settings
> panel and enabling the Kiosk Mode toggle. The Open kiosk button will appear
> in the top right corner of the module. Selecting this button opens a modal
> that outlines the contents… After reviewing the scope of the module's
> content, select Launch session to start a kiosk mode session." (p.610)

The refusals are `apps/api/tests/test_kiosk.py`, against the API, because that
is where they are enforced. What needs a browser is the path a builder walks:
Control Panel, the toggle, the button, the modal, the running kiosk - which
must render **without a single refused request**, since the read-only rule is
an allowlist and a widget whose read it forgot would draw nothing - and the
two ways out.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import WEB_BASE, eventually, open_builder, publish, save, viewer_url

ROWS = [{"id": "1", "name": "Ada"}, {"id": "2", "name": "Grace"}]


@pytest.fixture(scope="module")
def mod(api):
    mod = Module(api, "Kiosk")
    type_id = mod.object_type(columns=["id", "name"], rows=ROWS, key="id", title="name")
    mod.define({
        "format": 2,
        # On a page, so view mode records a view of it (p.188) - which a kiosk
        # must not, being read-only.
        "layout": layout({
            "pg": {"resolvedName": "CanvasPage", "props": {"title": "Rows", "pageId": "rows"},
                   "isCanvas": True, "nodes": ["tbl"]},
            "tbl": {"resolvedName": "CanvasObjectTable", "parent": "pg",
                    "props": {"objectSetVariable": "v_all", "columns": "id,name", "pageSize": 25}},
        }),
        "variables": {"v_all": {"id": "v_all", "kind": "object_set", "label": "All rows",
                                "object_set": object_set(type_id)}},
        "events": {},
        "kiosk": {"enabled": True},
        # Saving a state is a write, so a kiosk does not offer it (p.610).
        "state_saving": {"enabled": True},
    })
    publish(mod)
    return mod


def allowlist(page, mod) -> None:
    """p.610's Control Panel: the organisation page, as an administrator."""
    page.goto(f"{WEB_BASE}/org")
    settings = page.get_by_test_id("kiosk-settings")
    expect(settings).to_be_visible(timeout=30000)
    choice = page.get_by_test_id("kiosk-add-module")
    expect(choice.locator(f"option[value='{mod.app_id}']")).to_have_count(1)
    choice.select_option(mod.app_id)
    page.get_by_test_id("kiosk-add").click()
    expect(page.get_by_test_id("kiosk-allowlist")).to_contain_text(f"App {mod.tag}")


def launch(page, mod) -> None:
    page.goto(viewer_url(mod))
    page.get_by_test_id("open-kiosk").click()
    expect(page.get_by_test_id("kiosk-scope")).to_contain_text("Object types")
    page.get_by_test_id("launch-kiosk").click()
    expect(page.get_by_test_id("kiosk-bar")).to_be_visible(timeout=30000)


def test_the_button_waits_for_the_allowlist(page, mod) -> None:
    # Asked and answered before looking: an absent button is otherwise also
    # what the page shows while the question is still in flight.
    with page.expect_response(lambda r: r.url.endswith(f"/published-canvas-apps/{mod.app_id}/kiosk")):
        page.goto(viewer_url(mod))
    expect(page.locator("h1")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("state-bar")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("open-kiosk")).to_have_count(0)


def test_a_builder_launches_a_session_that_shows_the_module(page, mod) -> None:
    allowlist(page, mod)
    refused: list[str] = []
    page.on("response", lambda r: refused.append(f"{r.request.method} {r.url}")
            if r.status == 403 and "/api/" in r.url else None)
    launch(page, mod)
    expect(page).to_have_url(f"{WEB_BASE}/kiosk")
    expect(page.get_by_text("Grace")).to_be_visible(timeout=30000)
    expect(page.get_by_text("Ada")).to_be_visible()
    expect(page.get_by_test_id("state-bar")).to_have_count(0)
    page.wait_for_load_state("networkidle")
    assert refused == [], refused
    # The credential is the tab's, never the address bar's.
    assert "kiosk_" not in page.url
    assert page.evaluate("sessionStorage.getItem('anchor-kiosk-session')").startswith("kiosk_")

    # p.610's Exit kiosk mode: back to the module, the credential gone.
    page.get_by_test_id("exit-kiosk").click()
    expect(page).to_have_url(viewer_url(mod))
    assert page.evaluate("sessionStorage.getItem('anchor-kiosk-session')") is None


def test_an_administrator_ends_a_running_session(page, mod) -> None:
    launch(page, mod)
    admin = page.context.new_page()
    admin.goto(f"{WEB_BASE}/org")
    running = admin.locator("[data-testid='kiosk-session'][data-active='true']").first
    expect(running).to_be_visible(timeout=30000)
    count = admin.locator("[data-testid='kiosk-session'][data-active='true']").count()
    running.get_by_test_id("kiosk-end").click()
    expect(admin.locator("[data-testid='kiosk-session'][data-active='true']")).to_have_count(count - 1)
    page.reload()
    expect(page.get_by_test_id("kiosk-ended")).to_contain_text("This kiosk session has ended")


def test_the_toggle_is_in_the_module_s_settings(page, mod) -> None:
    open_builder(page, mod)
    toggle = page.get_by_test_id("kiosk-toggle")
    expect(toggle).to_be_checked(timeout=30000)
    toggle.uncheck()
    save(page)
    # Read back until the save has landed: the builder's "saved" line is
    # already showing from the first save when the second one starts.
    eventually(lambda: "kiosk" in mod.definition(), lambda held: held is False,
               what="the toggle turned off")
    page.get_by_test_id("kiosk-toggle").check()
    save(page)
    eventually(lambda: mod.definition().get("kiosk"), lambda held: held == {"enabled": True},
               what="the toggle turned on")
