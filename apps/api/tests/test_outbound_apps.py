"""Outbound applications: one person's authorization of a source (§752;
decision 0022; `data-connection` p.39-40, p.243).

> "When a source is configured with an outbound application, authentication
>  is delegated to an external OAuth 2.0 provider on behalf of the calling
>  user." (p.39)

A fake OAuth 2.0 provider runs in a thread: its token endpoint trades a code
only for the PKCE verifier whose challenge the authorize URL carried, and only
for the redirect URI the code was issued to, as a real one does. Each test
walks the flow the way a browser would - start, the provider, the callback -
and reads what was stored.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import threading
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import connections as conn_routes  # noqa: E402
from src.services import outbound_apps  # noqa: E402
from src.services.secrets import InMemorySecretsGateway  # noqa: E402

ADMIN_DSN = os.environ.get(
    "TEST_ADMIN_DSN", "postgresql://platform:devpass@localhost:5432/platform?sslmode=disable")
#: http so the test client, which talks http, gets the state cookie back: an
#: https address makes it Secure (`test_the_cookie_is_secure_behind_https`).
PUBLIC = "http://platform.example.test"


class Provider:
    """The OAuth server's side: the codes it issued, each for one challenge
    and one redirect URI."""

    def __init__(self) -> None:
        self.codes: dict[str, dict] = {}
        self.exchanged: list[dict] = []

    def issue(self, authorize_url: str) -> tuple[str, str]:
        """What the provider does when the person says yes: a code bound to
        the request's challenge, sent back to its redirect URI."""
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(authorize_url).query))
        code = uuid.uuid4().hex
        self.codes[code] = {"challenge": query["code_challenge"],
                            "redirect_uri": query["redirect_uri"],
                            "client_id": query["client_id"]}
        return code, query["state"]


@pytest.fixture(scope="module")
def provider():
    state = Provider()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # quiet
            pass

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            form = dict(urllib.parse.parse_qsl(self.rfile.read(length).decode()))
            state.exchanged.append(form)
            issued = state.codes.pop(form.get("code", ""), None)
            verifier = form.get("code_verifier", "")
            challenge = base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            ok = (form.get("grant_type") == "authorization_code" and issued is not None
                  and issued["challenge"] == challenge
                  and issued["redirect_uri"] == form.get("redirect_uri")
                  and form.get("client_secret") == "s3cret")
            body = (json.dumps({"access_token": f"at-{uuid.uuid4().hex[:8]}",
                                "refresh_token": "rt-1", "expires_in": 3600,
                                "scope": "read write"}).encode()
                    if ok else json.dumps({"error": "invalid_grant"}).encode())
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.base = f"http://127.0.0.1:{server.server_port}"
    yield state
    server.shutdown()


@pytest.fixture(autouse=True)
def _public(monkeypatch) -> None:
    monkeypatch.setenv("PLATFORM_PUBLIC_URL", PUBLIC + "/")


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def gateway() -> InMemorySecretsGateway:
    return InMemorySecretsGateway()


@pytest.fixture(scope="module")
def client(gateway) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    conn_routes.configure_secrets_gateway(gateway)
    with TestClient(create_app(), raise_server_exceptions=True, follow_redirects=False) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


@pytest.fixture(autouse=True)
def _fresh_browser(client) -> None:
    """Each test is a browser of its own: a state cookie one test set by hand
    would otherwise ride beside the next one's."""
    client.cookies.clear()


def cbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/connections"


def config(provider: Provider, **over) -> dict:
    return {"base_url": provider.base + "/api", "allow_insecure_http": True,
            "auth_type": "oauth2_authorization_code",
            "authorize_url": provider.base + "/authorize",
            "token_url": provider.base + "/token", "oauth_scope": "read write", **over}


@pytest.fixture()
def source(client, fx, provider) -> str:
    r = client.post(cbase(fx), headers=hdr(fx.editor_sub), json={
        "name": f"Tickets {uuid.uuid4().hex[:6]}", "source_type": "rest",
        "config": config(provider),
        "secret": {"client_id": "anchor-app", "client_secret": "s3cret"}})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def start(client, fx, cid: str, sub: str | None = None, return_to: str = "/w/p/connections"):
    r = client.post(f"{cbase(fx)}/{cid}/authorization", headers=hdr(sub or fx.editor_sub),
                    json={"return_to": return_to})
    assert r.status_code == 200, r.text
    return r.json()["authorize_url"]


def callback(client, **query):
    return client.get("/api/oauth/callback?" + urllib.parse.urlencode(query))


def status(client, fx, cid: str, sub: str | None = None) -> dict:
    r = client.get(f"{cbase(fx)}/{cid}/authorization", headers=hdr(sub or fx.editor_sub))
    assert r.status_code == 200, r.text
    return r.json()


# ---- the source ----------------------------------------------------------------------
def test_the_auth_type_needs_its_urls_and_the_platforms_address(
    client, fx, provider, monkeypatch
) -> None:
    def save(cfg):
        return client.post(cbase(fx), headers=hdr(fx.editor_sub), json={
            "name": f"X {uuid.uuid4().hex[:6]}", "source_type": "rest", "config": cfg,
            "secret": {"client_id": "a", "client_secret": "b"}})
    r = save(config(provider, authorize_url=""))
    assert r.status_code == 422 and "authorize_url: required" in r.text, r.text
    r = save(config(provider, token_url=""))
    assert r.status_code == 422 and "token_url: required" in r.text, r.text
    monkeypatch.delenv("PLATFORM_PUBLIC_URL")
    r = save(config(provider))
    assert r.status_code == 422 and "PLATFORM_PUBLIC_URL" in r.text, r.text


# ---- the flow ------------------------------------------------------------------------
def test_start_sends_the_person_to_the_provider_with_pkce(client, fx, source) -> None:
    url = start(client, fx, source)
    parsed = urllib.parse.urlparse(url)
    query = dict(urllib.parse.parse_qsl(parsed.query))
    assert parsed.path == "/authorize"
    assert query["response_type"] == "code" and query["client_id"] == "anchor-app"
    assert query["redirect_uri"] == f"{PUBLIC}/api/oauth/callback"
    assert query["scope"] == "read write"
    assert query["code_challenge_method"] == "S256" and len(query["code_challenge"]) == 43
    assert query["state"].startswith(f"{fx.editor}.")
    # The state rides a cookie scoped to the callback, which no script reads.
    cookie = client.cookies.get(outbound_apps.STATE_COOKIE)
    assert cookie == query["state"]


def test_the_cookie_is_secure_behind_https(client, fx, source, monkeypatch) -> None:
    monkeypatch.setenv("PLATFORM_PUBLIC_URL", "https://platform.example.test")
    r = client.post(f"{cbase(fx)}/{source}/authorization", headers=hdr(fx.editor_sub), json={})
    cookie = r.headers["set-cookie"]
    for part in ("HttpOnly", "SameSite=lax", "Path=/api/oauth", "Secure", "Max-Age=600"):
        assert part.lower() in cookie.lower(), (part, cookie)


def test_the_callback_stores_the_persons_grant_and_sends_them_back(
    client, fx, source, provider, gateway
) -> None:
    code, state = provider.issue(start(client, fx, source))
    r = callback(client, code=code, state=state)
    assert r.status_code == 303, r.text
    assert r.headers["location"] == "/w/p/connections?authorization=granted"
    # The state's cookie is spent with it.
    assert 'anchor_oauth_state=""' in r.headers["set-cookie"] and "Max-Age=0" in r.headers["set-cookie"]
    mine = status(client, fx, source)
    assert mine["authorized"] and mine["scope"] == "read write" and mine["expires_at"]
    # The tokens are the gateway's, under the source's own name, and the row
    # holds none.
    arn = f"local:secret:anchor/connections/{source}/grants/{fx.editor}"
    stored = gateway.get_secret(arn)
    assert stored["access_token"].startswith("at-") and stored["refresh_token"] == "rt-1"
    with psycopg.connect(ADMIN_DSN) as conn:
        columns = [r[0] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'outbound_grants'").fetchall()]
    assert not any("token" in c for c in columns)
    # The exchange carried the verifier, the client's secret and the same
    # redirect URI, which is what the provider checked.
    assert provider.exchanged[-1]["grant_type"] == "authorization_code"


def test_a_grant_is_its_persons_alone(client, fx, source, provider) -> None:
    code, state = provider.issue(start(client, fx, source))
    assert callback(client, code=code, state=state).status_code == 303
    assert status(client, fx, source)["authorized"] is True
    assert status(client, fx, source, sub=fx.viewer_sub)["authorized"] is False


def test_revoking_forgets_the_tokens(client, fx, source, provider, gateway) -> None:
    code, state = provider.issue(start(client, fx, source))
    callback(client, code=code, state=state)
    r = client.delete(f"{cbase(fx)}/{source}/authorization", headers=hdr(fx.editor_sub))
    assert r.status_code == 200 and r.json()["authorized"] is False
    assert status(client, fx, source)["authorized"] is False
    with pytest.raises(KeyError):
        gateway.get_secret(f"local:secret:anchor/connections/{source}/grants/{fx.editor}")


# ---- what the callback refuses --------------------------------------------------------
def test_a_state_from_another_browser_is_refused(client, fx, source, provider) -> None:
    """Decision 0022 §3: a flow started by one person and completed in
    another's browser would store the second's tokens as the first's grant."""
    code, state = provider.issue(start(client, fx, source))
    client.cookies.clear()
    r = callback(client, code=code, state=state)
    assert r.status_code == 400 and "not started in this browser" in r.text
    assert status(client, fx, source)["authorized"] is False


def test_a_state_is_used_once(client, fx, source, provider) -> None:
    code, state = provider.issue(start(client, fx, source))
    assert callback(client, code=code, state=state).status_code == 303
    client.cookies.set(outbound_apps.STATE_COOKIE, state, path="/api/oauth")
    again = callback(client, code=code, state=state)
    assert again.status_code == 400 and "already been used" in again.text


def test_a_state_ten_minutes_old_is_refused(client, fx, source, provider) -> None:
    code, state = provider.issue(start(client, fx, source))
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE oauth_states SET created_at = now() - interval '11 minutes' "
                     "WHERE state = %s", (state,))
    r = callback(client, code=code, state=state)
    assert r.status_code == 400 and "longer than ten minutes" in r.text
    assert status(client, fx, source)["authorized"] is False


def test_a_state_whose_person_is_changed_finds_nothing(client, fx, source, provider) -> None:
    code, state = provider.issue(start(client, fx, source))
    forged = f"{fx.viewer}.{state.split('.', 1)[1]}"
    client.cookies.set(outbound_apps.STATE_COOKIE, forged, path="/api/oauth")
    r = callback(client, code=code, state=forged)
    assert r.status_code == 400 and "already been used" in r.text


def test_something_that_is_not_a_state_is_refused(client) -> None:
    client.cookies.set(outbound_apps.STATE_COOKIE, "nonsense", path="/api/oauth")
    r = callback(client, code="x", state="nonsense")
    assert r.status_code == 400 and "not an authorization this platform started" in r.text


def test_the_person_declining_is_said_and_stores_nothing(client, fx, source, provider) -> None:
    _code, state = provider.issue(start(client, fx, source))
    r = callback(client, error="access_denied", state=state)
    assert r.status_code == 303
    assert r.headers["location"] == "/w/p/connections?authorization=denied&reason=access_denied"
    assert status(client, fx, source)["authorized"] is False


def test_a_code_the_provider_will_not_trade_is_said(client, fx, source, provider) -> None:
    _code, state = provider.issue(start(client, fx, source))
    r = callback(client, code="not-the-code", state=state)
    assert r.status_code == 303
    location = urllib.parse.unquote_plus(r.headers["location"])
    assert "authorization=failed" in location
    assert "the token endpoint rejected the credentials (HTTP 400)" in location
    assert status(client, fx, source)["authorized"] is False


def test_the_way_back_never_leaves_the_platform(client, fx, source, provider) -> None:
    for asked, kept in (("//evil.example/x", "/"), ("https://evil.example", "/"),
                        ("/\\evil.example", "/"), ("/w/p/x?tab=1", "/w/p/x?tab=1")):
        code, state = provider.issue(start(client, fx, source, return_to=asked))
        r = callback(client, code=code, state=state)
        assert r.headers["location"].startswith(kept + ("&" if "?" in kept else "?")), (
            asked, r.headers["location"])


def test_a_source_without_an_outbound_application_has_nothing_to_authorize(
    client, fx, provider
) -> None:
    r = client.post(cbase(fx), headers=hdr(fx.editor_sub), json={
        "name": f"Plain {uuid.uuid4().hex[:6]}", "source_type": "rest",
        "config": {"base_url": provider.base, "allow_insecure_http": True}})
    assert r.status_code == 201, r.text
    r = client.post(f"{cbase(fx)}/{r.json()['id']}/authorization", headers=hdr(fx.editor_sub),
                    json={})
    assert r.status_code == 409 and "does not authenticate through an outbound application" in r.text


def test_a_call_sends_the_persons_token_and_nothing_else() -> None:
    """The connector's half (§753 resolves the token): a source with an
    outbound application sends the caller's access token, and without one
    says so rather than falling back to the application's own credentials."""
    from src.services.connectors import ConnectorOperationError, RestConnector

    cfg = {"auth_type": "oauth2_authorization_code"}
    headers = RestConnector()._auth_headers(cfg, {"client_id": "a", "access_token": "at-9"})
    assert headers == {"Authorization": "Bearer at-9"}
    with pytest.raises(ConnectorOperationError, match="called as the person using it"):
        RestConnector()._auth_headers(cfg, {"client_id": "a", "client_secret": "b"})
