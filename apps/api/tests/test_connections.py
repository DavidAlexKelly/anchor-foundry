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

from test_api import Fixture, LocalVerifier, for_database, hdr  # noqa: E402
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
    src_dsn = for_database(ADMIN_DSN, SOURCE_DB)
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
        # p.143's relationships (§602): a plain key, two keys between the same
        # pair of tables, a composite key, and one into another schema.
        conn.execute("CREATE TABLE public.customers (id bigint PRIMARY KEY, email text)")
        conn.execute(
            """CREATE TABLE public.order_lines (
                   order_id bigint REFERENCES public.orders(id),
                   line_no integer,
                   billed_to bigint CONSTRAINT lines_billed_fk REFERENCES public.customers(id),
                   shipped_to bigint CONSTRAINT lines_shipped_fk REFERENCES public.customers(id),
                   note text,
                   PRIMARY KEY (order_id, line_no)
               )"""
        )
        conn.execute(
            """CREATE TABLE public.shipments (
                   id bigint PRIMARY KEY,
                   line_order bigint,
                   line_number integer,
                   CONSTRAINT shipments_line_fk FOREIGN KEY (line_number, line_order)
                       REFERENCES public.order_lines (line_no, order_id)
               )"""
        )
        # One column in two keys: the first by constraint name is the one shown.
        conn.execute(
            "CREATE TABLE public.refunds (subject_id bigint"
            " CONSTRAINT refunds_b_fk REFERENCES public.customers(id)"
            " CONSTRAINT refunds_a_fk REFERENCES public.orders(id))"
        )
        conn.execute("CREATE SCHEMA billing")
        conn.execute(
            "CREATE TABLE billing.invoices (id bigint PRIMARY KEY,"
            " order_id bigint REFERENCES public.orders(id))"
        )
        conn.execute(f"GRANT ALL ON ALL TABLES IN SCHEMA public TO {SOURCE_USER}")
        conn.execute(f"GRANT USAGE ON SCHEMA billing TO {SOURCE_USER}")
        conn.execute(f"GRANT SELECT ON billing.invoices TO {SOURCE_USER}")
    # Connection details as the API's connector will use them: TCP localhost.
    return {"host": "localhost", "port": 5432, "database": SOURCE_DB, "user": SOURCE_USER, "sslmode": "disable"}


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
    # p.143: the graph "is not always available" - a REST model has "no clear
    # relations between objects", and object storage has none either (§602).
    assert {t: types[t]["reports_relations"] for t in ("postgres", "mysql", "s3", "rest")} == {
        "postgres": True, "mysql": True, "s3": False, "rest": False,
    }


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


def test_discover_reports_each_columns_foreign_key(client: TestClient, fx: Fixture) -> None:
    """p.143's relationships, as decision 0015 §7's column annotation (§602)."""
    cid = _connection_id(client, fx)
    r = client.post(f"{base(fx)}/{cid}/discover", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    tables = {(t["schema_name"], t["name"]): t for t in r.json()}

    def refs(schema: str, name: str) -> dict[str, object]:
        return {c["name"]: c["references"] for c in tables[(schema, name)]["columns"]}

    lines = refs("public", "order_lines")
    assert lines["order_id"] == {
        "schema_name": "public", "table": "orders", "column": "id",
        "constraint": "order_lines_order_id_fkey",
    }
    # Two keys into one table stay two, told apart by their names.
    assert lines["billed_to"]["constraint"] == "lines_billed_fk"
    assert lines["shipped_to"]["constraint"] == "lines_shipped_fk"
    assert lines["billed_to"]["table"] == lines["shipped_to"]["table"] == "customers"
    # A column in no key, and a key's *target*, carry nothing.
    assert lines["line_no"] is None and lines["note"] is None
    assert all(v is None for v in refs("public", "orders").values())

    # A composite key pairs its columns as declared, not by name or position
    # in the table: (line_number, line_order) -> (line_no, order_id).
    shipments = refs("public", "shipments")
    assert (shipments["line_number"]["column"], shipments["line_order"]["column"]) == (
        "line_no", "order_id",
    )
    assert shipments["line_number"]["constraint"] == shipments["line_order"]["constraint"]
    assert shipments["id"] is None

    # A column in two keys shows the first by name, whichever came first.
    assert refs("public", "refunds")["subject_id"]["constraint"] == "refunds_a_fk"

    # Across schemas, named by the target's schema.
    assert refs("billing", "invoices")["order_id"] == {
        "schema_name": "public", "table": "orders", "column": "id",
        "constraint": "invoices_order_id_fkey",
    }


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


def test_no_read_endpoint_returns_the_credential_at_any_role(
    client: TestClient, fx: Fixture, source_database: dict[str, object],
) -> None:
    """`data-connection.md` §6: "a credential is never returned by any read
    endpoint, at any role. This wants an explicit test rather than an
    assumption."

    **Every GET route the app has**, walked rather than listed: each one whose
    path parameters are a workspace, a project or this connection, called at
    every role, the password searched for in whatever comes back. A list
    written out here would miss the endpoint added next year; the app's own
    routing table cannot. A route needing any other id is skipped, since it
    cannot be about this connection without naming something else first.
    """
    import re as _re

    r = client.post(
        base(fx), headers=hdr(fx.editor_sub),
        json={"name": "Credential sweep", "source_type": "postgres",
              "config": source_database, "secret": {"password": SOURCE_PASSWORD}},
    )
    assert r.status_code == 201, r.text
    known = {"workspace_id": fx.workspace, "project_id": fx.project,
             "connection_id": r.json()["id"]}
    # Tested once, so a connection that reads as `ok` has been through the
    # code that holds the password.
    client.post(f"{base(fx)}/{known['connection_id']}/test", headers=hdr(fx.editor_sub))

    from route_table import api_routes

    checked: list[str] = []
    for template, methods, _route in api_routes(client.app):
        if "GET" not in methods:
            continue
        params = _re.findall(r"{(\w+)}", template)
        if any(p not in known for p in params):
            continue
        path = template.format(**{p: known[p] for p in params})
        for sub in (fx.viewer_sub, fx.editor_sub, fx.admin_sub, fx.owner_sub):
            response = client.get(path, headers=hdr(sub))
            assert SOURCE_PASSWORD not in response.text, (template, sub, response.status_code)
        checked.append(template)
    # The connection's own reads are among the routes walked, and the walk is
    # the app's breadth rather than a handful.
    assert any(p.endswith("/connections") for p in checked), checked
    assert any("{connection_id}" in p for p in checked), checked
    assert len(checked) > 50, len(checked)


# ---- TLS by default (§929) -----------------------------------------------------
def test_a_postgres_source_asks_for_tls_unless_told_not_to() -> None:
    from src.services.connectors import PostgresConnector

    stored = PostgresConnector().validate_config({"host": "h", "database": "d", "user": "u"})
    assert stored["sslmode"] == "require", "prefer falls back to plaintext when TLS is refused"
    assert PostgresConnector().validate_config(
        {"host": "h", "database": "d", "user": "u", "sslmode": "disable"})["sslmode"] == "disable"


def test_a_default_connection_is_never_plaintext(source_database) -> None:
    """Whether this server speaks TLS or not (CI's does not; a developer's
    may): by default a session is encrypted or it is refused, never quietly
    plain."""
    from src.services.connectors import PostgresConnector

    config = {k: v for k, v in source_database.items() if k != "sslmode"}
    conninfo = PostgresConnector()._conninfo(config, {"password": SOURCE_PASSWORD})
    try:
        with psycopg.connect(**conninfo) as conn:
            encrypted = conn.execute(
                "SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()").fetchone()[0]
    except psycopg.OperationalError as exc:
        assert "SSL" in str(exc), exc
    else:
        assert encrypted is True


def test_a_source_without_tls_is_told_what_to_change() -> None:
    from src.services.connectors import PostgresConnector

    error = PostgresConnector._operational(
        Exception("server does not support SSL, but SSL was required\nmore"))
    assert "set sslmode to 'disable'" in str(error)
    assert str(PostgresConnector._operational(Exception("password authentication failed"))) == \
        "password authentication failed"
