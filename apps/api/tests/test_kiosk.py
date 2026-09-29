"""Kiosk mode (§684; `workshop` p.610-612).

> "Kiosk mode sessions are read-only, meaning that Ontology write backs such as
> object edits and creations may not be triggered, and have scoped down
> permissions limiting the content viewable within a session." (p.610)

The claims worth testing hardest are the refusals, because a kiosk screen is
left unattended in public: a session that only looked scoped would be the
worst kind of control that looks like it works. So a session is launched here
and then used as an attacker at that screen would use it - asking for what the
module never named, writing, and leaving its workspace - and each is refused
by the API, not by a page.
"""
from __future__ import annotations

import os
import sys
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.services import kiosk as kiosk_service  # noqa: E402

ADMIN_DSN = os.environ["TEST_ADMIN_DSN"]


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client() -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    with TestClient(create_app(), raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


def pbase(fx: Fixture) -> str:
    return f"{wbase(fx)}/projects/{fx.project}"


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def declare(client: TestClient, fx: Fixture, api_name: str) -> str:
    r = client.post(f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub), json={
        "api_name": api_name, "display_name": api_name.replace("_", " ").title(),
        "properties": [{"api_name": "name", "data_type": "string"}]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def module(client: TestClient, fx: Fixture, document: dict, *, publish: bool = True) -> str:
    r = client.post(f"{pbase(fx)}/canvas-apps", headers=hdr(fx.editor_sub),
                    json={"name": f"Kiosk {uuid.uuid4().hex[:8]}"})
    assert r.status_code == 201, r.text
    app_id = r.json()["id"]
    r = client.put(f"{pbase(fx)}/canvas-apps/{app_id}/definition", headers=hdr(fx.editor_sub),
                   json={"definition": document})
    assert r.status_code == 200, r.text
    if publish:
        r = client.put(f"{pbase(fx)}/canvas-apps/{app_id}/publish", headers=hdr(fx.admin_sub),
                       json={"scope": "workspace"})
        assert r.status_code == 200, r.text
    return app_id


def document(shown: str, *, kiosk: bool = True, embeds: str | None = None) -> dict:
    nodes = {
        "ROOT": {"type": "Container", "nodes": ["t"] + (["e"] if embeds else [])},
        "t": {"type": {"resolvedName": "CanvasObjectTable"}, "props": {"objectTypeId": shown}},
    }
    if embeds:
        nodes["e"] = {"type": {"resolvedName": "CanvasEmbeddedModule"},
                      "props": {"moduleId": embeds}}
    return {"format": 2, "variables": {}, "events": {}, "layout": nodes,
            **({"kiosk": {"enabled": True}} if kiosk else {})}


def allow(client: TestClient, fx: Fixture, app_id: str) -> None:
    r = client.put(f"/api/org/kiosk/modules/{app_id}", headers=hdr(fx.admin_sub))
    assert r.status_code == 204, r.text


def launch(client: TestClient, fx: Fixture, app_id: str, sub: str | None = None):
    return client.post(f"{wbase(fx)}/published-canvas-apps/{app_id}/kiosk-sessions",
                       headers=hdr(sub or fx.editor_sub))


@pytest.fixture(scope="module")
def world(client: TestClient, fx: Fixture) -> dict:
    tag = uuid.uuid4().hex[:6]
    shown = declare(client, fx, f"kiosk_shown_{tag}")
    hidden = declare(client, fx, f"kiosk_hidden_{tag}")
    inner = module(client, fx, document(shown, kiosk=False))
    app_id = module(client, fx, document(shown, embeds=inner))
    allow(client, fx, app_id)
    r = launch(client, fx, app_id)
    assert r.status_code == 201, r.text
    return {"shown": shown, "hidden": hidden, "app": app_id, "inner": inner, **r.json()}


# ---- pure ----------------------------------------------------------------------------
def test_only_reads_in_its_own_workspace_pass() -> None:
    ws = str(uuid.uuid4())
    base = f"/api/workspaces/{ws}"
    assert kiosk_service.refusal("GET", f"{base}/object-types", ws) is None
    assert kiosk_service.refusal("HEAD", f"{base}/object-types", ws) is None
    assert kiosk_service.refusal("GET", base, ws) is None
    assert kiosk_service.refusal("POST", f"{base}/object-sets/evaluate", ws) is None
    assert kiosk_service.refusal("POST", f"{base}/published-canvas-apps/x/variables/evaluate", ws) is None
    assert kiosk_service.refusal("POST", "/api/kiosk/end", ws) is None
    assert kiosk_service.refusal("GET", "/api/auth/me", ws) is None
    assert "own module's workspace" in kiosk_service.refusal("POST", "/api/auth/logout", ws)
    assert "read-only" in kiosk_service.refusal("POST", f"{base}/object-types", ws)
    assert "read-only" in kiosk_service.refusal("PUT", f"{base}/object-sets/evaluate", ws)
    assert "read-only" in kiosk_service.refusal("POST", f"{base}/object-sets/evaluate/x", ws)
    assert "read-only" in kiosk_service.refusal(
        "POST", f"{base}/projects/p/actions/a/execute", ws)
    assert "own module's workspace" in kiosk_service.refusal("GET", "/api/workspaces", ws)
    assert "own module's workspace" in kiosk_service.refusal(
        "GET", f"/api/workspaces/{uuid.uuid4()}/object-types", ws)
    assert "own module's workspace" in kiosk_service.refusal("GET", f"{base}x/object-types", ws)
    assert "own module's workspace" in kiosk_service.refusal("GET", "/api/org/kiosk/sessions", ws)


def test_the_scope_is_what_the_module_names_and_the_modules_it_embeds() -> None:
    app, shown, inner = uuid.uuid4(), str(uuid.uuid4()), str(uuid.uuid4())
    scope = kiosk_service.scope_of(app, document(shown, embeds=inner))
    assert scope == {"object_types": [shown], "link_types": [], "action_types": [],
                     "apps": sorted([str(app), inner])}
    assert kiosk_service.settings_for(scope) == {
        "app.kiosk": "on", "app.kiosk_object_types": "{" + shown + "}",
        "app.kiosk_link_types": "", "app.kiosk_action_types": "",
        "app.kiosk_apps": "{" + ",".join(sorted([str(app), inner])) + "}"}
    assert kiosk_service.scope_of(app, "not a document")["apps"] == [str(app)]


def test_a_credential_is_long_random_and_stored_as_its_hash() -> None:
    a, b = kiosk_service.new_token(), kiosk_service.new_token()
    assert a != b and a.startswith("kiosk_") and len(a) > 40
    assert len(kiosk_service.hash_token(a)) == 64 and kiosk_service.hash_token(a) != a


# ---- launching (p.610's modal) ---------------------------------------------------------
def test_the_modal_says_what_will_be_visible(client: TestClient, fx: Fixture, world: dict) -> None:
    r = client.get(f"{wbase(fx)}/published-canvas-apps/{world['app']}/kiosk",
                   headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is True and body["reason"] is None
    assert [e["id"] for e in body["scope"]["object_types"]] == [world["shown"]]
    assert body["scope"]["object_types"][0]["name"].startswith("Kiosk Shown")
    assert {e["id"] for e in body["scope"]["apps"]} == {world["app"], world["inner"]}


def test_a_launch_needs_the_setting_the_allowlist_and_a_builder(
    client: TestClient, fx: Fixture, world: dict,
) -> None:
    off = module(client, fx, document(world["shown"], kiosk=False))
    allow(client, fx, off)
    unlisted = module(client, fx, document(world["shown"]))
    for app_id, sub, reason in (
        (off, fx.editor_sub, "not turned on"),
        (unlisted, fx.editor_sub, "allowlist"),
        (world["app"], fx.viewer_sub, "builders"),
    ):
        r = client.get(f"{wbase(fx)}/published-canvas-apps/{app_id}/kiosk", headers=hdr(sub))
        assert r.status_code == 200, r.text
        assert r.json()["available"] is False and reason in r.json()["reason"]
        r = launch(client, fx, app_id, sub)
        assert r.status_code == 409 and reason in r.text, r.text
    # Taken off the allowlist, the module cannot be launched again.
    r = client.delete(f"/api/org/kiosk/modules/{off}", headers=hdr(fx.admin_sub))
    assert r.status_code == 204
    listed = client.get("/api/org/kiosk/modules", headers=hdr(fx.admin_sub)).json()
    assert world["app"] in {m["app_id"] for m in listed} and off not in {m["app_id"] for m in listed}


def test_the_allowlist_is_an_administrator_s(client: TestClient, fx: Fixture, world: dict) -> None:
    for path, method in (("/api/org/kiosk/modules", "get"),
                         (f"/api/org/kiosk/modules/{world['app']}", "put"),
                         ("/api/org/kiosk/sessions", "get")):
        r = getattr(client, method)(path, headers=hdr(fx.editor_sub))
        assert r.status_code == 403, (path, r.text)


# ---- the session (p.610-611) ---------------------------------------------------------
def test_the_session_sees_its_module_and_what_it_names(
    client: TestClient, fx: Fixture, world: dict,
) -> None:
    token = world["token"]
    r = client.get(f"{wbase(fx)}/published-canvas-apps/{world['app']}", headers=bearer(token))
    assert r.status_code == 200, r.text
    r = client.get(f"{wbase(fx)}/published-canvas-apps/{world['inner']}", headers=bearer(token))
    assert r.status_code == 200, r.text
    r = client.get(f"{wbase(fx)}/object-types/{world['shown']}", headers=bearer(token))
    assert r.status_code == 200, r.text
    r = client.post(f"{wbase(fx)}/object-sets/evaluate", headers=bearer(token),
                    json={"definition": {"object_type_id": world["shown"], "filters": []}})
    assert r.status_code == 200, r.text
    r = client.get("/api/kiosk/current", headers=bearer(token))
    assert r.json()["app_id"] == world["app"]


def test_what_the_module_never_named_is_not_there(
    client: TestClient, fx: Fixture, world: dict,
) -> None:
    """p.611's scope, by the database: the launcher can see the hidden type,
    and the session they launched cannot."""
    token = world["token"]
    r = client.get(f"{wbase(fx)}/object-types/{world['hidden']}", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, "the launcher can"
    r = client.get(f"{wbase(fx)}/object-types/{world['hidden']}", headers=bearer(token))
    assert r.status_code == 404, r.text
    r = client.post(f"{wbase(fx)}/object-sets/evaluate", headers=bearer(token),
                    json={"definition": {"object_type_id": world["hidden"], "filters": []}})
    assert r.status_code in (404, 422), r.text
    listed = client.get(f"{wbase(fx)}/object-types", headers=bearer(token)).json()
    ids = {t["id"] for t in (listed["items"] if isinstance(listed, dict) else listed)}
    assert ids == {world["shown"]}
    other = module(client, fx, document(world["shown"]))
    r = client.get(f"{wbase(fx)}/published-canvas-apps/{other}", headers=bearer(token))
    assert r.status_code == 404, r.text


def test_the_session_writes_nothing_and_stays_in_its_workspace(
    client: TestClient, fx: Fixture, world: dict,
) -> None:
    token = world["token"]
    for method, path, body in (
        ("post", f"{wbase(fx)}/object-types", {"api_name": "x", "display_name": "X",
                                                "properties": []}),
        ("put", f"{pbase(fx)}/canvas-apps/{world['app']}/definition", {"definition": {}}),
        ("post", f"{wbase(fx)}/published-canvas-apps/{world['app']}/states",
         {"name": "s", "values": {}}),
        ("post", f"{wbase(fx)}/published-canvas-apps/{world['app']}/kiosk-sessions", None),
    ):
        r = getattr(client, method)(path, headers=bearer(token), **({"json": body} if body else {}))
        assert r.status_code == 403 and "read-only" in r.text, (path, r.text)
    for path in ("/api/workspaces", "/api/org/kiosk/sessions", "/api/org"):
        r = client.get(path, headers=bearer(token))
        assert r.status_code == 403 and "own module's workspace" in r.text, (path, r.text)


def test_a_session_ends_from_the_screen_or_from_control_panel(
    client: TestClient, fx: Fixture, world: dict,
) -> None:
    listed = client.get("/api/org/kiosk/sessions", headers=hdr(fx.admin_sub)).json()
    mine = next(s for s in listed if s["id"] == world["session_id"])
    assert mine["active"] is True and mine["app_id"] == world["app"]

    # An administrator ends one from the launch history (p.611)…
    second = launch(client, fx, world["app"]).json()
    r = client.post(f"/api/org/kiosk/sessions/{second['session_id']}/end", headers=hdr(fx.admin_sub))
    assert r.status_code == 204, r.text
    r = client.get(f"{wbase(fx)}/object-types/{world['shown']}", headers=bearer(second["token"]))
    assert r.status_code == 401 and "ended" in r.text, r.text
    r = client.post(f"/api/org/kiosk/sessions/{second['session_id']}/end", headers=hdr(fx.admin_sub))
    assert r.status_code == 404, "an ended session is not ended twice"

    # …and the screen ends its own (p.610's Exit kiosk mode).
    third = launch(client, fx, world["app"]).json()
    r = client.post("/api/kiosk/end", headers=bearer(third["token"]))
    assert r.status_code == 204, r.text
    r = client.get("/api/kiosk/current", headers=bearer(third["token"]))
    assert r.status_code == 401, r.text
    # An ordinary session has no kiosk to end.
    assert client.post("/api/kiosk/end", headers=hdr(fx.editor_sub)).status_code == 403


def test_an_expired_or_unknown_credential_is_refused(
    client: TestClient, fx: Fixture, world: dict,
) -> None:
    fourth = launch(client, fx, world["app"]).json()
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE kiosk_sessions SET created_at = now() - interval '9 days',"
                     " expires_at = now() - interval '1 day' WHERE id = %s",
                     (fourth["session_id"],))
    r = client.get("/api/kiosk/current", headers=bearer(fourth["token"]))
    assert r.status_code == 401 and "ended" in r.text, r.text
    r = client.get("/api/kiosk/current", headers=bearer("kiosk_" + "x" * 43))
    assert r.status_code == 401 and "unknown" in r.text, r.text


def test_an_ordinary_request_is_not_scoped(client: TestClient, fx: Fixture, world: dict) -> None:
    """The settings are the request's, not the connection pool's: the next
    ordinary request after a kiosk one sees everything again."""
    client.get(f"{wbase(fx)}/object-types/{world['shown']}", headers=bearer(world["token"]))
    r = client.get(f"{wbase(fx)}/object-types/{world['hidden']}", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text


def test_an_administrator_adds_from_the_modules_they_can_see(
    client: TestClient, fx: Fixture, world: dict,
) -> None:
    r = client.get("/api/org/kiosk/candidates", headers=hdr(fx.admin_sub))
    assert r.status_code == 200, r.text
    assert world["app"] in {c["app_id"] for c in r.json()}
    assert client.get("/api/org/kiosk/candidates", headers=hdr(fx.editor_sub)).status_code == 403


def test_a_session_lasts_a_week(client: TestClient, fx: Fixture, world: dict) -> None:
    from datetime import datetime, timezone
    left = datetime.fromisoformat(world["expires_at"]) - datetime.now(timezone.utc)
    assert 6.9 < left.total_seconds() / 86400 <= 7


def test_only_a_module_that_exists_is_allowed(client: TestClient, fx: Fixture) -> None:
    r = client.put(f"/api/org/kiosk/modules/{uuid.uuid4()}", headers=hdr(fx.admin_sub))
    assert r.status_code == 404, r.text


def test_a_disabled_launcher_s_session_stops(client: TestClient, fx: Fixture, world: dict) -> None:
    """The session is the launcher's access, narrowed: when their account is
    disabled, so is every kiosk they launched."""
    fifth = launch(client, fx, world["app"]).json()
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE users SET status = 'disabled' WHERE id = %s", (fx.editor,))
    try:
        r = client.get("/api/kiosk/current", headers=bearer(fifth["token"]))
        assert r.status_code == 401 and "disabled" in r.text, r.text
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
            conn.execute("UPDATE users SET status = 'active' WHERE id = %s", (fx.editor,))
