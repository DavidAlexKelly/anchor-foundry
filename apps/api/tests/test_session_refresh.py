"""A browser session outlives its fifteen-minute access token (§859).

The session cookie carried only Cognito's access token, so a deployed session
ended fifteen minutes in. The refresh token Cognito issues with it now goes in
a cookie of its own, sent only to `POST /api/auth/refresh`, which asks Cognito
for a new access token. Cognito's token endpoint is stood in for twice: by a
replacement for the one call in the route tests, and by a local HTTP server for
the call itself.
"""
from __future__ import annotations

import asyncio
import http.server
import json
import os
import sys
import threading
import urllib.parse

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, mint  # noqa: E402
from src.lib import config  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import auth as auth_routes  # noqa: E402
from src.services import cognito_tokens  # noqa: E402

SESSION = {"X-Anchor-Session": "1"}


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("COGNITO_DOMAIN", "https://pool.auth.eu-west-2.amazoncognito.invalid")
    monkeypatch.setenv("COGNITO_CLIENT_ID", "the-client")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    config.get_settings.cache_clear()
    auth_mw.configure_verifier(LocalVerifier())
    with TestClient(create_app(), base_url="http://testserver") as c:
        yield c
    config.get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def signed_in(client: TestClient, sub: str, refresh: str | None = "r-1") -> None:
    body = {"access_token": mint(sub), **({"refresh_token": refresh} if refresh else {})}
    r = client.post("/api/auth/session", json=body)
    assert r.status_code == 200, r.text


def cookie_line(response, name: str) -> str:
    lines = [v for k, v in response.headers.multi_items()
             if k.lower() == "set-cookie" and v.startswith(f"{name}=")]
    assert len(lines) == 1, lines
    return lines[0]


def test_signing_in_keeps_the_refresh_token_where_only_renewal_is_sent_it(client, fx) -> None:
    r = client.post("/api/auth/session",
                    json={"access_token": mint(fx.editor_sub), "refresh_token": "r-1"})
    line = cookie_line(r, auth_routes.REFRESH_COOKIE).lower()
    assert "path=/api/auth/refresh" in line
    assert "httponly" in line and "samesite=strict" in line
    # And a development token, with none, sets none.
    r = client.post("/api/auth/session", json={"access_token": mint(fx.editor_sub)})
    assert not [v for k, v in r.headers.multi_items()
                if k.lower() == "set-cookie" and v.startswith(auth_routes.REFRESH_COOKIE)]


def test_a_renewal_is_a_new_session_for_the_same_person(client, fx, monkeypatch) -> None:
    signed_in(client, fx.editor_sub)
    asked: list[tuple] = []

    async def cognito(domain, client_id, token, **_):
        asked.append((domain, client_id, token))
        return mint(fx.editor_sub)

    monkeypatch.setattr(cognito_tokens, "refreshed_access_token", cognito)
    r = client.post("/api/auth/refresh", headers=SESSION)
    assert r.status_code == 200, r.text
    assert asked == [("https://pool.auth.eu-west-2.amazoncognito.invalid", "the-client", "r-1")]
    cookie_line(r, auth_mw.SESSION_COOKIE)
    # The new session works: the cookie alone, with the header.
    me = client.get("/api/auth/me", headers=SESSION)
    assert me.status_code == 200 and me.json()["user_id"] == r.json()["user_id"]


def test_a_refused_renewal_ends_the_session_for_good(client, fx, monkeypatch) -> None:
    signed_in(client, fx.editor_sub)

    async def refused(*_, **__):
        raise cognito_tokens.RefreshRefused("invalid_grant")

    monkeypatch.setattr(cognito_tokens, "refreshed_access_token", refused)
    r = client.post("/api/auth/refresh", headers=SESSION)
    assert r.status_code == 401
    assert "invalid_grant" in r.json()["detail"]
    line = cookie_line(r, auth_routes.REFRESH_COOKIE).lower()
    assert "max-age=0" in line and "path=/api/auth/refresh" in line
    # So the next 401 is not answered by asking Cognito again.
    assert client.post("/api/auth/refresh", headers=SESSION).status_code == 401


def test_cognito_unreachable_is_not_the_end_of_the_session(client, fx, monkeypatch) -> None:
    signed_in(client, fx.editor_sub)

    async def down(*_, **__):
        raise cognito_tokens.RefreshUnavailable("the token endpoint answered 503")

    monkeypatch.setattr(cognito_tokens, "refreshed_access_token", down)
    r = client.post("/api/auth/refresh", headers=SESSION)
    assert r.status_code == 503
    assert not [v for k, v in r.headers.multi_items() if k.lower() == "set-cookie"]


def test_what_a_renewal_needs(client, fx, monkeypatch) -> None:
    async def never(*_, **__):  # pragma: no cover - reaching it is the failure
        raise AssertionError("Cognito was asked")

    monkeypatch.setattr(cognito_tokens, "refreshed_access_token", never)
    # No refresh cookie.
    assert client.post("/api/auth/refresh", headers=SESSION).status_code == 401
    signed_in(client, fx.editor_sub)
    # No CSRF header.
    r = client.post("/api/auth/refresh")
    assert r.status_code == 401 and "X-Anchor-Session" in r.json()["detail"]
    # No hosted UI configured.
    monkeypatch.delenv("COGNITO_DOMAIN")
    config.get_settings.cache_clear()
    assert client.post("/api/auth/refresh", headers=SESSION).status_code == 401


def test_signing_out_drops_the_refresh_cookie_too(client, fx) -> None:
    signed_in(client, fx.editor_sub)
    r = client.post("/api/auth/logout", headers=SESSION)
    assert r.status_code == 204, r.text
    assert "max-age=0" in cookie_line(r, auth_routes.REFRESH_COOKIE).lower()
    assert "max-age=0" in cookie_line(r, auth_mw.SESSION_COOKIE).lower()


# ---- the call to Cognito itself ---------------------------------------------
class TokenEndpoint(http.server.BaseHTTPRequestHandler):
    answers: list[tuple[int, dict]] = []
    received: list[dict] = []

    def do_POST(self) -> None:  # noqa: N802 - the handler's own name
        length = int(self.headers.get("Content-Length", 0))
        TokenEndpoint.received.append(
            {"path": self.path, **urllib.parse.parse_qs(self.rfile.read(length).decode())})
        status, body = TokenEndpoint.answers.pop(0)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, *_):
        pass


@pytest.fixture
def endpoint():
    server = http.server.HTTPServer(("127.0.0.1", 0), TokenEndpoint)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    TokenEndpoint.received.clear()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_the_exchange_asks_for_a_refresh_grant(endpoint) -> None:
    TokenEndpoint.answers[:] = [(200, {"access_token": "new", "token_type": "Bearer"})]
    assert asyncio.run(cognito_tokens.refreshed_access_token(endpoint, "the-client", "r-1")) == "new"
    [asked] = TokenEndpoint.received
    assert asked["path"] == "/oauth2/token"
    assert asked["grant_type"] == ["refresh_token"]
    assert asked["client_id"] == ["the-client"] and asked["refresh_token"] == ["r-1"]


def test_what_the_exchange_makes_of_each_answer(endpoint) -> None:
    TokenEndpoint.answers[:] = [(400, {"error": "invalid_grant"}), (500, {}), (200, {})]
    with pytest.raises(cognito_tokens.RefreshRefused, match="invalid_grant"):
        asyncio.run(cognito_tokens.refreshed_access_token(endpoint, "c", "r"))
    with pytest.raises(cognito_tokens.RefreshUnavailable, match="500"):
        asyncio.run(cognito_tokens.refreshed_access_token(endpoint, "c", "r"))
    with pytest.raises(cognito_tokens.RefreshUnavailable, match="no access token"):
        asyncio.run(cognito_tokens.refreshed_access_token(endpoint, "c", "r"))
    with pytest.raises(cognito_tokens.RefreshUnavailable, match="could not be reached"):
        asyncio.run(cognito_tokens.refreshed_access_token("http://127.0.0.1:9", "c", "r", timeout=2))
