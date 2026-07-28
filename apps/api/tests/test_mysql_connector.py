"""MySQL/MariaDB connector tests - the second source type, and the thing that
proves the connector interface generalises rather than just being a rename of
the Postgres path.

Same standard as test_connections.py/test_sync.py: a real MariaDB server with
a real database, real login role, and the real PyMySQL driver end to end. No
mocks - a connector that only works against a fake is not evidence of
anything.

Requires a reachable MySQL/MariaDB (TEST_MYSQL_* below); the module skips
rather than fails when there isn't one, so a Postgres-only environment still
runs the rest of the suite.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pymysql = pytest.importorskip("pymysql", reason="PyMySQL not installed")

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import connections as conn_routes  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services.connectors import (  # noqa: E402
    ConnectorConfigError,
    MySQLConnector,
    SourceReadError,
    get_connector,
)
from src.services.secrets import InMemorySecretsGateway  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

MYSQL_HOST = os.environ.get("TEST_MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.environ.get("TEST_MYSQL_PORT", "3306"))
MYSQL_ADMIN_USER = os.environ.get("TEST_MYSQL_ADMIN_USER", "platform_test")
MYSQL_ADMIN_PASSWORD = os.environ.get("TEST_MYSQL_ADMIN_PASSWORD", "devpass")

SOURCE_DB = "conn_source_mysql"
SOURCE_USER = "mysql_source_user"
SOURCE_PASSWORD = "my-s0urce-Secret-42"


def _admin_connect(database: str = "mysql"):
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_ADMIN_USER,
        password=MYSQL_ADMIN_PASSWORD,
        database=database,
        connect_timeout=5,
        autocommit=True,
    )


try:
    _admin_connect().close()
except Exception as exc:  # pragma: no cover - environment guard
    pytest.skip(
        f"no MySQL/MariaDB reachable at {MYSQL_HOST}:{MYSQL_PORT} ({exc})",
        allow_module_level=True,
    )


@pytest.fixture(scope="module")
def source_database() -> dict[str, object]:
    """The customer's MySQL system: its own database, its own login role."""
    with _admin_connect() as conn, conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {SOURCE_DB}")
        cur.execute(f"CREATE DATABASE {SOURCE_DB}")
        cur.execute(f"CREATE USER IF NOT EXISTS '{SOURCE_USER}'@'%' IDENTIFIED BY '{SOURCE_PASSWORD}'")
        cur.execute(f"GRANT ALL PRIVILEGES ON {SOURCE_DB}.* TO '{SOURCE_USER}'@'%'")
        cur.execute("FLUSH PRIVILEGES")
    with _admin_connect(SOURCE_DB) as conn, conn.cursor() as cur:
        cur.execute(
            """CREATE TABLE orders (
                   id BIGINT PRIMARY KEY,
                   customer_email VARCHAR(255) NOT NULL,
                   total_pence INT NOT NULL,
                   placed_at DATETIME NULL
               )"""
        )
        cur.execute("CREATE VIEW recent_orders AS SELECT * FROM orders")
        # A leading-digit table name is legal in MySQL and illegal in Postgres -
        # the identifier rules genuinely differ, and the connector owns that.
        cur.execute("CREATE TABLE 2024_archive (id BIGINT PRIMARY KEY)")
        cur.execute(
            """INSERT INTO orders (id, customer_email, total_pence, placed_at) VALUES
               (1, 'a@example.com', 1200, '2024-01-01 10:00:00'),
               (2, 'b@example.com', 80,   '2024-01-02 10:00:00'),
               (3, 'c@example.com', 455,  '2024-01-03 10:00:00')"""
        )
    return {
        "host": MYSQL_HOST,
        "port": MYSQL_PORT,
        "database": SOURCE_DB,
        "user": SOURCE_USER,
        # This server is built without TLS (@@have_ssl = DISABLED), so the
        # connection has to opt out explicitly - which is the point of the
        # default being the other way round.
        "ssl_mode": "disabled",
    }


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    conn_routes.configure_secrets_gateway(InMemorySecretsGateway())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("mysql-sync-storage")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def cbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/connections"


def dbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets"


@pytest.fixture(scope="module")
def connection_id(client: TestClient, fx: Fixture, source_database: dict) -> str:
    r = client.post(
        cbase(fx),
        headers=hdr(fx.editor_sub),
        json={
            "name": f"MySQL Orders {uuid.uuid4().hex[:6]}",
            "source_type": "mysql",
            "config": source_database,
            "secret": {"password": SOURCE_PASSWORD},
        },
    )
    assert r.status_code == 201, r.text
    assert SOURCE_PASSWORD not in r.text
    return r.json()["id"]


# ---- registry ----------------------------------------------------------------
def test_mysql_is_registered_and_offered_to_the_wizard(client: TestClient, fx: Fixture) -> None:
    r = client.get(f"{cbase(fx)}/source-types", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200
    types = {t["type"]: t for t in r.json()}
    assert {"postgres", "mysql"} <= set(types)
    mysql = types["mysql"]
    assert mysql["secret_fields"] == ["password"]
    props = mysql["config_schema"]["properties"]
    assert {"host", "port", "database", "user", "ssl_mode"} <= set(props)
    assert props["port"]["default"] == 3306


def test_registry_returns_the_right_implementation() -> None:
    assert isinstance(get_connector("mysql"), MySQLConnector)
    assert get_connector("mysql").type_name == "mysql"
    with pytest.raises(ConnectorConfigError) as exc:
        get_connector("oracle")
    # The error names what *is* supported, so the list grows with the registry.
    assert "mysql" in str(exc.value) and "postgres" in str(exc.value)


def test_tls_is_required_by_default() -> None:
    """The security default is the one thing here that isn't shared with
    Postgres, so it gets asserted rather than assumed."""
    cleaned = MySQLConnector().validate_config(
        {"host": "h", "database": "d", "user": "u"}
    )
    assert cleaned["ssl_mode"] == "required"
    assert cleaned["port"] == 3306


def test_invalid_config_is_rejected_with_a_field_message() -> None:
    with pytest.raises(ConnectorConfigError) as exc:
        MySQLConnector().validate_config({"host": "h", "database": "d", "user": "u", "port": 0})
    assert "port" in str(exc.value)
    with pytest.raises(ConnectorConfigError) as exc:
        MySQLConnector().validate_config(
            {"host": "h", "database": "d", "user": "u", "ssl_mode": "whatever"}
        )
    assert "ssl_mode" in str(exc.value)


# ---- test & discover against the live source --------------------------------
def test_test_endpoint_reaches_the_real_server(
    client: TestClient, fx: Fixture, connection_id: str
) -> None:
    r = client.post(f"{cbase(fx)}/{connection_id}/test", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["error"] is None
    assert body["connection"]["status"] == "ok"
    assert SOURCE_PASSWORD not in r.text


def test_discover_reads_the_mysql_information_schema(
    client: TestClient, fx: Fixture, connection_id: str
) -> None:
    r = client.post(f"{cbase(fx)}/{connection_id}/discover", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    tables = {(t["schema_name"], t["name"]): t for t in r.json()}

    orders = tables[(SOURCE_DB, "orders")]
    assert orders["kind"] == "table"
    cols = {c["name"]: c for c in orders["columns"]}
    assert cols["id"]["is_primary_key"] is True
    assert cols["customer_email"]["nullable"] is False
    assert cols["placed_at"]["nullable"] is True
    # MySQL's own type vocabulary, not Postgres', comes back untranslated.
    assert cols["customer_email"]["data_type"] == "varchar"

    assert tables[(SOURCE_DB, "recent_orders")]["kind"] == "view"
    # A MySQL database is reported as a schema so the layers above keep one
    # vocabulary across source types.
    assert all(schema == SOURCE_DB for schema, _ in tables)
    assert SOURCE_PASSWORD not in r.text


def test_wrong_password_is_a_clean_error_not_a_500(
    client: TestClient, fx: Fixture, source_database: dict
) -> None:
    r = client.post(
        cbase(fx),
        headers=hdr(fx.editor_sub),
        json={
            "name": f"MySQL Bad Creds {uuid.uuid4().hex[:6]}",
            "source_type": "mysql",
            "config": source_database,
            "secret": {"password": "definitely-wrong"},
        },
    )
    assert r.status_code == 201
    cid = r.json()["id"]
    r = client.post(f"{cbase(fx)}/{cid}/test", headers=hdr(fx.editor_sub))
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["connection"]["status"] == "error"
    assert body["error"] and "definitely-wrong" not in body["error"]
    assert client.delete(f"{cbase(fx)}/{cid}", headers=hdr(fx.editor_sub)).status_code == 204


def test_tls_required_against_a_non_tls_server_fails_loudly(
    client: TestClient, fx: Fixture, source_database: dict
) -> None:
    """The whole point of the `required` default: this MariaDB has no TLS, and
    PyMySQL will happily finish the handshake in plaintext, so the connector
    has to notice and refuse rather than silently downgrade."""
    r = client.post(
        cbase(fx),
        headers=hdr(fx.editor_sub),
        json={
            "name": f"MySQL TLS {uuid.uuid4().hex[:6]}",
            "source_type": "mysql",
            "config": {**source_database, "ssl_mode": "required"},
            "secret": {"password": SOURCE_PASSWORD},
        },
    )
    assert r.status_code == 201
    cid = r.json()["id"]
    r = client.post(f"{cbase(fx)}/{cid}/test", headers=hdr(fx.editor_sub))
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False, "a plaintext session must not pass an ssl_mode=required test"
    assert "TLS" in body["error"]
    assert client.delete(f"{cbase(fx)}/{cid}", headers=hdr(fx.editor_sub)).status_code == 204


# ---- full sync through the shared pipeline ----------------------------------
def test_full_sync_lands_a_real_dataset(
    client: TestClient, fx: Fixture, connection_id: str
) -> None:
    """The payoff of the refactor: sync is driver-agnostic, so a MySQL source
    reaches DuckDB/Parquet/datasets through the identical path Postgres uses."""
    name = f"MySQL Orders {fx.tag}"
    r = client.post(
        f"{cbase(fx)}/{connection_id}/sync",
        headers=hdr(fx.editor_sub),
        json={"source_schema": SOURCE_DB, "source_table": "orders", "dataset_name": name},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True, body["error"]
    assert body["created_dataset"] is True
    assert body["rows_synced"] == 3

    did = body["dataset"]["id"]
    detail = client.get(f"{dbase(fx)}/{did}", headers=hdr(fx.viewer_sub)).json()
    assert detail["origin"] == "sync" and detail["connection_id"] == connection_id
    preview = client.get(f"{dbase(fx)}/{did}/preview", headers=hdr(fx.viewer_sub)).json()
    assert preview["total_rows"] == 3
    # Types survived the CSV round trip rather than all collapsing to text.
    schema = {c["name"]: c["data_type"] for c in detail["table_schema"]}
    assert schema["id"] == "BIGINT"
    assert "VARCHAR" in schema["customer_email"]


def test_sync_of_a_missing_table_is_a_clean_failed_run(
    client: TestClient, fx: Fixture, connection_id: str
) -> None:
    r = client.post(
        f"{cbase(fx)}/{connection_id}/sync",
        headers=hdr(fx.editor_sub),
        json={"source_schema": SOURCE_DB, "source_table": "no_such_table"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    assert "does not exist" in body["error"]


def test_identifier_rules_are_the_connectors_own(
    client: TestClient, fx: Fixture, connection_id: str
) -> None:
    """`2024_archive` is a legal MySQL table and an illegal Postgres one. The
    Postgres-shaped identifier check would have rejected it, which is why the
    rule belongs to the connector rather than to the sync layer."""
    r = client.post(
        f"{cbase(fx)}/{connection_id}/sync",
        headers=hdr(fx.editor_sub),
        json={
            "source_schema": SOURCE_DB,
            "source_table": "2024_archive",
            "dataset_name": f"MySQL Archive {fx.tag}",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True, r.json()["error"]

    # And a genuinely malformed name is still refused before it reaches SQL.
    import tempfile

    with tempfile.TemporaryDirectory() as tmp, pytest.raises(SourceReadError):
        MySQLConnector().snapshot(
            {"host": MYSQL_HOST, "port": MYSQL_PORT, "database": SOURCE_DB,
             "user": SOURCE_USER, "ssl_mode": "disabled"},
            {"password": SOURCE_PASSWORD},
            source_schema=SOURCE_DB,
            source_table="orders; DROP TABLE orders",
            dest_dir=tmp,
            max_bytes=1024,
        )


# ---- incremental sync --------------------------------------------------------
def test_scheduled_incremental_sync_merges_only_new_rows(
    client: TestClient, fx: Fixture, connection_id: str
) -> None:
    """Cursor-incremental mode over MySQL, driven through the same
    scheduled-sync endpoints Postgres uses."""
    name = f"MySQL Incremental {fx.tag}"
    r = client.put(
        f"{cbase(fx)}/{connection_id}/scheduled-sync",
        headers=hdr(fx.editor_sub),
        json={
            "mode": "incremental",
            "source_schema": SOURCE_DB,
            "source_table": "orders",
            "dataset_name": name,
            "primary_key_column": "id",
            "cursor_column": "id",
        },
    )
    assert r.status_code == 200, r.text

    r = client.post(f"{cbase(fx)}/{connection_id}/scheduled-sync/run", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True, body["error"]
    assert body["rows_synced"] == 3
    did = body["dataset"]["id"]

    # Nothing new: the steady state between source writes must not write a
    # needless version (and must not trip the empty-CSV type-inference bug the
    # Postgres path already had fixed).
    r = client.post(f"{cbase(fx)}/{connection_id}/scheduled-sync/run", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True, r.json()["error"]
    assert r.json()["rows_synced"] == 3

    with _admin_connect(SOURCE_DB) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO orders (id, customer_email, total_pence, placed_at) "
            "VALUES (4, 'd@example.com', 3100, '2024-01-04 10:00:00')"
        )
    r = client.post(f"{cbase(fx)}/{connection_id}/scheduled-sync/run", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True, body["error"]
    assert body["rows_synced"] == 4, "the new row should merge into the existing 3"

    preview = client.get(f"{dbase(fx)}/{did}/preview", headers=hdr(fx.viewer_sub)).json()
    assert preview["total_rows"] == 4
