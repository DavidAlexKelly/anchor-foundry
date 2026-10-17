"""The project's lists ask the database the same number of times however long
they are (§986).

A list that asks once per row - each dataset's latest version, each model's
inputs, each connection's last sync - is fast with the three rows a test
makes and slow with the three hundred a team does, and nothing shows it until
then. These count the statements a list's request sends with a few rows and
with more, and hold the two equal.
"""
from __future__ import annotations

import io
import os
import sys
import uuid
from contextlib import contextmanager
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.lib import db  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import connections as conn_routes  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services.secrets import InMemorySecretsGateway  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    auth_mw.configure_verifier(LocalVerifier())
    conn_routes.configure_secrets_gateway(InMemorySecretsGateway())
    ds_routes.configure_storage_gateway(LocalStorageGateway(str(tmp_path_factory.mktemp("counts"))))
    with TestClient(create_app(), raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


@contextmanager
def counted() -> Iterator[list[str]]:
    seen: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany) -> None:
        seen.append(statement)

    engine = db.get_engine().sync_engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", record)


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


def base(fx: Fixture) -> str:
    return f"{wbase(fx)}/projects/{fx.project}"


def grow(client: TestClient, fx: Fixture, n: int) -> None:
    """`n` more of each: an uploaded dataset, a model reading it, a connection."""
    for _ in range(n):
        tag = uuid.uuid4().hex[:6]
        r = client.post(f"{base(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
                        data={"name": f"rows_{tag}"},
                        files={"file": ("rows.csv", io.BytesIO(b"id,v\n1,a\n"), "text/csv")})
        assert r.status_code == 201, r.text
        did = r.json()["id"]
        r = client.post(f"{base(fx)}/models", headers=hdr(fx.editor_sub), json={
            "name": f"Model {tag}", "code": "SELECT * FROM rows",
            "inputs": [{"dataset_id": did, "input_alias": "rows"}]})
        assert r.status_code == 201, r.text
        r = client.post(f"{base(fx)}/models/{r.json()['id']}/run", headers=hdr(fx.editor_sub))
        assert r.status_code == 200, r.text
        r = client.post(f"{base(fx)}/connections", headers=hdr(fx.editor_sub), json={
            "name": f"Source {tag}", "source_type": "postgres",
            "config": {"host": "localhost", "database": "nowhere", "user": "nobody"}})
        assert r.status_code == 201, r.text
        r = client.post(f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub), json={
            "api_name": f"row_{tag}", "display_name": f"Row {tag}",
            "properties": [{"api_name": "v", "data_type": "string"}]})
        assert r.status_code == 201, r.text
        r = client.post(f"{base(fx)}/object-type-sources", headers=hdr(fx.editor_sub), json={
            "object_type_id": r.json()["id"], "dataset_id": did, "primary_key_column": "id",
            "column_mappings": {"v": "v"}})
        assert r.status_code == 201, r.text
        r = client.post(f"{base(fx)}/object-type-sources/{r.json()['id']}/sync",
                        headers=hdr(fx.editor_sub))
        assert r.status_code == 200, r.text
        r = client.post(f"{base(fx)}/canvas-apps", headers=hdr(fx.editor_sub),
                        json={"name": f"Module {tag}"})
        assert r.status_code == 201, r.text


#: Under the project, or, starting `~`, under the workspace.
LISTS = [
    "/datasets",
    "/models",
    "/connections",
    "/connections/sync-health",
    "/exports",
    "/pipeline",
    "/canvas-apps",
    "/object-type-sources",
    "~/object-types",
    "~/projects",
    "/resources",
]


def url(fx: Fixture, path: str) -> str:
    return f"{wbase(fx)}{path[1:]}" if path.startswith("~") else f"{base(fx)}{path}"



@pytest.fixture(scope="module")
def counts(client: TestClient) -> dict[str, tuple[int, int]]:
    """Each list's statements with two of everything, then with six."""
    fx = Fixture()
    found: dict[str, list[int]] = {path: [] for path in LISTS}
    for size in (2, 4):
        grow(client, fx, size)
        for path in LISTS:
            # Once first, so who is asking is already known (the identity
            # cache) and what is counted is the list.
            client.get(url(fx, path), headers=hdr(fx.viewer_sub))
            with counted() as seen:
                r = client.get(url(fx, path), headers=hdr(fx.viewer_sub))
            assert r.status_code == 200, (path, r.text)
            found[path].append(len(seen))
    return {path: (small, large) for path, (small, large) in found.items()}


@pytest.mark.parametrize("path", LISTS)
def test_a_list_asks_the_same_number_of_times_however_long_it_is(counts, path) -> None:
    small, large = counts[path]
    assert large == small, f"{path}: {small} statements with 2 of each, {large} with 6"
