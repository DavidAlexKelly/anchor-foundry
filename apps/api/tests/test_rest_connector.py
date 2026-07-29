"""Generic REST/HTTP JSON connector tests (roadmap Connections item 5).

Runs against a real HTTP server in its own process (`rest_fixture_server.py`)
rather than a patched urlopen - same standard as the Postgres/MariaDB/moto
suites. A mocked HTTP client would be testing the mock's shape.

The roadmap calls this "the highest-variance connector to build well", so the
assertions concentrate on the variance: where the records live in the body,
the two pagination styles, the three auth schemes, and every way a response
can be shaped wrong.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import connections as conn_routes  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services.connectors import (  # noqa: E402
    ConnectorConfigError,
    ConnectorOperationError,
    RestConnector,
    SourceReadError,
    get_connector,
)
from src.services.secrets import InMemorySecretsGateway  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rest_fixture_server.py")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def api_base() -> str:
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, SERVER, str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.25)
    else:  # pragma: no cover - environment guard
        proc.terminate()
        pytest.skip("fixture API did not start")
    yield f"http://127.0.0.1:{port}"
    proc.terminate()
    proc.wait(timeout=10)


def cfg(base: str, path: str, **overrides) -> dict:
    # allow_insecure_http because the fixture server is plain http on
    # localhost - which is exactly the opt-in the flag exists for.
    out = {"base_url": base, "resource_path": path, "allow_insecure_http": True}
    out.update(overrides)
    return out


# ---- registry & config -------------------------------------------------------
def test_rest_is_registered() -> None:
    assert isinstance(get_connector("rest"), RestConnector)


def test_https_is_the_default_and_http_must_be_opted_into(api_base: str) -> None:
    connector = RestConnector()
    with pytest.raises(ConnectorConfigError) as exc:
        connector.validate_config({"base_url": "http://example.com"})
    assert "https" in str(exc.value)
    # Opting in is explicit, and https never needs it.
    assert connector.validate_config(
        {"base_url": "http://example.com", "allow_insecure_http": True}
    )["base_url"] == "http://example.com"
    assert connector.validate_config({"base_url": "https://example.com"})["auth_type"] == "none"


def test_link_local_is_refused() -> None:
    """A connector fetching an operator-supplied URL runs inside the customer's
    VPC; 169.254.169.254 is where the instance metadata service - and the task
    role's credentials - live."""
    connector = RestConnector()
    with pytest.raises(ConnectorConfigError) as exc:
        connector.validate_config(
            {"base_url": "http://169.254.169.254/latest/meta-data/", "allow_insecure_http": True}
        )
    assert "link-local" in str(exc.value)


def test_config_requires_what_each_mode_needs() -> None:
    connector = RestConnector()
    with pytest.raises(ConnectorConfigError) as exc:
        connector.validate_config(
            {"base_url": "https://x.test", "auth_type": "oauth2_client_credentials"}
        )
    assert "token_url" in str(exc.value)
    with pytest.raises(ConnectorConfigError) as exc:
        connector.validate_config({"base_url": "https://x.test", "pagination": "cursor"})
    assert "cursor_path" in str(exc.value)
    with pytest.raises(ConnectorConfigError) as exc:
        connector.validate_config({"base_url": "https://x.test", "auth_type": "psychic"})
    assert "auth_type" in str(exc.value)


# ---- locating the records ----------------------------------------------------
def test_records_at_the_body_root(api_base: str) -> None:
    tables = RestConnector().discover(cfg(api_base, "/records"), {})
    assert len(tables) == 1
    table = tables[0]
    assert table.kind == "endpoint" and table.name == "records"
    types = {c.name: c.data_type for c in table.columns}
    assert types == {
        "id": "BIGINT", "name": "VARCHAR", "score": "DOUBLE",
        "active": "BOOLEAN", "tags": "JSON",
    }


def test_records_behind_a_dotted_path(api_base: str) -> None:
    tables = RestConnector().discover(
        cfg(api_base, "/wrapped", records_path="data.items"), {}
    )
    assert [c.name for c in tables[0].columns][:2] == ["id", "name"]


def test_a_wrong_records_path_says_so(api_base: str) -> None:
    connector = RestConnector()
    with pytest.raises(SourceReadError) as exc:
        connector.test(cfg(api_base, "/wrapped"), {})  # body is an object, not a list
    assert "records_path" in str(exc.value)
    with pytest.raises(SourceReadError):
        connector.test(cfg(api_base, "/notalist", records_path="records"), {})


def test_a_non_json_response_says_so(api_base: str) -> None:
    with pytest.raises(SourceReadError) as exc:
        RestConnector().test(cfg(api_base, "/notjson"), {})
    assert "did not return JSON" in str(exc.value)


def test_a_server_error_is_not_a_read_error(api_base: str) -> None:
    """500 is the API being broken, not this table being unreadable - callers
    that care about the distinction get it from the exception type."""
    with pytest.raises(ConnectorOperationError) as exc:
        RestConnector().test(cfg(api_base, "/boom"), {})
    assert not isinstance(exc.value, SourceReadError)
    assert "500" in str(exc.value)


# ---- auth --------------------------------------------------------------------
def test_api_key_header_auth(api_base: str) -> None:
    connector = RestConnector()
    config = cfg(api_base, "/secured", auth_type="api_key_header")
    connector.test(config, {"api_key": "s3cret"})  # no raise
    with pytest.raises(SourceReadError) as exc:
        connector.test(config, {"api_key": "wrong"})
    assert "401" in str(exc.value)
    with pytest.raises(ConnectorOperationError) as exc:
        connector.test(config, {})
    assert "no api_key stored" in str(exc.value)


def test_bearer_auth(api_base: str) -> None:
    connector = RestConnector()
    config = cfg(api_base, "/bearer", auth_type="bearer")
    connector.test(config, {"api_key": "t0ken"})
    with pytest.raises(SourceReadError) as exc:
        connector.test(config, {"api_key": "nope"})
    assert "403" in str(exc.value)


def test_oauth2_client_credentials(api_base: str) -> None:
    connector = RestConnector()
    config = cfg(
        api_base, "/oauth-data",
        auth_type="oauth2_client_credentials",
        token_url=f"{api_base}/oauth-token",
    )
    connector.test(config, {"client_id": "the-client", "client_secret": "the-secret"})

    with pytest.raises(ConnectorOperationError) as exc:
        connector.test(config, {"client_id": "the-client", "client_secret": "wrong"})
    message = str(exc.value)
    assert "token endpoint rejected" in message
    # The token endpoint can echo what it was sent; the error must not carry it.
    assert "wrong" not in message and "the-secret" not in message

    with pytest.raises(ConnectorOperationError) as exc:
        connector.test(config, {"client_id": "only-half"})
    assert "client_secret" in str(exc.value)


# ---- pagination --------------------------------------------------------------
def _snapshot_rows(connector: RestConnector, config: dict, tmp_path) -> list[dict]:
    import json

    extract = connector.snapshot(
        config, {}, source_schema="", source_table="records",
        dest_dir=str(tmp_path), max_bytes=10 * 1024 * 1024,
    )
    assert extract.extension == ".jsonl", "REST records land as JSONL, never CSV"
    if extract.empty:
        return []
    with open(extract.path) as handle:
        return [json.loads(line) for line in handle if line.strip()]


def test_no_pagination_reads_one_page(api_base: str, tmp_path) -> None:
    rows = _snapshot_rows(RestConnector(), cfg(api_base, "/records"), tmp_path)
    assert [r["id"] for r in rows] == [1, 2, 3]
    # Nested values survive as structure rather than being flattened to text -
    # the reason REST writes JSONL.
    assert rows[0]["tags"] == ["x", "y"]


def test_page_number_pagination_walks_to_the_end(api_base: str, tmp_path) -> None:
    config = cfg(
        api_base, "/paged", records_path="results",
        pagination="page_number", page_param="page",
    )
    rows = _snapshot_rows(RestConnector(), config, tmp_path)
    assert [r["id"] for r in rows] == [1, 2, 3], "should follow pages until one comes back empty"


def test_cursor_pagination_follows_the_cursor(api_base: str, tmp_path) -> None:
    config = cfg(
        api_base, "/cursored", records_path="results",
        pagination="cursor", cursor_path="meta.next", cursor_param="cursor",
    )
    rows = _snapshot_rows(RestConnector(), config, tmp_path)
    assert [r["id"] for r in rows] == [1, 2, 3], "should stop when the cursor comes back null"


def test_an_empty_collection_is_empty_not_an_error(api_base: str, tmp_path) -> None:
    connector = RestConnector()
    extract = connector.snapshot(
        cfg(api_base, "/empty"), {}, source_schema="", source_table="records",
        dest_dir=str(tmp_path), max_bytes=1024,
    )
    assert extract.empty is True


def test_the_byte_cap_stops_a_large_response(api_base: str, tmp_path) -> None:
    with pytest.raises(SourceReadError) as exc:
        RestConnector().snapshot(
            cfg(api_base, "/records"), {}, source_schema="", source_table="records",
            dest_dir=str(tmp_path), max_bytes=10,
        )
    assert "exceeds" in str(exc.value)


def test_there_is_no_server_side_cursor(api_base: str) -> None:
    """REST has no universal "changed since", so incremental mode still
    fetches everything and merges - asserted so the absence is deliberate."""
    assert RestConnector().max_cursor_value(
        cfg(api_base, "/records"), {},
        source_schema="", source_table="records", cursor_column="id",
    ) is None


# ---- end to end through the platform ----------------------------------------
@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    conn_routes.configure_secrets_gateway(InMemorySecretsGateway())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("rest-storage")))
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


def test_full_sync_of_a_paginated_api(client: TestClient, fx: Fixture, api_base: str) -> None:
    r = client.post(
        cbase(fx),
        headers=hdr(fx.editor_sub),
        json={
            "name": f"Fixture API {uuid.uuid4().hex[:6]}",
            "source_type": "rest",
            "config": cfg(
                api_base, "/cursored", records_path="results",
                pagination="cursor", cursor_path="meta.next",
            ),
            "secret": {},
        },
    )
    assert r.status_code == 201, r.text
    cid = r.json()["id"]

    assert client.post(f"{cbase(fx)}/{cid}/test", headers=hdr(fx.editor_sub)).json()["ok"] is True

    r = client.post(
        f"{cbase(fx)}/{cid}/sync",
        headers=hdr(fx.editor_sub),
        json={"source_schema": "", "source_table": "cursored",
              "dataset_name": f"API Records {fx.tag}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True, body["error"]
    assert body["rows_synced"] == 3

    detail = client.get(
        f"{dbase(fx)}/{body['dataset']['id']}", headers=hdr(fx.viewer_sub)
    ).json()
    schema = {c["name"]: c["data_type"] for c in detail["table_schema"]}
    # JSON types survive into the dataset rather than everything becoming text.
    assert schema["id"] == "BIGINT"
    assert schema["active"] == "BOOLEAN"


def test_the_api_appears_in_the_source_type_catalog(client: TestClient, fx: Fixture) -> None:
    r = client.get(f"{cbase(fx)}/source-types", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200
    types = {t["type"]: t for t in r.json()}
    assert {"postgres", "mysql", "s3", "rest"} <= set(types)
    rest = types["rest"]
    assert set(rest["secret_fields"]) == {"api_key", "client_id", "client_secret"}
    # The enum fields render as pickers in the wizard rather than free text.
    assert rest["config_schema"]["properties"]["auth_type"]["enum"]
    assert rest["config_schema"]["properties"]["pagination"]["enum"]
