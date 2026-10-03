"""p.195-196's four transactional export modes, run against a real table
(§748; decision 0020 §4; `data-connection` p.195-196).

What each mode *plans* is `test_exports.py`'s. These run each one against a
Postgres destination over a dataset whose versions are real transactions:
an upload (SNAPSHOT), p.10's new file (APPEND), p.10's replaced file (UPDATE)
and a re-parse (SNAPSHOT), and read back what the table holds.
"""
from __future__ import annotations

import io
import os
import sys
import uuid

import psycopg
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, hdr  # noqa: E402
from test_export_runs import (  # noqa: E402,F401 (fixtures)
    ADMIN_DSN, base, client, destination, destination_connection, fx, make_export,
    make_table, rows_in, run, storage_root,
)

CSV = b"id,email\n1,ada@example.com\n2,grace@example.com\n"


class Dataset:
    """An uploaded dataset whose next version is whichever transaction the
    test asks for."""

    def __init__(self, client: TestClient, fx: Fixture) -> None:
        self.client, self.fx = client, fx
        r = client.post(f"{base(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
                        data={"name": f"txn_{uuid.uuid4().hex[:6]}"},
                        files={"file": ("seed.csv", io.BytesIO(CSV), "text/csv")})
        assert r.status_code == 201, r.text
        self.id = r.json()["id"]

    def append(self, filename: str, body: bytes) -> None:
        r = self.client.post(f"{base(self.fx)}/datasets/{self.id}/files",
                             headers=hdr(self.fx.editor_sub),
                             files={"file": (filename, io.BytesIO(body), "text/csv")})
        assert r.status_code == 200 and r.json()["mode"] == "append", r.text

    def replace(self, body: bytes) -> None:
        r = self.client.post(f"{base(self.fx)}/datasets/{self.id}/files",
                             headers=hdr(self.fx.editor_sub),
                             files={"file": ("seed.csv", io.BytesIO(body), "text/csv")})
        assert r.status_code == 200 and r.json()["mode"] == "update", r.text

    def snapshot(self) -> None:
        """A re-parse with nothing chosen: the same rows, as a new view."""
        r = self.client.post(f"{base(self.fx)}/datasets/{self.id}/parse",
                             headers=hdr(self.fx.editor_sub), json={})
        assert r.status_code == 200, r.text


def export(client, fx, destination, dataset: Dataset, mode: str) -> str:
    table = f"t_{mode}_{uuid.uuid4().hex[:6]}"
    make_table(table, "id bigint, email text")
    cid = destination_connection(client, fx, destination)
    r = make_export(client, fx, cid, dataset.id, mode=mode,
                    destination={"schema": "public", "table": table})
    assert r.status_code == 201, r.text
    return r.json()["id"], table


def ids(table: str) -> list[int]:
    return [r[0] for r in rows_in(table)]


def last_version(export_id: str) -> int | None:
    with psycopg.connect(ADMIN_DSN) as conn:
        return conn.execute("SELECT last_version FROM exports WHERE id = %s",
                            (export_id,)).fetchone()[0]


def test_efficient_mirror_sends_new_rows_and_clears_for_a_new_view(
    client: TestClient, fx: Fixture, destination: dict
) -> None:
    """p.195: "always incrementally exporting any unexported transactions from
    the current dataset view and truncating the external table when there is a
    SNAPSHOT transaction"."""
    data = Dataset(client, fx)
    export_id, table = export(client, fx, destination, data, "efficient_mirror")
    first = run(client, fx, export_id)
    assert (first["status"], first["rows_written"]) == ("succeeded", 2)
    assert first["detail"] == "cleared the table, then sent the whole view at v1"

    data.append("more.csv", b"id,email\n3,alan@example.com\n")
    second = run(client, fx, export_id)
    # **One row, not three**: the APPEND's rows only, onto what is there.
    assert (second["rows_written"], second["detail"]) == (1, "sent the rows v2 added")
    assert ids(table) == [1, 2, 3]

    assert run(client, fx, export_id)["skipped"] is True

    data.snapshot()
    third = run(client, fx, export_id)
    assert third["detail"] == "cleared the table, then sent the whole view at v3"
    assert ids(table) == [1, 2, 3], "a new view replaces the table, so nothing doubles"


def test_an_update_is_refused_and_the_table_is_left_as_it_was(
    client: TestClient, fx: Fixture, destination: dict
) -> None:
    """p.195: "This mode does not support UPDATE and DELETE transactions"."""
    data = Dataset(client, fx)
    export_id, table = export(client, fx, destination, data, "efficient_mirror")
    run(client, fx, export_id)
    data.replace(b"id,email\n1,ada@new.example\n2,grace@example.com\n")
    refused = run(client, fx, export_id)
    assert refused["status"] == "failed"
    assert refused["error"].startswith("v2 is an UPDATE transaction")
    assert "mirror export" in refused["error"]
    assert rows_in(table) == [(1, "ada@example.com"), (2, "grace@example.com")]
    assert last_version(export_id) == 1, "a refused run does not move the mark"
    # A new view gets it moving again, and sends the dataset as it is.
    data.snapshot()
    assert run(client, fx, export_id)["status"] == "succeeded"
    assert rows_in(table) == [(1, "ada@new.example"), (2, "grace@example.com")]


def test_incremental_sends_a_new_view_whole_and_that_duplicates(
    client: TestClient, fx: Fixture, destination: dict
) -> None:
    """p.196: "This mode may produce duplicate records in the target table if
    the upstream dataset has a SNAPSHOT transaction"."""
    data = Dataset(client, fx)
    export_id, table = export(client, fx, destination, data, "incremental")
    assert run(client, fx, export_id)["detail"] == "sent the whole view at v1"
    data.append("more.csv", b"id,email\n3,alan@example.com\n")
    assert run(client, fx, export_id)["rows_written"] == 1
    assert ids(table) == [1, 2, 3]
    data.snapshot()
    run(client, fx, export_id)
    assert ids(table) == [1, 1, 2, 2, 3, 3]


def test_incremental_truncate_clears_and_sends_only_the_new_rows(
    client: TestClient, fx: Fixture, destination: dict
) -> None:
    """p.196: "useful when treating the target table like a message queue"."""
    data = Dataset(client, fx)
    export_id, table = export(client, fx, destination, data, "incremental_truncate")
    run(client, fx, export_id)
    assert ids(table) == [1, 2]
    data.append("more.csv", b"id,email\n3,alan@example.com\n4,hedy@example.com\n")
    second = run(client, fx, export_id)
    assert second["detail"] == "cleared the table, then sent the rows v2 added"
    assert ids(table) == [3, 4]


def test_append_only_fails_on_a_new_view_after_its_first_run(
    client: TestClient, fx: Fixture, destination: dict
) -> None:
    """p.196: "failing if there is a SNAPSHOT, UPDATE, or DELETE transaction
    (after the first run)… guarantees there will never be duplicate data"."""
    data = Dataset(client, fx)
    export_id, table = export(client, fx, destination, data, "append_only")
    run(client, fx, export_id)
    data.append("more.csv", b"id,email\n3,alan@example.com\n")
    data.append("most.csv", b"id,email\n4,hedy@example.com\n")
    assert run(client, fx, export_id)["detail"] == "sent the rows v2, v3 added"
    assert ids(table) == [1, 2, 3, 4]
    data.snapshot()
    refused = run(client, fx, export_id)
    assert refused["status"] == "failed"
    assert refused["error"].startswith("v4 is a SNAPSHOT transaction")
    assert ids(table) == [1, 2, 3, 4]


def test_an_append_whose_previous_version_is_gone_names_mirror(
    client: TestClient, fx: Fixture, destination: dict
) -> None:
    """Decision 0020 §4: an APPEND's rows are computed from it and the version
    before, so without the earlier one's bytes they cannot be told apart."""
    data = Dataset(client, fx)
    export_id, table = export(client, fx, destination, data, "incremental")
    run(client, fx, export_id)
    data.append("more.csv", b"id,email\n3,alan@example.com\n")
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE dataset_versions SET s3_manifest_key = NULL "
                     "WHERE dataset_id = %s AND version_number = 1", (data.id,))
    refused = run(client, fx, export_id)
    assert refused["status"] == "failed"
    assert refused["error"].startswith("v1 is no longer stored, so the rows v2 added")
    assert ids(table) == [1, 2]


def test_rows_an_append_repeats_are_still_sent(
    client: TestClient, fx: Fixture, destination: dict
) -> None:
    """`EXCEPT ALL`, not `EXCEPT`: a file that adds a row equal to one already
    there added a row, and the table should have it twice as the dataset does."""
    data = Dataset(client, fx)
    export_id, table = export(client, fx, destination, data, "incremental")
    run(client, fx, export_id)
    data.append("again.csv", b"id,email\n1,ada@example.com\n")
    assert run(client, fx, export_id)["rows_written"] == 1
    assert ids(table) == [1, 1, 2]
