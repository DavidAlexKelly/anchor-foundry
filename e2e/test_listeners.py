"""HTTPS listeners, on the Data Connection screen (§516; `data-connection`
p.249-266).

    "Navigate to Data Connection > Listeners to connect the Palantir platform
     to external systems and workflows." (p.261)

What each scheme accepts is `apps/api/tests/test_listeners.py`'s. What needs
a browser is the round trip a person makes: create one, see its address,
start it, have something post to that address, and read what arrived, and a
reader shown all of that with nothing to press.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE


def post(url: str, body: bytes, headers: dict | None = None) -> int:
    request = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def open_connections(page, mod: Module) -> None:
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/connections")
    expect(page.get_by_test_id("listeners-panel")).to_be_visible(timeout=30000)


def card(page, name: str):
    return page.locator(f'[data-testid="listener"][data-name="{name}"]')


def test_a_listener_is_made_started_and_sent_an_event(page, api) -> None:
    mod = Module(api, "Listeners")
    open_connections(page, mod)
    name = f"Tickets {mod.tag}"
    page.get_by_test_id("listener-new").click()
    page.get_by_test_id("listener-name").fill(name)
    page.get_by_test_id("listener-create").click()

    listener = card(page, name)
    expect(listener.get_by_test_id("listener-status")).to_contain_text("Stopped", timeout=15000)
    url = listener.get_by_test_id("listener-url").inner_text()
    assert "/api/listen/" in url, url
    expect(listener.get_by_test_id("listener-curl")).to_contain_text(url)
    # Stopped: the address answers, and refuses.
    assert post(url, b'{"n": 1}') == 503

    listener.get_by_test_id("listener-toggle").click()
    expect(listener.get_by_test_id("listener-status")).to_contain_text("Running")
    assert post(url, json.dumps({"ticket": "T-7"}).encode()) == 200

    listener.get_by_test_id("listener-events-toggle").click()
    expect(listener.get_by_test_id("listener-event-body")).to_have_text('{"ticket": "T-7"}', timeout=15000)
    expect(listener.get_by_test_id("listener-event")).to_contain_text("application/json")


def test_a_verifying_listener_says_its_scheme_and_refuses_the_unsigned(page, api) -> None:
    mod = Module(api, "Listeners secret")
    open_connections(page, mod)
    name = f"Signed {mod.tag}"
    page.get_by_test_id("listener-new").click()
    page.get_by_test_id("listener-name").fill(name)
    page.get_by_test_id("listener-verification").select_option("header_secret")
    expect(page.get_by_test_id("listener-problem")).to_have_text("This verification needs a secret.")
    expect(page.get_by_test_id("listener-create")).to_be_disabled()
    page.get_by_test_id("listener-secret").fill("t0ken")
    page.get_by_test_id("listener-header").fill("X-Hook-Token")
    expect(page.get_by_test_id("listener-problem")).to_have_count(0)
    page.get_by_test_id("listener-create").click()

    listener = card(page, name)
    expect(listener.get_by_test_id("listener-verification-text")).to_have_text(
        "Verification: Secret in a header (X-Hook-Token)", timeout=15000)
    listener.get_by_test_id("listener-toggle").click()
    expect(listener.get_by_test_id("listener-status")).to_contain_text("Running")
    url = listener.get_by_test_id("listener-url").inner_text()
    assert post(url, b"{}") == 401
    assert post(url, b"{}", {"X-Hook-Token": "t0ken"}) == 200


def test_a_reader_sees_listeners_and_events_with_nothing_to_press(page, viewer_page, api) -> None:
    mod = Module(api, "Listeners reader")
    made = mod.api.call("POST", f"{mod.base}/listeners", {"display_name": f"Read {mod.tag}"})
    mod.api.call("POST", f"{mod.base}/listeners/{made['id']}/start")
    [endpoint] = made["endpoints"]
    url = endpoint["url"]
    assert post(url, b'{"seen": true}') == 200

    open_connections(viewer_page, mod)
    listener = card(viewer_page, f"Read {mod.tag}")
    expect(listener.get_by_test_id("listener-status")).to_contain_text("Running · 1 event received")
    expect(viewer_page.get_by_test_id("listener-new")).to_have_count(0)
    expect(listener.get_by_test_id("listener-toggle")).to_have_count(0)
    expect(listener.get_by_test_id("listener-delete")).to_have_count(0)
    listener.get_by_test_id("listener-events-toggle").click()
    expect(listener.get_by_test_id("listener-event-body")).to_have_text('{"seen": true}')
