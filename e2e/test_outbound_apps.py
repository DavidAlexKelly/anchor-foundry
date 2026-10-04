"""An outbound application authorized from the connections page (§754;
decision 0022; `data-connection` p.39-40, p.243).

The grant, the callback's refusals and the calls made with it are the API's
tests' (`apps/api/tests/test_outbound_apps.py`, `test_outbound_calls.py`), and
the sentences are `apps/web/src/lib/outbound-app.test.ts`'. What needs a
browser is the round trip itself: the state cookie is set on this browser,
the provider sends the same browser back to `/api/oauth/callback`, and the
page it lands on says how it went - and that a source saved through the form
asks to be authorized rather than failing a test nobody could pass yet.
"""
from __future__ import annotations

import json
import threading
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE


class Provider:
    """A provider that asks the person, and an API that answers only the
    access tokens it issued."""

    def __init__(self) -> None:
        self.tokens: set[str] = set()
        self.base = ""


@pytest.fixture(scope="module")
def provider():
    state = Provider()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # quiet
            pass

        def _send(self, status: int, body: bytes, kind: str, headers: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", kind)
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            url = urllib.parse.urlparse(self.path)
            query = dict(urllib.parse.parse_qsl(url.query))
            if url.path == "/authorize":
                # The consent screen: each choice sends the browser back to the
                # redirect URI the platform named, with the state it sent.
                back = query["redirect_uri"]
                allow = urllib.parse.urlencode({"code": uuid.uuid4().hex, "state": query["state"]})
                deny = urllib.parse.urlencode({"error": "access_denied", "state": query["state"]})
                page = (f"<!doctype html><title>Vendor</title><p>Let Anchor read your tickets?</p>"
                        f"<a href='{back}?{allow}'>Allow</a> <a href='{back}?{deny}'>Deny</a>")
                self._send(200, page.encode(), "text/html")
            elif url.path == "/api/tickets":
                token = self.headers.get("Authorization", "").removeprefix("Bearer ")
                if token in state.tokens:
                    self._send(200, json.dumps([{"id": 1, "title": "Printer"}]).encode(),
                               "application/json")
                else:
                    self._send(401, b"{}", "application/json")
            else:
                self._send(404, b"", "text/plain")

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            form = dict(urllib.parse.parse_qsl(self.rfile.read(length).decode()))
            if form.get("grant_type") != "authorization_code" or not form.get("code_verifier"):
                self._send(400, b'{"error": "invalid_grant"}', "application/json")
                return
            token = f"at-{uuid.uuid4().hex[:8]}"
            state.tokens.add(token)
            self._send(200, json.dumps({"access_token": token, "expires_in": 3600,
                                        "scope": "tickets.read"}).encode(), "application/json")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    state.base = f"http://127.0.0.1:{server.server_port}"
    yield state
    server.shutdown()


@pytest.fixture(scope="module")
def module(api):
    return Module(api, "Outbound apps")


def connections_page(page, module) -> None:
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}/connections")


def a_source(api, module, provider: Provider) -> dict:
    return api.call("POST", f"{module.base}/connections", {
        "name": f"Tickets {uuid.uuid4().hex[:6]}", "source_type": "rest",
        "config": {"base_url": provider.base + "/api/tickets", "allow_insecure_http": True,
                   "auth_type": "oauth2_authorization_code",
                   "authorize_url": provider.base + "/authorize",
                   "token_url": provider.base + "/token", "oauth_scope": "tickets.read"},
        "secret": {"client_id": "anchor", "client_secret": "s3cret"}})


def test_a_source_saved_in_the_form_is_authorized_and_then_works(
    page, api, module, provider
) -> None:
    name = f"Helpdesk {uuid.uuid4().hex[:6]}"
    connections_page(page, module)
    page.get_by_role("button", name="Add connection").first.click()
    # The open one: an empty project has a second wizard in its empty state.
    dialog = page.locator("dialog.dialog[open]").filter(has_text="Add connection")
    dialog.get_by_role("button", name="REST / HTTP JSON").click()
    dialog.get_by_label("Connection name").fill(name)
    # The application's own fields are not asked for until it is chosen.
    expect(dialog.get_by_label("Token URL")).to_be_visible()
    expect(dialog.get_by_label("Authorize URL")).to_have_count(0)
    dialog.get_by_label("Auth Type").select_option("oauth2_authorization_code")
    dialog.get_by_label("Base URL").fill(provider.base + "/api/tickets")
    dialog.get_by_label("Authorize URL").fill(provider.base + "/authorize")
    dialog.get_by_label("Token URL").fill(provider.base + "/token")
    dialog.get_by_label("Oauth Scope").fill("tickets.read")
    dialog.get_by_label("Allow Insecure Http").check()
    dialog.get_by_label("client_id").fill("anchor")
    dialog.get_by_label("client_secret").fill("s3cret")
    dialog.get_by_role("button", name="Save & test").click()
    expect(dialog).to_contain_text(
        f"{name} was saved. It is called as whoever uses it", timeout=15000)

    dialog.get_by_role("button", name="Authorize now").click()
    page.wait_for_url(f"{provider.base}/authorize*", timeout=15000)
    page.get_by_role("link", name="Allow").click()
    page.wait_for_url("**/connections", timeout=30000)
    expect(page.get_by_test_id("authorization-returned")).to_have_text(
        "Authorized. Calls on the source are now made as you.", timeout=15000)
    # Said once: the address no longer carries it.
    assert "authorization=" not in page.evaluate("window.location.search")

    cell = page.get_by_test_id(f"authorization-{name}")
    expect(cell.get_by_test_id("authorization-says")).to_have_text(
        "You have authorized this source with scope tickets.read. Calls on it are made as you.",
        timeout=15000)
    # The call is made with the person's token, which the far end accepts.
    row = page.locator("tr").filter(has_text=name).first
    row.get_by_role("button", name="Test").click()
    expect(row.locator(".status-ok")).to_be_visible(timeout=30000)

    cell.get_by_role("button", name="Revoke").click()
    expect(cell.get_by_test_id("authorization-says")).to_contain_text(
        "You have not authorized this source.")
    expect(cell.get_by_role("button", name="Authorize", exact=True)).to_be_visible()
    # Nothing left to revoke.
    expect(cell.get_by_role("button", name="Revoke")).to_have_count(0)


def test_declining_at_the_provider_is_said_and_stores_nothing(
    page, api, module, provider
) -> None:
    source = a_source(api, module, provider)
    connections_page(page, module)
    cell = page.get_by_test_id(f"authorization-{source['name']}")
    expect(cell.get_by_test_id("authorization-says")).to_contain_text(
        "You have not authorized this source.", timeout=30000)
    cell.get_by_role("button", name="Authorize", exact=True).click()
    page.wait_for_url(f"{provider.base}/authorize*", timeout=15000)
    page.get_by_role("link", name="Deny").click()
    page.wait_for_url("**/connections", timeout=30000)
    expect(page.get_by_test_id("authorization-returned")).to_have_text(
        "The provider did not authorize the source (access_denied).", timeout=15000)
    expect(page.get_by_test_id(f"authorization-{source['name']}")
           .get_by_test_id("authorization-says")).to_contain_text(
        "You have not authorized this source.")
    grant = api.call("GET", f"{module.base}/connections/{source['id']}/authorization")
    assert grant["authorized"] is False


def test_a_source_called_as_the_platform_offers_no_authorization(
    page, api, module, provider
) -> None:
    source = api.call("POST", f"{module.base}/connections", {
        "name": f"Status {uuid.uuid4().hex[:6]}", "source_type": "rest",
        "config": {"base_url": provider.base + "/api/tickets", "allow_insecure_http": True}})
    other = a_source(api, module, provider)
    connections_page(page, module)
    # The outbound one has arrived, so the plain one's absence is about the
    # product rather than about timing.
    expect(page.get_by_test_id(f"authorization-{other['name']}")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id(f"authorization-{source['name']}")).to_have_count(0)
