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
    expect(listener.get_by_test_id("listener-archive-now")).to_have_count(0)
    expect(listener.get_by_test_id("listener-ingress-edit")).to_have_count(0)
    listener.get_by_test_id("listener-events-toggle").click()
    expect(listener.get_by_test_id("listener-event-body")).to_have_text('{"seen": true}')


def test_rotating_an_endpoint_without_downtime(page, api) -> None:
    """§517, p.258: "Generate a new endpoint, and add an expiration date for
    the old endpoint. You should now have two usable endpoints. Replace any
    usage of your old endpoint with the new endpoint. Delete the old
    endpoint.\""""
    mod = Module(api, "Listeners rotation")
    made = mod.api.call("POST", f"{mod.base}/listeners", {"display_name": f"Rotating {mod.tag}"})
    mod.api.call("POST", f"{mod.base}/listeners/{made['id']}/start")
    old_url = made["endpoints"][0]["url"]
    open_connections(page, mod)
    listener = card(page, f"Rotating {mod.tag}")

    listener.get_by_test_id("listener-rotate").click()
    retiring = listener.get_by_test_id("listener-endpoint")
    expect(retiring).to_contain_text(old_url, timeout=15000)
    expect(retiring.get_by_test_id("listener-endpoint-state")).to_have_text(
        "Retiring: answers for 24 more hours")
    new_url = listener.get_by_test_id("listener-url").inner_text()
    assert new_url != old_url
    assert post(old_url, b"{}") == 200 and post(new_url, b"{}") == 200
    expect(listener.get_by_test_id("listener-no-rotation")).to_contain_text("at most two endpoints")
    expect(listener.get_by_test_id("listener-rotate")).to_have_count(0)

    retiring.get_by_test_id("listener-endpoint-extend").click()
    expect(retiring.get_by_test_id("listener-endpoint-state")).to_have_text(
        "Retiring: answers for 2 more days")

    retiring.get_by_test_id("listener-endpoint-delete").click()
    expect(listener.get_by_test_id("listener-endpoint")).to_have_count(0)
    assert post(old_url, b"{}") == 404

    # And retiring the address at once.
    listener.get_by_test_id("listener-rotation").select_option("now")
    listener.get_by_test_id("listener-rotate").click()
    expect(listener.get_by_test_id("listener-url")).not_to_have_text(new_url)
    expect(listener.get_by_test_id("listener-endpoint")).to_have_count(0)
    assert post(new_url, b"{}") == 404


def test_a_named_sender_asks_only_for_its_secret(page, api) -> None:
    """§518, p.262: "configure a custom, basic authentication listener, or one
    of the following listeners". GitHub fixes the scheme and the header, so
    the form asks for the secret alone, and a signed push is taken."""
    import hashlib
    import hmac

    mod = Module(api, "Listeners github")
    open_connections(page, mod)
    name = f"Pushes {mod.tag}"
    page.get_by_test_id("listener-new").click()
    page.get_by_test_id("listener-name").fill(name)
    page.get_by_test_id("listener-type").select_option("github")
    expect(page.get_by_test_id("listener-verification")).to_be_disabled()
    expect(page.get_by_test_id("listener-verification")).to_have_value("hmac_sha256")
    expect(page.get_by_test_id("listener-header")).to_have_count(0)
    page.get_by_test_id("listener-secret").fill("gh-secret")
    page.get_by_test_id("listener-create").click()

    listener = card(page, name)
    expect(listener.get_by_test_id("listener-verification-text")).to_have_text(
        "Verification: GitHub · HMAC-SHA256 signature (X-Hub-Signature-256)", timeout=15000)
    listener.get_by_test_id("listener-toggle").click()
    expect(listener.get_by_test_id("listener-status")).to_contain_text("Running")
    url = listener.get_by_test_id("listener-url").inner_text()
    body = b'{"ref": "refs/heads/main"}'
    sig = hmac.new(b"gh-secret", body, hashlib.sha256).hexdigest()
    assert post(url, body, {"X-Hub-Signature-256": f"sha256={sig}"}) == 200
    assert post(url, body) == 401



def test_archiving_now_makes_the_backing_dataset(page, api) -> None:
    """§519, p.264: "Every few minutes, the listener event stream will archive
    into a backing dataset. This dataset can be used like any other dataset".
    Archive now does the run the worker does, and the dataset it makes opens
    like any other and says what made it."""
    mod = Module(api, "Listeners archive")
    name = f"Archived {mod.tag}"
    made = mod.api.call("POST", f"{mod.base}/listeners", {"display_name": name})
    mod.api.call("POST", f"{mod.base}/listeners/{made['id']}/start")
    url = made["endpoints"][0]["url"]
    assert post(url, b'{"n": 1}') == 200 and post(url, b'{"n": 2}') == 200
    open_connections(page, mod)
    listener = card(page, name)
    expect(listener.get_by_test_id("listener-archive")).to_contain_text(
        "Not archived yet · 2 events waiting. The first archive makes the dataset.")

    listener.get_by_test_id("listener-archive-now").click()
    expect(listener.get_by_test_id("listener-archived")).to_have_text("Archived 2 events as version 1.")
    expect(listener.get_by_test_id("listener-archive")).to_contain_text(
        f"Archived to {name} events · nothing waiting")
    listener.get_by_test_id("listener-archive").get_by_role("link", name=f"{name} events").click()
    page.wait_for_url("**/r/**")
    page.goto(page.url.split("?")[0] + "?tab=details")
    expect(page.get_by_test_id("ds-made-by")).to_have_text(f"Listener {name}", timeout=30000)
    expect(page.get_by_test_id("ds-size")).to_contain_text("6 columns")


def test_an_allowlist_narrows_who_may_send(page, api) -> None:
    """§520, p.254: "Configuring a small IP range … to allow requests to a
    listener with only basic authorization or header secret verification
    available." This test posts from this machine, so a range without it
    refuses the post and one with it takes it."""
    mod = Module(api, "Listeners ingress")
    name = f"Narrow {mod.tag}"
    made = mod.api.call("POST", f"{mod.base}/listeners", {"display_name": name})
    mod.api.call("POST", f"{mod.base}/listeners/{made['id']}/start")
    [endpoint] = made["endpoints"]
    url = endpoint["url"]

    open_connections(page, mod)
    listener = card(page, name)
    expect(listener.get_by_test_id("listener-ingress")).to_contain_text("inherited ingress", timeout=15000)
    listener.get_by_test_id("listener-ingress-edit").click()
    ranges = listener.get_by_test_id("listener-ingress-ranges")
    ranges.fill("203.0.113.0/24\nnot-a-range")
    listener.get_by_test_id("listener-ingress-save").click()
    expect(listener.get_by_test_id("listener-ingress-error")).to_contain_text("'not-a-range' is not an IP")
    # Nothing was saved, and the refusal does not outlive the edit it was about.
    listener.get_by_test_id("listener-ingress-cancel").click()
    expect(listener.get_by_test_id("listener-ingress")).to_contain_text("inherited ingress")
    listener.get_by_test_id("listener-ingress-edit").click()
    expect(ranges).to_have_value("")
    expect(listener.get_by_test_id("listener-ingress-error")).to_have_count(0)
    ranges.fill("203.0.113.9/24")
    listener.get_by_test_id("listener-ingress-save").click()
    expect(listener.get_by_test_id("listener-ingress")).to_have_text(
        "Only 203.0.113.0/24 may send.Edit allowlist")
    expect(listener.get_by_test_id("listener-ingress-form")).to_have_count(0)
    assert post(url, b'{"n": 1}') == 403

    # This machine's own addresses, both ways it may be reached.
    listener.get_by_test_id("listener-ingress-edit").click()
    expect(ranges).to_have_value("203.0.113.0/24")
    ranges.fill("203.0.113.0/24\n127.0.0.0/8\n::1")
    listener.get_by_test_id("listener-ingress-save").click()
    expect(listener.get_by_test_id("listener-ingress")).to_contain_text(
        "Only these 3 ranges may send: 203.0.113.0/24, 127.0.0.0/8, ::1/128.")
    assert post(url, b'{"n": 2}') == 200
    listener.get_by_test_id("listener-events-toggle").click()
    expect(listener.get_by_test_id("listener-event-body")).to_have_text('{"n": 2}', timeout=15000)

    # Emptying it is inherited ingress again.
    listener.get_by_test_id("listener-ingress-edit").click()
    ranges.fill("")
    listener.get_by_test_id("listener-ingress-save").click()
    expect(listener.get_by_test_id("listener-ingress")).to_contain_text("inherited ingress")
