"""Connections layer tests. The local Postgres doubles as the customer's
source system: a dedicated source database with known tables lets test and
discover run against a real driver end to end.

Credential boundary assertions are the core of this file: the password enters
once at create time and must never appear in any response, the stored config,
or the audit log.
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
from src.routes import connections as conn_routes  # noqa: E402
from src.services.secrets import InMemorySecretsGateway  # noqa: E402

ADMIN_DSN = os.environ["TEST_ADMIN_DSN"]

SOURCE_DB = "conn_source_test"
SOURCE_USER = "conn_source_user"
SOURCE_PASSWORD = "s0urce-Secret-42"


@pytest.fixture(scope="module")
def source_database() -> dict[str, object]:
    """A separate database + login role acting as the customer's system."""
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {SOURCE_DB}")
        conn.execute(f"DROP ROLE IF EXISTS {SOURCE_USER}")
        conn.execute(f"CREATE ROLE {SOURCE_USER} LOGIN PASSWORD '{SOURCE_PASSWORD}'")
        conn.execute(f"GRANT {SOURCE_USER} TO platform")  # needed for OWNER below
        conn.execute(f"CREATE DATABASE {SOURCE_DB} OWNER {SOURCE_USER}")
    src_dsn = ADMIN_DSN.replace("/platform?", f"/{SOURCE_DB}?")
    with psycopg.connect(src_dsn, autocommit=True) as conn:
        conn.execute(
            """CREATE TABLE public.orders (
                   id bigint PRIMARY KEY,
                   customer_email text NOT NULL,
                   total_pence integer NOT NULL,
                   placed_at timestamptz
               )"""
        )
        conn.execute("CREATE VIEW public.recent_orders AS SELECT * FROM public.orders")
        conn.execute(f"GRANT ALL ON ALL TABLES IN SCHEMA public TO {SOURCE_USER}")
    # Connection details as the API's connector will use them: TCP localhost.
    return {"host": "localhost", "port": 5432, "database": SOURCE_DB, "user": SOURCE_USER}


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def gateway() -> InMemorySecretsGateway:
    return InMemorySecretsGateway()


@pytest.fixture(scope="module")
def client(gateway: InMemorySecretsGateway) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    conn_routes.configure_secrets_gateway(gateway)
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def base(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/connections"


# ---- catalog ----------------------------------------------------------------
def test_source_type_catalog(client: TestClient, fx: Fixture) -> None:
    r = client.get(f"{base(fx)}/source-types", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200
    types = {t["type"]: t for t in r.json()}
    assert "postgres" in types
    assert types["postgres"]["secret_fields"] == ["password"]
    assert "host" in types["postgres"]["config_schema"]["properties"]


# ---- create + credential boundary ------------------------------------------
def test_editor_creates_connection_password_never_returned(
    client: TestClient, fx: Fixture, source_database: dict[str, object],
    gateway: InMemorySecretsGateway,
) -> None:
    r = client.post(
        base(fx),
        headers=hdr(fx.editor_sub),
        json={
            "name": "Orders DB",
            "source_type": "postgres",
            "config": source_database,
            "secret": {"password": SOURCE_PASSWORD},
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert SOURCE_PASSWORD not in r.text
    assert "secret" not in body and "secret_arn" not in body
    assert body["status"] == "unconfigured"
    assert body["config"]["host"] == "localhost"
    # The secret landed in the gateway keyed by the connection id.
    arn = f"local:secret:anchor/connections/{body['id']}"
    assert gateway.get_secret(arn) == {"password": SOURCE_PASSWORD}
    # And the DB row's config carries no password anywhere.
    with psycopg.connect(ADMIN_DSN) as conn:
        cfg = conn.execute(
            "SELECT config::text FROM connections WHERE id=%s", (body["id"],)
        ).fetchone()[0]
    assert SOURCE_PASSWORD not in cfg


def test_viewer_cannot_create_but_can_list(client: TestClient, fx: Fixture) -> None:
    r = client.post(
        base(fx), headers=hdr(fx.viewer_sub),
        json={"name": "X", "source_type": "postgres",
              "config": {"host": "h", "database": "d", "user": "u"}},
    )
    assert r.status_code == 403
    r = client.get(base(fx), headers=hdr(fx.viewer_sub))
    assert r.status_code == 200
    assert any(c["name"] == "Orders DB" for c in r.json())
    assert SOURCE_PASSWORD not in r.text


def test_outsider_gets_404(client: TestClient, fx: Fixture) -> None:
    assert client.get(base(fx), headers=hdr(fx.outsider_sub)).status_code == 404


def test_invalid_config_is_422_with_field_message(client: TestClient, fx: Fixture) -> None:
    r = client.post(
        base(fx), headers=hdr(fx.editor_sub),
        json={"name": "Bad", "source_type": "postgres",
              "config": {"host": "h", "database": "d", "user": "u", "port": 999999}},
    )
    assert r.status_code == 422
    assert "port" in r.json()["detail"]


def test_unsupported_source_type_is_422(client: TestClient, fx: Fixture) -> None:
    r = client.post(
        base(fx), headers=hdr(fx.editor_sub),
        json={"name": "Nope", "source_type": "snowflake", "config": {}},
    )
    assert r.status_code == 422
    assert "supported" in r.json()["detail"]


# ---- test & discover against the live source --------------------------------
def _connection_id(client: TestClient, fx: Fixture) -> str:
    r = client.get(base(fx), headers=hdr(fx.editor_sub))
    return next(c["id"] for c in r.json() if c["name"] == "Orders DB")


def test_test_endpoint_reaches_source_and_updates_status(
    client: TestClient, fx: Fixture, source_database: dict[str, object]
) -> None:
    cid = _connection_id(client, fx)
    r = client.post(f"{base(fx)}/{cid}/test", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["error"] is None
    assert body["connection"]["status"] == "ok"
    assert body["connection"]["last_tested_at"] is not None
    assert SOURCE_PASSWORD not in r.text


def test_discover_returns_real_tables(client: TestClient, fx: Fixture) -> None:
    cid = _connection_id(client, fx)
    r = client.post(f"{base(fx)}/{cid}/discover", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    tables = {(t["schema_name"], t["name"]): t for t in r.json()}
    orders = tables[("public", "orders")]
    assert orders["kind"] == "table"
    cols = {c["name"]: c for c in orders["columns"]}
    assert cols["id"]["is_primary_key"] is True
    assert cols["customer_email"]["nullable"] is False
    assert tables[("public", "recent_orders")]["kind"] == "view"
    assert SOURCE_PASSWORD not in r.text


def test_wrong_password_is_clean_error_not_500(
    client: TestClient, fx: Fixture, source_database: dict[str, object]
) -> None:
    r = client.post(
        base(fx), headers=hdr(fx.editor_sub),
        json={"name": "Bad Creds", "source_type": "postgres",
              "config": source_database, "secret": {"password": "wrong"}},
    )
    cid = r.json()["id"]
    r = client.post(f"{base(fx)}/{cid}/test", headers=hdr(fx.editor_sub))
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["connection"]["status"] == "error"
    assert body["error"] and "wrong" not in body["error"]  # message, not the password
    # cleanup for later assertions
    assert client.delete(f"{base(fx)}/{cid}", headers=hdr(fx.editor_sub)).status_code == 204


def test_viewer_cannot_test_or_discover(client: TestClient, fx: Fixture) -> None:
    cid = _connection_id(client, fx)
    assert client.post(f"{base(fx)}/{cid}/test", headers=hdr(fx.viewer_sub)).status_code == 403
    assert client.post(f"{base(fx)}/{cid}/discover", headers=hdr(fx.viewer_sub)).status_code == 403


# ---- update & credential rotation -------------------------------------------
def test_update_rotates_secret_and_resets_status(
    client: TestClient, fx: Fixture, gateway: InMemorySecretsGateway
) -> None:
    cid = _connection_id(client, fx)
    r = client.patch(
        f"{base(fx)}/{cid}", headers=hdr(fx.editor_sub),
        json={"secret": {"password": SOURCE_PASSWORD}},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "unconfigured"  # must re-test after rotation
    arn = f"local:secret:anchor/connections/{cid}"
    assert gateway.get_secret(arn)["password"] == SOURCE_PASSWORD


# ---- workspace scope ---------------------------------------------------------
def test_workspace_scope_requires_workspace_admin(client: TestClient, fx: Fixture) -> None:
    payload = {
        "name": "Shared Warehouse",
        "source_type": "postgres",
        "scope": "workspace",
        "config": {"host": "h", "database": "d", "user": "u"},
    }
    r = client.post(base(fx), headers=hdr(fx.editor_sub), json=payload)
    assert r.status_code == 403
    r = client.post(base(fx), headers=hdr(fx.admin_sub), json=payload)  # org admin → ws admin
    assert r.status_code == 201
    assert r.json()["scope"] == "workspace" and r.json()["project_id"] is None


# ---- delete removes the secret ----------------------------------------------
def test_delete_removes_row_and_secret(
    client: TestClient, fx: Fixture, gateway: InMemorySecretsGateway
) -> None:
    cid = _connection_id(client, fx)
    arn = f"local:secret:anchor/connections/{cid}"
    gateway.get_secret(arn)  # exists before
    assert client.delete(f"{base(fx)}/{cid}", headers=hdr(fx.editor_sub)).status_code == 204
    with pytest.raises(KeyError):
        gateway.get_secret(arn)
    r = client.get(base(fx), headers=hdr(fx.editor_sub))
    assert all(c["id"] != cid for c in r.json())


# ---- audit ------------------------------------------------------------------
def test_connection_actions_audited_without_password(client: TestClient, fx: Fixture) -> None:
    r = client.get("/api/org/audit?limit=200", headers=hdr(fx.admin_sub))
    actions = {e["action"] for e in r.json()}
    assert {"connection.create", "connection.test", "connection.discover",
            "connection.delete"} <= actions
    assert SOURCE_PASSWORD not in r.text
