"""File-based syncs: a folder, a transaction type, and filters (§749;
decision 0021; `data-connection` p.160-164).

> "Each run will ingest all files nested in the external system's
>  subdirectory, including files ingested in previous runs, and commit a
>  SNAPSHOT transaction to the output dataset containing exactly those
>  files." (p.160)

The pure rules first, then each of p.160-162's four modes run against a real
moto S3 server: what the dataset holds after each run, the version's
transaction type, and what a run that cannot read a file leaves behind.
"""
from __future__ import annotations

import os
import sys
import time
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("moto", reason="moto not installed")

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from test_s3_connector import (  # noqa: E402,F401 (fixtures)
    ACCESS_KEY, BUCKET, PREFIX, REGION, SECRET_KEY, s3, s3_endpoint,
)
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import connections as conn_routes  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services import file_syncs  # noqa: E402
from src.services.file_syncs import FileSyncError  # noqa: E402
from src.services.secrets import InMemorySecretsGateway  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

ADMIN_DSN = os.environ.get(
    "TEST_ADMIN_DSN", "postgresql://platform:devpass@localhost:5432/platform?sslmode=disable")


# ---- the rules ------------------------------------------------------------------
def f(path: str, size: int = 10, modified: str = "2026-01-01T00:00:00.000000+0000") -> dict:
    return {"path": path, "size": size, "modified": modified}


def test_filters_are_checked_and_normalised() -> None:
    assert file_syncs.parse_filters(None) == {}
    assert file_syncs.parse_filters({"exclude_synced": True}) == {
        "exclude_synced": {"by_modified": False, "by_size": False}}
    assert file_syncs.parse_filters({"modified_after": "2026-02-01"}) == {
        "modified_after": "2026-02-01T00:00:00.000000+0000"}
    # Off is the same as not set.
    assert file_syncs.parse_filters({"exclude_synced": False, "path_matches": ""}) == {}
    for bad, said in (({"nonsense": 1}, "unknown filter nonsense"),
                      ({"path_matches": "("}, "not a regular expression"),
                      ({"path_matches": "a" * 201}, "of up to 200 characters"),
                      ({"limit": 0}, "limit is a whole number of at least 1"),
                      ({"size_min": True}, "size_min is a whole number"),
                      ({"size_min": 9, "size_max": 3}, "no file could pass"),
                      ({"modified_after": "soon"}, "modified_after is a date"),
                      ({"exclude_synced": {"by_colour": True}}, "exclude_synced is true")):
        with pytest.raises(FileSyncError, match=said):
            file_syncs.parse_filters(bad)


def test_p161s_contradictions_are_refused() -> None:
    """Decision 0021 §2: the settings that would make a run do something other
    than its type says."""
    plain = {"exclude_synced": {"by_modified": False, "by_size": False}}
    changes = {"exclude_synced": {"by_modified": True, "by_size": False}}
    with pytest.raises(FileSyncError, match="APPEND file sync needs Exclude files already synced"):
        file_syncs.check("APPEND", {})
    with pytest.raises(FileSyncError, match="needs an UPDATE file sync"):
        file_syncs.check("APPEND", changes)
    with pytest.raises(FileSyncError, match="needs an UPDATE file sync"):
        file_syncs.check("APPEND", {"exclude_synced": {"by_modified": False, "by_size": True}})
    with pytest.raises(FileSyncError, match="it is an APPEND"):
        file_syncs.check("UPDATE", plain)
    with pytest.raises(FileSyncError, match="transaction type is one of"):
        file_syncs.check("DELETE", {})
    file_syncs.check("APPEND", plain)
    file_syncs.check("UPDATE", changes)
    file_syncs.check("SNAPSHOT", {})
    file_syncs.check("SNAPSHOT", plain)  # p.162's trailing window


def test_select_applies_p164s_filters() -> None:
    listing = [f("b/2.csv", 50, "2026-03-01T00:00:00.000000+0000"),
               f("a/1.csv", 5, "2026-01-01T00:00:00.000000+0000"),
               f("a/old.json", 500, "2025-01-01T00:00:00.000000+0000")]
    names = lambda files: [x["path"] for x in files]  # noqa: E731
    # Oldest first, so a limited run drains a backlog in order.
    assert names(file_syncs.select(listing, {}, {})) == ["a/old.json", "a/1.csv", "b/2.csv"]
    assert names(file_syncs.select(listing, {"path_matches": r"\.csv$"}, {})) == ["a/1.csv", "b/2.csv"]
    assert names(file_syncs.select(listing, {"path_not_matches": "^a/"}, {})) == ["b/2.csv"]
    after = file_syncs.parse_filters({"modified_after": "2026-02-01"})
    assert names(file_syncs.select(listing, after, {})) == ["b/2.csv"]
    # "After" is after: a file modified at the instant itself is not.
    at = file_syncs.parse_filters({"modified_after": "2026-03-01T00:00:00+00:00"})
    assert file_syncs.select(listing, at, {}) == []
    assert names(file_syncs.select(listing, {"size_min": 10, "size_max": 100}, {})) == ["b/2.csv"]
    # p.164's "between" includes its ends.
    assert names(file_syncs.select(listing, {"size_min": 5, "size_max": 5}, {})) == ["a/1.csv"]
    assert names(file_syncs.select(listing, {"limit": 2}, {})) == ["a/old.json", "a/1.csv"]
    assert file_syncs.select(listing, {"at_least": 4}, {}) == []
    assert len(file_syncs.select(listing, {"at_least": 3}, {})) == 3
    # p.164: "If any file has a relative path matching … sync all files".
    assert file_syncs.select(listing, {"any_path_matches": "_SUCCESS"}, {}) == []
    assert len(file_syncs.select(listing, {"any_path_matches": "old"}, {})) == 3


def test_exclude_synced_keys_by_path_and_optionally_by_change() -> None:
    seen = {"a.csv": {"size": 10, "modified": "m1"}, "b.csv": {"size": 10, "modified": "m1"}}
    listing = [f("a.csv", 10, "m1"), f("b.csv", 99, "m2"), f("c.csv", 10, "m1")]
    names = lambda filters: [x["path"] for x in file_syncs.select(listing, filters, seen)]  # noqa: E731
    by = lambda **k: {"exclude_synced": {"by_modified": False, "by_size": False, **k}}  # noqa: E731
    assert names(by()) == ["c.csv"]
    # Oldest first: c.csv (m1) before the rewritten b.csv (m2).
    assert names(by(by_size=True)) == ["c.csv", "b.csv"]
    assert names(by(by_modified=True)) == ["c.csv", "b.csv"]
    assert names({}) == ["a.csv", "c.csv", "b.csv"]


def test_the_view_after_a_run() -> None:
    assert file_syncs.view_after("SNAPSHOT", ["a", "b"], ["c"]) == ["c"]
    assert file_syncs.view_after("APPEND", ["a", "b"], ["c"]) == ["a", "b", "c"]
    assert file_syncs.view_after("UPDATE", ["a", "b"], ["a", "c"]) == ["b", "a", "c"]


def test_a_files_rows_are_kept_under_the_file_as_it_was_taken() -> None:
    one = file_syncs.file_key("p/", "a.csv", 10, "m1")
    assert one.startswith("p/files/") and one.endswith(".parquet")
    assert one == file_syncs.file_key("p/", "a.csv", 10, "m1")
    assert one != file_syncs.file_key("p/", "a.csv", 11, "m1")
    assert one != file_syncs.file_key("p/", "a.csv", 10, "m2")
    assert one != file_syncs.file_key("p/", "b.csv", 10, "m1")


# ---- against a bucket -------------------------------------------------------------
@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory, s3) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    conn_routes.configure_secrets_gateway(InMemorySecretsGateway())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("file-sync-storage"))))
    with TestClient(create_app(), raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def cbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/connections"


class Folder:
    """A folder of its own in the bucket, and a connection syncing it."""

    def __init__(self, client: TestClient, fx: Fixture, s3, s3_endpoint: str) -> None:
        self.client, self.fx, self.s3 = client, fx, s3
        self.name = f"drop_{uuid.uuid4().hex[:6]}"
        r = client.post(cbase(fx), headers=hdr(fx.editor_sub), json={
            "name": f"Files {self.name}", "source_type": "s3",
            "config": {"bucket": BUCKET, "prefix": PREFIX, "region": REGION,
                       "endpoint_url": s3_endpoint},
            "secret": {"access_key_id": ACCESS_KEY, "secret_access_key": SECRET_KEY}})
        assert r.status_code == 201, r.text
        self.id = r.json()["id"]

    def put(self, path: str, body: bytes) -> None:
        self.s3.put_object(Bucket=BUCKET, Key=f"{PREFIX}{self.name}/{path}", Body=body)

    def configure(self, transaction: str = "SNAPSHOT", **filters):
        return self.client.put(
            f"{cbase(self.fx)}/{self.id}/scheduled-sync", headers=hdr(self.fx.editor_sub),
            json={"mode": "files", "folder": self.name, "file_transaction": transaction,
                  "file_filters": filters, "dataset_name": f"Files {self.name}"})

    def run(self) -> dict:
        r = self.client.post(f"{cbase(self.fx)}/{self.id}/scheduled-sync/run",
                             headers=hdr(self.fx.editor_sub))
        assert r.status_code == 200, r.text
        return r.json()

    def rows(self) -> list:
        did = self.run_dataset()
        r = self.client.get(
            f"/api/workspaces/{self.fx.workspace}/projects/{self.fx.project}/datasets/{did}/preview",
            headers=hdr(self.fx.viewer_sub))
        return sorted(r.json()["rows"])

    def run_dataset(self) -> str:
        with psycopg.connect(ADMIN_DSN) as conn:
            return str(conn.execute("SELECT sync_dataset_id FROM connections WHERE id = %s",
                                    (self.id,)).fetchone()[0])

    def types(self) -> list[str]:
        with psycopg.connect(ADMIN_DSN) as conn:
            return [r[0] for r in conn.execute(
                "SELECT transaction_type FROM dataset_versions WHERE dataset_id = %s "
                "ORDER BY version_number", (self.run_dataset(),)).fetchall()]

    def files(self) -> list[str]:
        with psycopg.connect(ADMIN_DSN) as conn:
            return sorted(r[0] for r in conn.execute(
                "SELECT filename FROM dataset_files WHERE dataset_id = %s",
                (self.run_dataset(),)).fetchall())


@pytest.fixture()
def folder(client, fx, s3, s3_endpoint) -> Folder:
    return Folder(client, fx, s3, s3_endpoint)


def test_batch_mirror_takes_every_nested_file_each_run(folder: Folder) -> None:
    """p.160: "including files ingested in previous runs"."""
    folder.put("a.csv", b"id,v\n1,a\n")
    folder.put("deeper/b.csv", b"id,v\n2,b\n")
    folder.put("notes.txt", b"not data")
    assert folder.configure().status_code == 200
    first = folder.run()
    assert first["ok"], first
    assert first["files_taken"] == ["a.csv", "deeper/b.csv"]
    assert folder.rows() == [[1, "a"], [2, "b"]]
    folder.put("c.csv", b"id,v\n3,c\n")
    # S3's LastModified is to the second, so files put together sort by path.
    assert sorted(folder.run()["files_taken"]) == ["a.csv", "c.csv", "deeper/b.csv"]
    assert folder.rows() == [[1, "a"], [2, "b"], [3, "c"]]
    assert folder.types() == ["SNAPSHOT", "SNAPSHOT"]
    assert folder.files() == ["a.csv", "c.csv", "deeper/b.csv"]


def test_incremental_append_takes_only_new_files(folder: Folder) -> None:
    """p.161: "Each run will ingest all files that have not yet been
    ingested, keyed by file path name, and commit an APPEND transaction"."""
    folder.put("a.csv", b"id,v\n1,a\n")
    assert folder.configure("APPEND", exclude_synced=True).status_code == 200
    assert folder.run()["files_taken"] == ["a.csv"]
    folder.put("b.csv", b"id,v\n2,b\n")
    second = folder.run()
    assert (second["files_taken"], second["rows_synced"]) == (["b.csv"], 1)
    assert folder.rows() == [[1, "a"], [2, "b"]]
    # Nothing new: no version, and the run says so by taking nothing.
    third = folder.run()
    assert third["ok"] and third["files_taken"] == []
    assert folder.types() == ["APPEND", "APPEND"]


def test_incremental_update_replaces_a_changed_file(folder: Folder) -> None:
    """p.161-162: "ingest all files that have not yet been ingested or have
    since changed … and commit an UPDATE transaction"."""
    folder.put("a.csv", b"id,v\n1,a\n")
    folder.put("b.csv", b"id,v\n2,b\n")
    assert folder.configure("UPDATE", exclude_synced={"by_size": True}).status_code == 200
    folder.run()
    folder.put("a.csv", b"id,v\n1,a-changed\n")
    second = folder.run()
    assert second["files_taken"] == ["a.csv"]
    # a.csv's old row is gone, not kept beside the new one.
    assert folder.rows() == [[1, "a-changed"], [2, "b"]]
    assert folder.types() == ["UPDATE", "UPDATE"]
    # Remembered as it is now, so an unchanged folder takes nothing - and the
    # run still names the dataset it left as it was.
    third = folder.run()
    assert third["files_taken"] == [] and third["dataset"]["current_version"] == 2


def test_a_trailing_window_holds_only_the_last_runs_new_files(folder: Folder) -> None:
    """p.162: "containing only files that were never present in any previous
    job run"."""
    folder.put("a.csv", b"id,v\n1,a\n")
    assert folder.configure("SNAPSHOT", exclude_synced=True).status_code == 200
    folder.run()
    folder.put("b.csv", b"id,v\n2,b\n")
    folder.run()
    assert folder.rows() == [[2, "b"]]
    assert folder.files() == ["b.csv"]
    assert folder.types() == ["SNAPSHOT", "SNAPSHOT"]


def test_by_modified_sees_a_rewritten_file_of_the_same_size(folder: Folder) -> None:
    folder.put("a.csv", b"id,v\n1,a\n")
    assert folder.configure("UPDATE", exclude_synced={"by_modified": True}).status_code == 200
    folder.run()
    time.sleep(1.1)  # S3's LastModified is to the second
    folder.put("a.csv", b"id,v\n1,z\n")
    assert folder.run()["files_taken"] == ["a.csv"]
    assert folder.rows() == [[1, "z"]]


def test_a_file_that_cannot_be_read_fails_the_whole_run(folder: Folder) -> None:
    """p.163: "If a sync fails at any point, the transaction is aborted and
    none of the files from that run are committed"."""
    folder.put("a.csv", b"id,v\n1,a\n")
    assert folder.configure("APPEND", exclude_synced=True).status_code == 200
    folder.run()
    folder.put("b.csv", b"id,v\n2,b\n")
    folder.put("c.csv", b"other,columns,here\nx,y,z\n")
    failed = folder.run()
    assert not failed["ok"] and failed["files_taken"] == []
    assert "c.csv" in failed["error"]
    assert folder.rows() == [[1, "a"]], "b.csv was not committed either"
    assert folder.types() == ["APPEND"]
    # And it was not remembered: once c.csv is fixed, both are taken.
    folder.put("c.csv", b"id,v\n3,c\n")
    assert folder.run()["files_taken"] == ["b.csv", "c.csv"]


def test_filters_choose_the_files(folder: Folder) -> None:
    folder.put("keep/a.csv", b"id,v\n1,a\n")
    folder.put("skip/b.csv", b"id,v\n2,b\n")
    folder.put("keep/c.csv", b"id,v\n3,c\n")
    assert folder.configure(path_matches="^keep/", limit=1).status_code == 200
    assert len(folder.run()["files_taken"]) == 1
    assert folder.configure(path_matches="^keep/", at_least=3).status_code == 200
    taken = folder.run()
    assert taken["ok"] and taken["files_taken"] == []


def test_settings_a_file_sync_cannot_have_are_refused(client, fx, folder: Folder) -> None:
    r = folder.configure("APPEND")
    assert r.status_code == 422, r.text
    assert "needs Exclude files already synced" in r.text
    r = client.put(f"{cbase(fx)}/{folder.id}/scheduled-sync", headers=hdr(fx.editor_sub),
                   json={"mode": "files", "folder": folder.name, "cron_schedule": "0 * * * *"})
    assert r.status_code == 422 and "not built yet" in r.text, r.text
    r = client.put(f"{cbase(fx)}/{folder.id}/scheduled-sync", headers=hdr(fx.editor_sub),
                   json={"mode": "full", "source_schema": "x"})
    assert r.status_code == 422 and "needs a source table" in r.text, r.text


def test_a_folder_that_climbs_out_of_the_prefix_is_refused(folder: Folder) -> None:
    folder.s3.put_object(Bucket=BUCKET, Key="private/secrets.csv", Body=b"k,v\ntop,secret\n")
    r = folder.client.put(
        f"{cbase(folder.fx)}/{folder.id}/scheduled-sync", headers=hdr(folder.fx.editor_sub),
        json={"mode": "files", "folder": "../private"})
    assert r.status_code == 200, r.text
    ran = folder.run()
    assert not ran["ok"] and "invalid folder" in ran["error"]


def test_only_an_s3_source_has_files(client, fx) -> None:
    r = client.post(cbase(fx), headers=hdr(fx.editor_sub), json={
        "name": f"Tables {uuid.uuid4().hex[:6]}", "source_type": "postgres",
        "config": {"host": "localhost", "port": 5432, "database": "x", "user": "y"},
        "secret": {"password": "z"}})
    assert r.status_code == 201, r.text
    r = client.put(f"{cbase(fx)}/{r.json()['id']}/scheduled-sync", headers=hdr(fx.editor_sub),
                   json={"mode": "files", "folder": "x"})
    assert r.status_code == 422 and "has tables, not files" in r.text, r.text


def test_the_schedule_says_what_it_is(folder: Folder) -> None:
    r = folder.configure("UPDATE", exclude_synced={"by_size": True}, limit=5)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["sync_mode"], body["sync_source_schema"], body["sync_source_table"]) == (
        "files", folder.name, None)
    assert body["sync_file_transaction"] == "UPDATE"
    assert body["sync_file_filters"] == {
        "exclude_synced": {"by_modified": False, "by_size": True}, "limit": 5}


def test_a_file_that_does_not_parse_is_named(folder: Folder) -> None:
    folder.put("bad.json", b"{not json")
    assert folder.configure().status_code == 200
    failed = folder.run()
    assert not failed["ok"]
    assert failed["error"].startswith("bad.json could not be read")


def test_a_dataset_a_table_sync_made_is_a_new_view_when_files_take_it_over(
    client, fx, folder: Folder
) -> None:
    """Decision 0021 §3: a dataset holding none of this sync's files gets a
    SNAPSHOT, whatever the sync's type - an APPEND would claim the rows of the
    one-object sync before it were still there."""
    folder.put("a.csv", b"id,v\n1,a\n")
    r = client.put(f"{cbase(fx)}/{folder.id}/scheduled-sync", headers=hdr(fx.editor_sub), json={
        "mode": "full", "source_schema": folder.name, "source_table": "a.csv",
        "dataset_name": f"Files {folder.name}"})
    assert r.status_code == 200, r.text
    assert folder.run()["ok"]
    folder.put("b.csv", b"id,v\n2,b\n")
    assert folder.configure("APPEND", exclude_synced=True).status_code == 200
    assert folder.run()["ok"]
    assert folder.types() == ["SNAPSHOT", "SNAPSHOT"]
    assert folder.rows() == [[1, "a"], [2, "b"]]


def test_a_table_sync_carries_no_file_settings(client, fx, folder: Folder) -> None:
    assert folder.configure("APPEND", exclude_synced=True).status_code == 200
    r = client.put(f"{cbase(fx)}/{folder.id}/scheduled-sync", headers=hdr(fx.editor_sub), json={
        "mode": "full", "source_schema": folder.name, "source_table": "a.csv"})
    assert r.status_code == 200, r.text
    assert (r.json()["sync_file_transaction"], r.json()["sync_file_filters"]) == (None, None)
