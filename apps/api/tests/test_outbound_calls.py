"""Calls made as the person, through their grant (§753; decision 0022 §4;
`data-connection` p.39-40, p.243).

> "an outbound application may be used as the authentication for a REST API
>  Webhook and will prompt individual users to authenticate with the OAuth
>  server when attempting to execute the Webhook." (p.243)

A fake OAuth server and the API behind it run in one thread: the token
endpoint issues tokens for codes and refresh tokens, and the API records whose
token each request carried. Every test reads that record, since a call that
"worked" with the wrong person's token is the failure this unit exists for.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import sys
import threading
import time
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import connections as conn_routes  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services import outbound_apps  # noqa: E402
from src.services.secrets import InMemorySecretsGateway  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

PUBLIC = "http://platform.example.test"


class Server:
    def __init__(self) -> None:
        self.codes: dict[str, dict] = {}
        self.refresh_ok = True
        self.seen: list[str] = []       # the bearer each API request carried
        self.grants: list[dict] = []    # each token request's form

    def issue(self, authorize_url: str) -> tuple[str, str]:
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(authorize_url).query))
        code = uuid.uuid4().hex
        self.codes[code] = {"challenge": query["code_challenge"]}
        return code, query["state"]


@pytest.fixture(scope="module")
def server():
    state = Server()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

        def _json(self, status: int, body) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            self._api()

        def do_POST(self) -> None:
            if self.path.startswith("/token"):
                return self._token()
            self._api()

        def _api(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            bearer = self.headers.get("Authorization", "")
            state.seen.append(bearer)
            if not bearer.startswith("Bearer at-"):
                return self._json(401, {"error": "unauthorized"})
            self._json(200, [{"id": 1, "who": bearer.split("at-", 1)[1]}])

        def _token(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            form = dict(urllib.parse.parse_qsl(self.rfile.read(length).decode()))
            state.grants.append(form)
            if form.get("grant_type") == "authorization_code":
                issued = state.codes.pop(form.get("code", ""), None)
                verifier = form.get("code_verifier", "")
                challenge = base64.urlsafe_b64encode(
                    hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
                if issued is None or issued["challenge"] != challenge:
                    return self._json(400, {"error": "invalid_grant"})
                who = form["code"][:6]
                return self._json(200, {"access_token": f"at-{who}", "refresh_token": f"rt-{who}",
                                        "expires_in": 3600})
            if form.get("grant_type") == "refresh_token" and state.refresh_ok:
                who = form["refresh_token"].split("rt-", 1)[1]
                # No refresh_token in the answer: RFC 6749 §6's "keep yours".
                return self._json(200, {"access_token": f"at-{who}-renewed", "expires_in": 3600})
            self._json(400, {"error": "invalid_grant"})

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    state.base = f"http://127.0.0.1:{httpd.server_port}"
    yield state
    httpd.shutdown()


@pytest.fixture(autouse=True)
def _public(monkeypatch) -> None:
    monkeypatch.setenv("PLATFORM_PUBLIC_URL", PUBLIC)


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def gateway() -> InMemorySecretsGateway:
    return InMemorySecretsGateway()


@pytest.fixture(scope="module")
def client(gateway, tmp_path_factory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    conn_routes.configure_secrets_gateway(gateway)
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("outbound-calls"))))
    with TestClient(create_app(), raise_server_exceptions=True, follow_redirects=False) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh(client) -> None:
    auth_mw.clear_identity_cache()
    client.cookies.clear()


def pbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


@pytest.fixture()
def source(client, fx, server) -> str:
    r = client.post(f"{pbase(fx)}/connections", headers=hdr(fx.editor_sub), json={
        "name": f"Helpdesk {uuid.uuid4().hex[:6]}", "source_type": "rest",
        "config": {"base_url": server.base + "/api", "resource_path": "tickets",
                   "allow_insecure_http": True, "auth_type": "oauth2_authorization_code",
                   "authorize_url": server.base + "/authorize",
                   "token_url": server.base + "/token"},
        "secret": {"client_id": "anchor-app", "client_secret": "s3cret"}})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def authorize(client, fx, server, cid: str, sub: str) -> str:
    """The whole flow as `sub`; returns the person's token label."""
    r = client.post(f"{pbase(fx)}/connections/{cid}/authorization", headers=hdr(sub),
                    json={"return_to": "/"})
    assert r.status_code == 200, r.text
    code, state = server.issue(r.json()["authorize_url"])
    r = client.get("/api/oauth/callback?" + urllib.parse.urlencode({"code": code, "state": state}))
    assert r.status_code == 303 and "granted" in r.headers["location"], r.text
    client.cookies.clear()
    return code[:6]


def try_source(client, fx, cid: str, sub: str):
    return client.post(f"{pbase(fx)}/connections/{cid}/test", headers=hdr(sub))


# ---- reads on the source -----------------------------------------------------------------
def test_a_read_is_made_with_the_callers_own_token(client, fx, server, source) -> None:
    mine = authorize(client, fx, server, source, fx.editor_sub)
    r = try_source(client, fx, source, fx.editor_sub)
    assert r.status_code == 200 and r.json()["ok"], r.text
    assert server.seen[-1] == f"Bearer at-{mine}"


def test_two_people_call_as_themselves(client, fx, server, source) -> None:
    editor = authorize(client, fx, server, source, fx.editor_sub)
    admin = authorize(client, fx, server, source, fx.admin_sub)
    try_source(client, fx, source, fx.admin_sub)
    assert server.seen[-1] == f"Bearer at-{admin}"
    try_source(client, fx, source, fx.editor_sub)
    assert server.seen[-1] == f"Bearer at-{editor}"


def test_someone_who_has_not_authorized_is_told_to(client, fx, server, source) -> None:
    """p.40: "The user invoking the function has completed the interactive
    authorization flow at least once." Nobody else's grant stands in."""
    authorize(client, fx, server, source, fx.editor_sub)
    before = len(server.seen)
    r = try_source(client, fx, source, fx.admin_sub)
    body = r.json()
    assert body["ok"] is False and "you have not authorized this source" in body["error"], body
    assert len(server.seen) == before, "nothing was sent"


def test_preview_and_sync_now_are_made_as_the_person_too(client, fx, server, source) -> None:
    mine = authorize(client, fx, server, source, fx.editor_sub)
    r = client.post(f"{pbase(fx)}/connections/{source}/sync", headers=hdr(fx.editor_sub),
                    json={"source_table": "tickets", "dataset_name": f"Tickets {uuid.uuid4().hex[:4]}"})
    assert r.status_code == 200 and r.json()["ok"], r.text
    assert server.seen[-1] == f"Bearer at-{mine}"
    r = client.post(f"{pbase(fx)}/connections/{source}/sync", headers=hdr(fx.admin_sub),
                    json={"source_table": "tickets", "dataset_name": f"Tickets {uuid.uuid4().hex[:4]}"})
    assert r.json()["ok"] is False and "you have not authorized" in r.json()["error"], r.text


# ---- an expiring grant ------------------------------------------------------------------
def _expire(gateway, cid: str, user) -> None:
    arn = f"local:secret:anchor/connections/{cid}/grants/{user}"
    values = gateway.get_secret(arn)
    values["expires_at"] = str(int(time.time()) - 5)
    gateway._store[arn] = values


def test_a_lapsing_token_is_renewed_first(client, fx, server, source, gateway) -> None:
    """RFC 6749 §6, and p.40's "refresh handler": renewed before it is sent,
    and a renewal that leaves the refresh token out keeps the one held."""
    mine = authorize(client, fx, server, source, fx.editor_sub)
    _expire(gateway, source, fx.editor)
    r = try_source(client, fx, source, fx.editor_sub)
    assert r.json()["ok"], r.text
    assert server.grants[-1]["grant_type"] == "refresh_token"
    assert server.grants[-1]["refresh_token"] == f"rt-{mine}"
    assert server.grants[-1]["client_secret"] == "s3cret"
    assert server.seen[-1] == f"Bearer at-{mine}-renewed"
    held = gateway.get_secret(f"local:secret:anchor/connections/{source}/grants/{fx.editor}")
    assert held["refresh_token"] == f"rt-{mine}" and int(held["expires_at"]) > time.time()


def test_a_renewal_the_server_refuses_forgets_the_grant(client, fx, server, source, gateway) -> None:
    """p.40: "Credentials expired and no refresh handler provided … The user
    must … complete the authorization flow again." """
    authorize(client, fx, server, source, fx.editor_sub)
    _expire(gateway, source, fx.editor)
    server.refresh_ok = False
    try:
        r = try_source(client, fx, source, fx.editor_sub)
    finally:
        server.refresh_ok = True
    assert "has expired and could not be renewed" in r.json()["error"], r.text
    mine = client.get(f"{pbase(fx)}/connections/{source}/authorization",
                      headers=hdr(fx.editor_sub)).json()
    assert mine["authorized"] is False


def test_a_lapsed_token_with_nothing_to_renew_it_is_said(client, fx, server, source, gateway) -> None:
    authorize(client, fx, server, source, fx.editor_sub)
    arn = f"local:secret:anchor/connections/{source}/grants/{fx.editor}"
    values = gateway.get_secret(arn)
    values.pop("refresh_token")
    values["expires_at"] = str(int(time.time()) - 5)
    gateway._store[arn] = values
    r = try_source(client, fx, source, fx.editor_sub)
    assert "has expired - authorize it again" in r.json()["error"], r.text


# ---- webhooks ---------------------------------------------------------------------------
def webhook(client, fx, source: str) -> dict:
    r = client.post(f"{pbase(fx)}/webhooks", headers=hdr(fx.editor_sub), json={
        "connection_id": source, "api_name": f"hook_{uuid.uuid4().hex[:8]}",
        "display_name": "Open a ticket", "method": "POST", "path": "tickets"})
    assert r.status_code == 201, r.text
    return r.json()


def test_a_webhook_is_called_as_the_person_running_it(client, fx, server, source) -> None:
    """p.243: individual users authenticate "when attempting to execute the
    Webhook"."""
    hook = webhook(client, fx, source)
    mine = authorize(client, fx, server, source, fx.editor_sub)
    r = client.post(f"{pbase(fx)}/webhooks/{hook['id']}/test", headers=hdr(fx.editor_sub),
                    json={"values": {}})
    assert r.status_code == 200 and r.json()["ok"] is True, r.text
    assert server.seen[-1] == f"Bearer at-{mine}"


def test_a_webhook_run_by_someone_unauthorized_is_a_recorded_failure(
    client, fx, server, source
) -> None:
    hook = webhook(client, fx, source)
    authorize(client, fx, server, source, fx.editor_sub)
    before = len(server.seen)
    r = client.post(f"{pbase(fx)}/webhooks/{hook['id']}/test", headers=hdr(fx.admin_sub),
                    json={"values": {}})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is False
    assert "you have not authorized this source" in r.json()["error"]
    assert len(server.seen) == before


def test_an_action_rule_calls_the_webhook_as_the_person_who_ran_the_action(
    client, fx, server, source
) -> None:
    hook = webhook(client, fx, source)
    mine = authorize(client, fx, server, source, fx.editor_sub)
    wbase = f"/api/workspaces/{fx.workspace}"
    type_id = client.post(f"{wbase}/object-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"Ticket{uuid.uuid4().hex[:6]}", "display_name": "Ticket",
        "properties": [{"api_name": "priority", "data_type": "string"}]}).json()["id"]
    upload = client.post(f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
                         data={"name": f"Tickets {uuid.uuid4().hex[:6]}"},
                         files={"file": ("t.csv", io.BytesIO(b"ticket_id,priority\nT1,low\n"),
                                         "text/csv")})
    src = client.post(f"{pbase(fx)}/object-type-sources", headers=hdr(fx.editor_sub), json={
        "object_type_id": type_id, "dataset_id": upload.json()["id"],
        "primary_key_column": "ticket_id", "column_mappings": {"priority": "priority"}})
    client.post(f"{pbase(fx)}/object-type-sources/{src.json()['id']}/sync",
                headers=hdr(fx.editor_sub))
    instance = client.get(f"{wbase}/object-types/{type_id}/instances",
                          headers=hdr(fx.viewer_sub)).json()["items"][0]["id"]
    action = client.post(f"{wbase}/action-types", headers=hdr(fx.editor_sub), json={
        "object_type_id": type_id, "api_name": f"a_{uuid.uuid4().hex[:6]}",
        "display_name": "Escalate", "editable_properties": ["priority"]}).json()
    r = client.put(f"{wbase}/action-types/{action['id']}/definition", headers=hdr(fx.editor_sub),
                   json={"parameters": [{"api_name": "priority", "display_name": "Priority",
                                         "data_type": "string"}],
                         "rules": [{"kind": "modify_object",
                                    "config": {"property": "priority", "parameter": "priority"}},
                                   {"kind": "webhook",
                                    "config": {"webhook": hook["id"], "mode": "side_effect",
                                               "inputs": {}}}],
                         "criteria": []})
    assert r.status_code == 200, r.text
    r = client.post(f"{pbase(fx)}/actions/{action['id']}/execute", headers=hdr(fx.editor_sub),
                    json={"instance_id": instance, "values": {"priority": "high"}})
    assert r.status_code == 200, r.text
    assert server.seen[-1] == f"Bearer at-{mine}"


# ---- a schedule has no person -----------------------------------------------------------
def test_a_schedule_on_such_a_source_is_refused_when_it_is_set(client, fx, source) -> None:
    """Decision 0022 §4: refused when set, not every time it fires."""
    r = client.put(f"{pbase(fx)}/connections/{source}/scheduled-sync",
                   headers=hdr(fx.editor_sub),
                   json={"mode": "full", "source_table": "tickets", "cron_schedule": "0 * * * *"})
    assert r.status_code == 422 and "a schedule has no person to call it as" in r.text, r.text
    r = client.put(f"{pbase(fx)}/connections/{source}/scheduled-sync",
                   headers=hdr(fx.editor_sub), json={"mode": "full", "source_table": "tickets"})
    assert r.status_code == 200, r.text


def test_a_source_without_an_application_is_untouched(client, fx, server) -> None:
    """Every other auth type sends what it always sent."""
    r = client.post(f"{pbase(fx)}/connections", headers=hdr(fx.editor_sub), json={
        "name": f"Keyed {uuid.uuid4().hex[:6]}", "source_type": "rest",
        "config": {"base_url": server.base + "/api", "resource_path": "tickets",
                   "allow_insecure_http": True, "auth_type": "bearer"},
        "secret": {"api_key": "at-static"}})
    try_source(client, fx, r.json()["id"], fx.admin_sub)
    assert server.seen[-1] == "Bearer at-static"
    assert outbound_apps.is_outbound({"auth_type": "bearer"}) is False


def test_diagnose_names_a_missing_authorization(client, fx, server, source) -> None:
    """p.31's fifth check: "Check OAuth authorization. If your source uses an
    outbound application, HTTP 401: Unauthorized and similar errors usually
    indicate that the calling user has not completed the interactive
    authorization flow"."""
    r = client.post(f"{pbase(fx)}/connections/{source}/diagnose", headers=hdr(fx.admin_sub))
    assert r.status_code == 200, r.text
    steps = {s["name"]: s for s in r.json()["steps"]}
    assert steps["credentials"]["status"] == "failed"
    assert "you have not authorized this source" in steps["credentials"]["detail"]
    mine = authorize(client, fx, server, source, fx.editor_sub)
    r = client.post(f"{pbase(fx)}/connections/{source}/diagnose", headers=hdr(fx.editor_sub))
    steps = {s["name"]: s for s in r.json()["steps"]}
    assert steps["credentials"]["status"] == "ok", steps
    assert server.seen[-1] == f"Bearer at-{mine}"


def test_a_webhook_on_a_source_without_an_application_needs_no_grant(
    client, fx, server
) -> None:
    r = client.post(f"{pbase(fx)}/connections", headers=hdr(fx.editor_sub), json={
        "name": f"Keyed {uuid.uuid4().hex[:6]}", "source_type": "rest",
        "config": {"base_url": server.base + "/api", "allow_insecure_http": True,
                   "auth_type": "bearer"},
        "secret": {"api_key": "at-static"}})
    hook = webhook(client, fx, r.json()["id"])
    r = client.post(f"{pbase(fx)}/webhooks/{hook['id']}/test", headers=hdr(fx.admin_sub),
                    json={"values": {}})
    assert r.json()["ok"] is True, r.text
    assert server.seen[-1] == "Bearer at-static"
