"""API integration tests. Runs the real FastAPI app against the real local
Postgres (as the RLS-subject role) with genuine RS256 JWTs validated against
a locally generated JWKS - the production verification code path, different
only in where the public key comes from.

Covers the contract from the build brief and spec §9:
  * 401 without/with-invalid token
  * 404 (never 403) for resources outside the user's access
  * role floors: viewer cannot write, editor cannot admin
  * org admin full access; project custom mode incl. 'none' revocation
  * cross-org invisibility
  * audit entries written atomically with mutations
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from typing import Any

import jwt as pyjwt
import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ADMIN_DSN = os.environ["TEST_ADMIN_DSN"]      # role: platform (owner) - fixtures only
APP_DSN = os.environ["DATABASE_URL"]          # role: platform_app - what the API uses

os.environ.setdefault("COGNITO_CLIENT_ID", "test-client")
os.environ.setdefault("COGNITO_ISSUER", "https://test-issuer.local")
# TestClient speaks http://testserver, and a Secure cookie is not sent over
# http - so with the production default the session cookie would be set and
# then never come back, and every cookie test would fail for a reason that has
# nothing to do with what it is testing. Set here rather than defaulted to
# False in config.py: a non-Secure session cookie in production is a token on
# the wire, and that must take a deliberate act to turn off.
os.environ.setdefault("SESSION_COOKIE_SECURE", "false")

from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402

# ---- test token infrastructure ----------------------------------------------
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_ISSUER = "https://test-issuer.local"
_CLIENT = "test-client"


class LocalVerifier:
    """Same claim checks as CognitoTokenVerifier, keyed to the test keypair."""

    def verify(self, token: str) -> dict[str, Any]:
        from src.lib.errors import UnauthorizedError

        try:
            claims: dict[str, Any] = pyjwt.decode(
                token,
                _KEY.public_key(),
                algorithms=["RS256"],
                issuer=_ISSUER,
                options={"require": ["exp", "iss", "sub"], "verify_exp": True},
            )
        except pyjwt.PyJWTError as exc:
            raise UnauthorizedError(f"invalid token: {type(exc).__name__}") from exc
        if claims.get("token_use") == "access":
            if claims.get("client_id") != _CLIENT:
                raise UnauthorizedError("token client mismatch")
        else:
            raise UnauthorizedError("unrecognised token_use")
        return claims


def mint(sub: str, *, expired: bool = False, wrong_client: bool = False) -> str:
    now = int(time.time())
    return pyjwt.encode(
        {
            "sub": sub,
            "iss": _ISSUER,
            "token_use": "access",
            "client_id": "other" if wrong_client else _CLIENT,
            "iat": now - 3600 if expired else now,
            "exp": now - 1800 if expired else now + 900,
        },
        _KEY,
        algorithm="RS256",
    )


# ---- fixtures ---------------------------------------------------------------
class Fixture:
    """One org with one workspace + project and users at each level, plus a
    second org for cross-tenant checks. Built with the owner role; the API
    itself only ever connects as platform_app."""

    def __init__(self) -> None:
        tag = uuid.uuid4().hex[:8]
        self.tag = tag
        with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
            def one(sql: str, params: tuple[Any, ...]) -> Any:
                cur = conn.execute(sql, params)
                row = cur.fetchone()
                return row[0] if row else None

            self.org = one(
                "INSERT INTO organisations (name, slug) VALUES (%s,%s) RETURNING id",
                (f"TestOrg {tag}", f"testorg-{tag}"),
            )
            self.other_org = one(
                "INSERT INTO organisations (name, slug) VALUES (%s,%s) RETURNING id",
                (f"OtherOrg {tag}", f"otherorg-{tag}"),
            )

            def user(email: str, role: str, org: Any) -> tuple[Any, str]:
                sub = f"sub-{email.split('@')[0]}-{tag}"
                uid = one(
                    """INSERT INTO users (organisation_id, email, display_name,
                                          org_role, cognito_sub, status)
                       VALUES (%s,%s,%s,%s,%s,'active') RETURNING id""",
                    (org, email, email.split("@")[0], role, sub),
                )
                return uid, sub

            self.owner, self.owner_sub = user(f"owner-{tag}@example.com", "owner", self.org)
            self.admin, self.admin_sub = user(f"admin-{tag}@example.com", "admin", self.org)
            self.editor, self.editor_sub = user(f"editor-{tag}@example.com", "member", self.org)
            self.viewer, self.viewer_sub = user(f"viewer-{tag}@example.com", "member", self.org)
            self.outsider, self.outsider_sub = user(f"out-{tag}@example.com", "member", self.org)
            self.foreign, self.foreign_sub = user(f"foreign-{tag}@example.org", "owner", self.other_org)

            wid = uuid.uuid4()
            self.workspace = one(
                """INSERT INTO workspaces (id, organisation_id, name, slug, s3_prefix,
                                           pg_schema, search_prefix, created_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (wid, self.org, f"WS {tag}", f"ws-{tag}", f"workspaces/ws-{tag}/",
                 f"ws_{wid.hex[:12]}", f"ws-{wid.hex[:12]}-", self.owner),
            )
            conn.execute(
                "INSERT INTO workspace_members (workspace_id, user_id, role) VALUES (%s,%s,'editor')",
                (self.workspace, self.editor),
            )
            conn.execute(
                "INSERT INTO workspace_members (workspace_id, user_id, role) VALUES (%s,%s,'viewer')",
                (self.workspace, self.viewer),
            )
            self.project = one(
                """INSERT INTO projects (workspace_id, name, slug, created_by)
                   VALUES (%s,%s,%s,%s) RETURNING id""",
                (self.workspace, f"Proj {tag}", f"proj-{tag}", self.owner),
            )


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client() -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def hdr(sub: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint(sub)}"}


# ---- auth -------------------------------------------------------------------
def test_no_token_is_401(client: TestClient) -> None:
    assert client.get("/api/auth/me").status_code == 401


def test_expired_token_is_401(client: TestClient, fx: Fixture) -> None:
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {mint(fx.viewer_sub, expired=True)}"})
    assert r.status_code == 401


def test_wrong_client_is_401(client: TestClient, fx: Fixture) -> None:
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {mint(fx.viewer_sub, wrong_client=True)}"})
    assert r.status_code == 401


def test_tampered_signature_is_401(client: TestClient, fx: Fixture) -> None:
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = pyjwt.encode(
        {"sub": fx.viewer_sub, "iss": _ISSUER, "token_use": "access",
         "client_id": _CLIENT, "exp": int(time.time()) + 900},
        other, algorithm="RS256",
    )
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_unprovisioned_sub_is_401(client: TestClient) -> None:
    assert client.get("/api/auth/me", headers=hdr("sub-nobody")).status_code == 401


def test_me_returns_identity_without_secrets(client: TestClient, fx: Fixture) -> None:
    r = client.get("/api/auth/me", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200
    body = r.json()
    assert body["org_role"] == "member"
    assert "cognito_sub" not in body and "token" not in str(body).lower()


# ---- workspace visibility & roles ------------------------------------------
def test_workspace_list_shows_only_accessible(client: TestClient, fx: Fixture) -> None:
    r = client.get("/api/workspaces", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200
    ids = [w["id"] for w in r.json()]
    assert str(fx.workspace) in ids
    r = client.get("/api/workspaces", headers=hdr(fx.outsider_sub))
    assert str(fx.workspace) not in [w["id"] for w in r.json()]


def test_inaccessible_workspace_is_404_not_403(client: TestClient, fx: Fixture) -> None:
    r = client.get(f"/api/workspaces/{fx.workspace}", headers=hdr(fx.outsider_sub))
    assert r.status_code == 404  # spec §9: does not exist for this user
    r = client.get(f"/api/workspaces/{fx.workspace}", headers=hdr(fx.foreign_sub))
    assert r.status_code == 404  # cross-org: same story


def test_org_admin_sees_all_workspaces(client: TestClient, fx: Fixture) -> None:
    r = client.get(f"/api/workspaces/{fx.workspace}", headers=hdr(fx.admin_sub))
    assert r.status_code == 200
    assert r.json()["effective_role"] == "admin"


def test_viewer_cannot_update_workspace(client: TestClient, fx: Fixture) -> None:
    r = client.patch(
        f"/api/workspaces/{fx.workspace}", headers=hdr(fx.viewer_sub), json={"name": "nope"}
    )
    assert r.status_code == 403  # visible but insufficient → 403


def test_member_cannot_create_workspace(client: TestClient, fx: Fixture) -> None:
    r = client.post("/api/workspaces", headers=hdr(fx.viewer_sub), json={"name": "X"})
    assert r.status_code == 403


def test_org_admin_creates_workspace_with_isolation(client: TestClient, fx: Fixture) -> None:
    name = f"Made By API {fx.tag}"
    r = client.post("/api/workspaces", headers=hdr(fx.admin_sub), json={"name": name})
    assert r.status_code == 201, r.text
    body = r.json()
    assert "s3_prefix" not in body  # anchors are internal
    with psycopg.connect(ADMIN_DSN) as conn:
        row = conn.execute(
            "SELECT pg_schema FROM workspaces WHERE id = %s", (body["id"],)
        ).fetchone()
        assert row is not None
        schema_exists = conn.execute(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name = %s", (row[0],)
        ).fetchone()
        assert schema_exists is not None  # provision_workspace_schema ran atomically


# ---- projects ---------------------------------------------------------------
def test_viewer_lists_but_cannot_create_project(client: TestClient, fx: Fixture) -> None:
    base = f"/api/workspaces/{fx.workspace}/projects"
    assert client.get(base, headers=hdr(fx.viewer_sub)).status_code == 200
    r = client.post(base, headers=hdr(fx.viewer_sub), json={"name": "nope"})
    assert r.status_code == 403


def test_editor_creates_project(client: TestClient, fx: Fixture) -> None:
    base = f"/api/workspaces/{fx.workspace}/projects"
    r = client.post(base, headers=hdr(fx.editor_sub), json={"name": f"EProj {fx.tag}"})
    assert r.status_code == 201, r.text
    assert r.json()["effective_role"] == "editor"


def test_project_under_wrong_workspace_is_404(client: TestClient, fx: Fixture) -> None:
    # Correct project id, wrong workspace id in the path → hierarchy check 404s.
    r = client.get(
        f"/api/workspaces/{uuid.uuid4()}/projects/{fx.project}", headers=hdr(fx.admin_sub)
    )
    assert r.status_code == 404


def test_project_detail_has_sidebar_counts(client: TestClient, fx: Fixture) -> None:
    r = client.get(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}", headers=hdr(fx.viewer_sub)
    )
    assert r.status_code == 200
    counts = r.json()["resource_counts"]
    assert set(counts) == {"connections", "datasets", "models", "objects", "canvas", "code"}


def test_custom_mode_none_revokes_and_404s(client: TestClient, fx: Fixture) -> None:
    base = f"/api/workspaces/{fx.workspace}/projects/{fx.project}"
    # Owner flips project to custom mode and grants editor a role, viewer none.
    r = client.patch(base, headers=hdr(fx.owner_sub), json={"permission_mode": "custom"})
    assert r.status_code == 200
    r = client.put(
        f"{base}/permissions", headers=hdr(fx.owner_sub),
        json={"user_id": str(fx.editor), "role": "editor"},
    )
    assert r.status_code == 201
    r = client.put(
        f"{base}/permissions", headers=hdr(fx.owner_sub),
        json={"user_id": str(fx.viewer), "role": "none"},
    )
    assert r.status_code == 201
    # Editor still in; viewer explicitly revoked → project vanishes (404).
    assert client.get(base, headers=hdr(fx.editor_sub)).status_code == 200
    assert client.get(base, headers=hdr(fx.viewer_sub)).status_code == 404
    # Org admin bypasses custom mode entirely (spec §4).
    r = client.get(base, headers=hdr(fx.admin_sub))
    assert r.status_code == 200 and r.json()["effective_role"] == "owner"
    # Restore inherited mode for later tests.
    assert client.patch(base, headers=hdr(fx.owner_sub),
                        json={"permission_mode": "inherited"}).status_code == 200


def test_editor_cannot_manage_permissions(client: TestClient, fx: Fixture) -> None:
    r = client.put(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/permissions",
        headers=hdr(fx.editor_sub),
        json={"user_id": str(fx.viewer), "role": "viewer"},
    )
    assert r.status_code == 403


# ---- org admin --------------------------------------------------------------
def test_non_admin_cannot_read_audit(client: TestClient, fx: Fixture) -> None:
    assert client.get("/api/org/audit", headers=hdr(fx.viewer_sub)).status_code == 403


def test_mutations_are_audited(client: TestClient, fx: Fixture) -> None:
    r = client.get("/api/org/audit", headers=hdr(fx.admin_sub))
    assert r.status_code == 200
    actions = {e["action"] for e in r.json()}
    assert {"workspace.create", "project.create", "project.permission.set"} <= actions
    # No secrets in any metadata blob (spec §10 tripwire).
    for entry in r.json():
        assert "password" not in str(entry["metadata"]).lower()


def test_admin_invites_user_and_no_credentials_returned(client: TestClient, fx: Fixture) -> None:
    r = client.post(
        "/api/org/members", headers=hdr(fx.admin_sub),
        json={"email": f"new-{fx.tag}@example.com", "display_name": "New Person", "org_role": "member"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert "cognito_sub" not in body and "password" not in str(body).lower()
    # Duplicate invite → 409.
    r = client.post(
        "/api/org/members", headers=hdr(fx.admin_sub),
        json={"email": f"new-{fx.tag}@example.com", "display_name": "Again", "org_role": "member"},
    )
    assert r.status_code == 409


def test_member_cannot_invite(client: TestClient, fx: Fixture) -> None:
    r = client.post(
        "/api/org/members", headers=hdr(fx.viewer_sub),
        json={"email": f"x-{fx.tag}@example.com", "display_name": "X", "org_role": "member"},
    )
    assert r.status_code == 403


def test_group_grant_flows_to_workspace(client: TestClient, fx: Fixture) -> None:
    r = client.post("/api/org/groups", headers=hdr(fx.admin_sub),
                    json={"name": f"Analysts {fx.tag}"})
    assert r.status_code == 201
    gid = r.json()["id"]
    assert client.put(f"/api/org/groups/{gid}/members/{fx.outsider}",
                      headers=hdr(fx.admin_sub)).status_code == 204
    # Grant the group viewer on the workspace → outsider gains access.
    r = client.post(
        f"/api/workspaces/{fx.workspace}/members", headers=hdr(fx.admin_sub),
        json={"group_id": gid, "role": "viewer"},
    )
    assert r.status_code == 201
    auth_mw.clear_identity_cache()
    r = client.get(f"/api/workspaces/{fx.workspace}", headers=hdr(fx.outsider_sub))
    assert r.status_code == 200 and r.json()["effective_role"] == "viewer"


def test_the_member_list_can_be_narrowed_to_groups(client: TestClient, fx: Fixture) -> None:
    """p.478's "Specify Multipass group IDs", for §234's User Select.

    **The narrowing is here rather than in the browser** so a dropdown never
    needs the membership graph to answer itself - see `orgs.list_users`.
    """
    r = client.post("/api/org/groups", headers=hdr(fx.admin_sub),
                    json={"name": f"Pickers {fx.tag}"})
    assert r.status_code == 201, r.text
    gid = r.json()["id"]
    assert client.put(f"/api/org/groups/{gid}/members/{fx.outsider}",
                      headers=hdr(fx.admin_sub)).status_code == 204

    everyone = client.get("/api/org/members", headers=hdr(fx.viewer_sub))
    assert everyone.status_code == 200, everyone.text
    all_ids = {u["id"] for u in everyone.json()}
    assert str(fx.outsider) in all_ids

    narrowed = client.get("/api/org/members", headers=hdr(fx.viewer_sub),
                          params={"group_id": gid})
    assert narrowed.status_code == 200, narrowed.text
    assert {u["id"] for u in narrowed.json()} == {str(fx.outsider)}
    # **Narrower than the whole org is the assertion**, not merely "returns
    # something": a filter that was ignored would answer with everyone, and on
    # a one-member group that is the difference between right and wrong.
    assert len(all_ids) > 1


def test_narrowing_to_a_group_from_another_org_finds_nobody(
    client: TestClient, fx: Fixture
) -> None:
    """The group id arrives from a document a builder wrote, so it is re-checked
    against the caller's organisation rather than trusted.

    **A real group in the other organisation, not a made-up id.** An unknown
    uuid matches nothing whatever the query says, so it would pass against a
    version that never checked the organisation at all - the fixture's second
    org is what makes this an assertion about the join rather than about
    arithmetic on random numbers.
    """
    r = client.post("/api/org/groups", headers=hdr(fx.foreign_sub),
                    json={"name": f"Theirs {fx.tag}"})
    assert r.status_code == 201, r.text
    theirs = r.json()["id"]
    assert client.put(f"/api/org/groups/{theirs}/members/{fx.foreign}",
                      headers=hdr(fx.foreign_sub)).status_code == 204

    r = client.get("/api/org/members", headers=hdr(fx.viewer_sub),
                   params={"group_id": theirs})
    assert r.status_code == 200, r.text
    assert r.json() == []

    # **And now the case that actually needs the organisation check.** Above,
    # the foreign group's only member is also foreign, so `users.organisation_id
    # = :org` alone excludes them and the query answers correctly even without
    # looking at the *group's* org - a mutant deleting that check survived this
    # test until the state below existed. `group_members` has no organisation
    # column, so a group in one org holding a user from another is expressible;
    # written straight to the table because no route offers to build it.
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO group_members (group_id, user_id) VALUES (%s,%s)",
            (theirs, fx.viewer),
        )
    r = client.get("/api/org/members", headers=hdr(fx.viewer_sub),
                   params={"group_id": theirs})
    assert r.status_code == 200, r.text
    assert r.json() == [], "a group from another org selected one of our users"


@pytest.mark.anyio
async def test_asking_for_the_users_in_no_groups_finds_nobody(fx: Fixture) -> None:
    """`list_users(group_ids=[])` is nobody, and this has to be asked of the
    **service** because no URL can express it.

    A repeated query parameter has no empty form, so over HTTP the only two
    states are absent and non-empty — which is exactly why the browser's
    `shouldAsk` refuses to send a request it cannot express. The branch is not
    dead code, though: `list_users` has more callers than the one route, and a
    next caller passing `[]` must not silently get everybody. A mutation that
    deleted it survived every route test there is, because every route test goes
    through the door that cannot reach it.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    from src.services import orgs as org_service

    engine = create_async_engine(APP_DSN)
    try:
        async with engine.connect() as conn:
            # RLS reads the caller from the session, the way `user_connection`
            # sets it up for a request.
            await conn.exec_driver_sql(
                f"SELECT set_config('app.user_id', '{fx.viewer}', true)"
            )
            everybody = await org_service.list_users(conn, fx.org)
            nobody = await org_service.list_users(conn, fx.org, group_ids=[])
    finally:
        await engine.dispose()

    assert len(everybody) > 1, "the fixture should have several users"
    assert nobody == []


def test_the_member_list_is_unchanged_when_no_group_is_named(
    client: TestClient, fx: Fixture
) -> None:
    """Every caller before §234 sends no `group_id`, and gets what it always
    got. The parameter being *absent* is the whole-organisation answer; there is
    no URL that means "these zero groups", which is why the widget refuses to
    ask rather than sending one (`user-select.shouldAsk`)."""
    r = client.get("/api/org/members", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    assert len(r.json()) > 1


def test_disabled_user_is_locked_out(client: TestClient, fx: Fixture) -> None:
    r = client.post(
        "/api/org/members", headers=hdr(fx.admin_sub),
        json={"email": f"doomed-{fx.tag}@example.com", "display_name": "Doomed", "org_role": "member"},
    )
    doomed_id = r.json()["id"]
    with psycopg.connect(ADMIN_DSN) as conn:
        sub = conn.execute("SELECT cognito_sub FROM users WHERE id=%s", (doomed_id,)).fetchone()[0]
    assert client.get("/api/auth/me", headers=hdr(sub)).status_code == 200
    assert client.delete(f"/api/org/members/{doomed_id}", headers=hdr(fx.admin_sub)).status_code == 204
    assert client.get("/api/auth/me", headers=hdr(sub)).status_code == 401


def test_health_is_public(client: TestClient) -> None:
    assert client.get("/api/health").status_code == 200


# ---- browser session cookie (STATUS.md §55) ---------------------------------
def test_a_verified_token_becomes_an_httponly_session_cookie(
    client: TestClient, fx: Fixture
) -> None:
    """The credential travels inward only: the response carries a Set-Cookie
    and no token, so a script on this origin has nothing to exfiltrate."""
    r = client.post("/api/auth/session", json={"access_token": mint(fx.owner_sub)})
    assert r.status_code == 200, r.text
    assert r.json()["email"].startswith("owner-")
    assert "access_token" not in r.text

    raw = r.headers["set-cookie"]
    assert "anchor_session=" in raw
    assert "HttpOnly" in raw
    assert "SameSite=lax" in raw.replace("samesite", "SameSite")


def test_the_session_cookie_authenticates_subsequent_requests(
    client: TestClient, fx: Fixture
) -> None:
    client.post("/api/auth/session", json={"access_token": mint(fx.owner_sub)})
    r = client.get("/api/auth/me", headers={"X-Anchor-Session": "1"})
    assert r.status_code == 200, r.text
    assert r.json()["email"].startswith("owner-")
    client.cookies.clear()


def test_a_cookie_without_the_session_header_is_refused(
    client: TestClient, fx: Fixture
) -> None:
    """The CSRF barrier. A form POST from another site carries the cookie and
    cannot carry the header; without this check the cookie alone would be
    enough to act as the user."""
    client.post("/api/auth/session", json={"access_token": mint(fx.owner_sub)})
    r = client.get("/api/auth/me")
    assert r.status_code == 401, r.text
    assert "X-Anchor-Session" in r.json()["detail"]
    client.cookies.clear()


def test_an_authorization_header_still_wins_and_needs_no_session_header(
    client: TestClient, fx: Fixture
) -> None:
    """Every non-browser caller - the tests, the worker, anything holding a
    token deliberately - must keep working exactly as before."""
    r = client.get("/api/auth/me", headers=hdr(fx.owner_sub))
    assert r.status_code == 200, r.text


def test_a_bad_token_does_not_get_a_session(client: TestClient) -> None:
    r = client.post("/api/auth/session", json={"access_token": "not-a-jwt"})
    assert r.status_code == 401, r.text
    assert "anchor_session" not in r.headers.get("set-cookie", "")


def test_signing_out_clears_the_cookie(client: TestClient, fx: Fixture) -> None:
    """The cookie is httpOnly, so this endpoint is the only thing that can end
    the session; a delete that missed would leave somebody signed in while
    being told otherwise."""
    client.post("/api/auth/session", json={"access_token": mint(fx.owner_sub)})
    r = client.post("/api/auth/logout", headers={"X-Anchor-Session": "1"})
    assert r.status_code == 204, r.text
    assert 'anchor_session=""' in r.headers["set-cookie"] or "anchor_session=;" in r.headers["set-cookie"]
    assert client.get("/api/auth/me", headers={"X-Anchor-Session": "1"}).status_code == 401
    client.cookies.clear()
