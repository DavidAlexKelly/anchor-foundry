"""A listener's events, archived into a backing dataset (§519; db 0108;
`data-connection` p.264).

> "Every few minutes, the listener event stream will archive into a backing
> dataset. This dataset can be used like any other dataset in the platform"
> (p.264)
"""
from __future__ import annotations

import io
import os
import re
import sys
import uuid

import duckdb
import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import ADMIN_DSN, Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import connections as connection_routes  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services import listener_archive as archive_service  # noqa: E402
from src.services.secrets import InMemorySecretsGateway  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

WORKER = os.path.join(os.path.dirname(__file__), "..", "..", "worker", "src", "anchor_worker",
                      "jobs", "listener_archives.py")


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def storage(tmp_path_factory) -> LocalStorageGateway:
    return LocalStorageGateway(str(tmp_path_factory.mktemp("archive-storage")))


@pytest.fixture(scope="module")
def client(storage) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    connection_routes.configure_secrets_gateway(InMemorySecretsGateway())
    ds_routes.configure_storage_gateway(storage)
    with TestClient(create_app(), raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def base(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


def listener(client, fx, name: str | None = None) -> dict:
    r = client.post(f"{base(fx)}/listeners", headers=hdr(fx.editor_sub),
                    json={"display_name": name or f"Hook {uuid.uuid4().hex[:6]}"})
    made = r.json()
    client.post(f"{base(fx)}/listeners/{made['id']}/start", headers=hdr(fx.editor_sub))
    return made


def send(client, made: dict, body: bytes, **headers) -> None:
    path = "/api/listen/" + made["endpoints"][0]["url"].rsplit("/api/listen/", 1)[1]
    assert client.post(path, content=body, headers=headers).status_code == 200


def archive(client, fx, made: dict, sub=None):
    return client.post(f"{base(fx)}/listeners/{made['id']}/archive", headers=hdr(sub or fx.editor_sub))


def rows_of(storage, fx, dataset_name: str) -> list[tuple]:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        key = conn.execute("SELECT s3_location FROM datasets WHERE project_id = %s AND name = %s",
                           (fx.project, dataset_name)).fetchone()[0]
    return duckdb.connect().execute(
        "SELECT event_id, content_type, size_bytes, body, headers FROM read_parquet(?) ORDER BY event_id",
        [storage.local_path(key)]).fetchall()


def test_archiving_makes_a_dataset_and_then_appends_to_it(client, fx, storage) -> None:
    made = listener(client, fx, f"Tickets {uuid.uuid4().hex[:6]}")
    send(client, made, b'{"n": 1}', **{"Content-Type": "application/json"})
    send(client, made, b'{"n": 2}')
    r = archive(client, fx, made)
    assert r.status_code == 200, r.text
    got = r.json()
    assert (got["archived"], got["version"]) == (2, 1)
    after = got["listener"]
    name = f"{made['display_name']} events"
    assert (after["archive_dataset_name"], after["pending_events"]) == (name, 0)
    assert after["archive_dataset_resource_id"] and after["archived_at"]
    first = rows_of(storage, fx, name)
    assert [(r[1], r[2], r[3]) for r in first] == [("application/json", 8, '{"n": 1}'), (None, 8, '{"n": 2}')]

    # The next run appends: the new version holds everything so far.
    send(client, made, "café".encode("latin-1"))
    assert client.get(f"{base(fx)}/listeners/{made['id']}", headers=hdr(fx.viewer_sub)).json()["pending_events"] == 1
    got = archive(client, fx, made).json()
    assert (got["archived"], got["version"]) == (1, 2)
    rows = rows_of(storage, fx, name)
    assert len(rows) == 3 and rows[2][3] == "caf�", "a body that is not UTF-8 keeps its place"
    # Nothing new: no version.
    got = archive(client, fx, made).json()
    assert (got["archived"], got["version"]) == (0, None)


def test_the_archive_is_an_ordinary_dataset_made_by_the_listener(client, fx) -> None:
    made = listener(client, fx)
    send(client, made, b"{}")
    dataset = archive(client, fx, made).json()["listener"]["archive_dataset_name"]
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        did, origin = conn.execute("SELECT id, origin FROM datasets WHERE project_id = %s AND name = %s",
                                   (fx.project, dataset)).fetchone()
    assert origin == "listener"
    # §506's origin says who made it.
    got = client.get(f"{base(fx)}/datasets/{did}/origin", headers=hdr(fx.viewer_sub)).json()
    assert got["tool"] == {"kind": "listener", "name": made["display_name"], "resource_id": None}
    schema = client.get(f"{base(fx)}/datasets/{did}", headers=hdr(fx.viewer_sub)).json()["table_schema"]
    assert [c["name"] for c in schema] == [n for n, _ in archive_service.COLUMNS]


def test_headers_are_archived_as_they_were_kept(client, fx, storage) -> None:
    made = listener(client, fx)
    send(client, made, b"{}", **{"X-Trace": "t1", "Authorization": "Bearer secret"})
    name = archive(client, fx, made).json()["listener"]["archive_dataset_name"]
    [row] = rows_of(storage, fx, name)
    assert '"x-trace": "t1"' in row[4] and '"authorization": "[redacted]"' in row[4]


def test_a_name_already_taken_gets_a_number(client, fx) -> None:
    name = f"Clash {uuid.uuid4().hex[:6]}"
    r = client.post(f"{base(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
                    data={"name": f"{name} events"}, files={"file": ("a.csv", io.BytesIO(b"id\n1\n"), "text/csv")})
    assert r.status_code == 201, r.text
    made = listener(client, fx, name)
    send(client, made, b"{}")
    assert archive(client, fx, made).json()["listener"]["archive_dataset_name"] == f"{name} events 2"


def test_one_run_takes_a_bounded_batch(client, fx, monkeypatch) -> None:
    """A backlog catches up over several runs, and one event bigger than the
    byte ceiling is still taken, so it cannot stall the archive."""
    made = listener(client, fx)
    for n in range(5):
        send(client, made, b"x" * 10)
    monkeypatch.setattr(archive_service, "ARCHIVE_EVENTS", 2)
    assert archive(client, fx, made).json()["archived"] == 2
    assert archive(client, fx, made).json()["archived"] == 2
    monkeypatch.setattr(archive_service, "ARCHIVE_EVENTS", 100)
    # An event bigger than the whole ceiling is still taken, alone.
    monkeypatch.setattr(archive_service, "ARCHIVE_BYTES", 5)
    got = archive(client, fx, made).json()
    assert got["archived"] == 1 and got["listener"]["pending_events"] == 0
    monkeypatch.setattr(archive_service, "ARCHIVE_BYTES", 15)
    send(client, made, b"y" * 10)
    send(client, made, b"z" * 5)
    # 10 then 15 in total: both fit exactly.
    assert archive(client, fx, made).json()["archived"] == 2


def test_a_deleted_dataset_starts_the_archive_over(client, fx, storage) -> None:
    made = listener(client, fx)
    send(client, made, b"1")
    send(client, made, b"2")
    name = archive(client, fx, made).json()["listener"]["archive_dataset_name"]
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("DELETE FROM datasets WHERE project_id = %s AND name = %s", (fx.project, name))
    listed = client.get(f"{base(fx)}/listeners/{made['id']}", headers=hdr(fx.viewer_sub)).json()
    assert (listed["archive_dataset_name"], listed["pending_events"]) == (None, 2)
    got = archive(client, fx, made).json()
    assert (got["archived"], got["version"]) == (2, 1)
    assert [r[3] for r in rows_of(storage, fx, name)] == ["1", "2"]


def test_the_worker_finds_what_needs_archiving(client, fx) -> None:
    quiet = listener(client, fx)
    busy = listener(client, fx)
    send(client, busy, b"{}")
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        found = {str(r[0]) for r in conn.execute("SELECT listener_id FROM list_listeners_to_archive()")}
    assert busy["id"] in found and quiet["id"] not in found
    archive(client, fx, busy)
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        found = {str(r[0]) for r in conn.execute("SELECT listener_id FROM list_listeners_to_archive()")}
    assert busy["id"] not in found


def test_archiving_is_an_editor_s_and_within_the_project(client, fx, storage) -> None:
    made = listener(client, fx)
    send(client, made, b"{}")
    assert archive(client, fx, made, sub=fx.viewer_sub).status_code == 403
    other = client.post(f"/api/workspaces/{fx.workspace}/projects", headers=hdr(fx.editor_sub),
                        json={"name": f"Elsewhere {uuid.uuid4().hex[:6]}"}).json()

    def files() -> int:
        return sum(len(names) for _, _, names in os.walk(storage._root))
    before = files()
    r = client.post(f"/api/workspaces/{fx.workspace}/projects/{other['id']}/listeners/{made['id']}/archive",
                    headers=hdr(fx.editor_sub))
    assert r.status_code == 404
    # Refused before anything is written, not rolled back after: a Parquet
    # file is not in the transaction.
    assert files() == before


def test_the_worker_archives_with_the_same_code() -> None:
    """The block between the SHARED markers is the same text in the API and
    the worker, since two archivers that disagreed about a column would write
    two shapes into one dataset."""
    def shared(path: str) -> str:
        source = open(path).read()
        found = re.search(r"# ---- SHARED with [^\n]*\n(.*?)# ---- end SHARED", source, re.S)
        assert found, path
        return found.group(1)
    assert shared(archive_service.__file__) == shared(WORKER)
