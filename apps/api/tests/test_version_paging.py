"""A dataset's history is read a page at a time (§879).

A dataset synced every five minutes has a hundred thousand versions a year,
and the history answered every one of them on every visit, each with its
schema and its own S3 HEAD. It is a page now, newest first, and each row
carries what reading it used to need the whole history for: the version
before's row count, and whether it begins a view. The page says what is
true of the whole: how many versions, how many views, where the current one
begins.
"""
from __future__ import annotations

import json
import os
import sys

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, hdr  # noqa: E402
from test_datasets import base, client, fx, storage, upload  # noqa: E402,F401

ADMIN_DSN = os.environ["TEST_ADMIN_DSN"]
#: v1 is the upload's own SNAPSHOT; these follow it.
LATER = ["APPEND", "APPEND", "SNAPSHOT", "APPEND", "UPDATE", "APPEND"]


@pytest.fixture(scope="module")
def history(client: TestClient, fx: Fixture) -> str:  # noqa: F811
    made = upload(client, fx, fx.editor_sub, name=f"Paged {fx.tag}")
    assert made.status_code == 201, made.text
    did = made.json()["id"]
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        for n, kind in enumerate(LATER, start=2):
            conn.execute(
                """INSERT INTO dataset_versions (dataset_id, version_number, table_schema,
                                                 row_count, produced_by_kind, transaction_type)
                   VALUES (%s, %s, %s, %s, 'sync', %s)""",
                (did, n, json.dumps([{"name": "id", "data_type": "BIGINT"}]), 3 + n * 10, kind))
        conn.execute("UPDATE datasets SET current_version = %s WHERE id = %s", (len(LATER) + 1, did))
    return did


def page(client: TestClient, fx: Fixture, did: str, **params) -> dict:  # noqa: F811
    r = client.get(f"{base(fx)}/{did}/versions", params=params, headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return r.json()


def test_a_page_is_the_newest_and_says_what_is_true_of_all(client, fx, history) -> None:  # noqa: F811
    first = page(client, fx, history, limit=3)
    assert [v["version_number"] for v in first["items"]] == [7, 6, 5]
    assert first["total"] == 7 and first["newest"] == 7
    # v1 (the upload) and v4 begin views; the current one begins at v4.
    assert (first["views"], first["view_start"]) == (2, 4)


def test_the_next_page_starts_under_the_last_and_rows_read_as_in_the_whole(
    client, fx, history  # noqa: F811
) -> None:
    whole = page(client, fx, history, limit=200)["items"]
    second = page(client, fx, history, limit=3, before=5)["items"]
    assert [v["version_number"] for v in second] == [4, 3, 2]
    by_number = {v["version_number"]: v for v in whole}
    for row in second:
        # The change on a page's last row is the one the whole history shows.
        assert row["previous_row_count"] == by_number[row["version_number"] - 1]["row_count"]
    assert [v["starts_view"] for v in whole] == [False, False, False, True, False, False, True]
    assert whole[-1]["previous_row_count"] is None


def test_a_page_is_bounded(client, fx, history) -> None:  # noqa: F811
    assert len(page(client, fx, history)["items"]) == 7  # under the default page
    r = client.get(f"{base(fx)}/{history}/versions", params={"limit": 500},
                   headers=hdr(fx.viewer_sub))
    assert r.status_code == 422


def test_views_follow_p26_when_there_is_no_snapshot_and_when_the_first_is_one(
    client, fx  # noqa: F811
) -> None:
    """p.26: a view begins at the latest SNAPSHOT, or at the earliest version
    when there is none. Moved to the server with §879; these were the web's
    cases."""
    def history_of(kinds: list[str]) -> dict:
        made = upload(client, fx, fx.editor_sub, name=f"Views {fx.tag} {'-'.join(kinds)}")
        did = made.json()["id"]
        with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
            conn.execute("UPDATE dataset_versions SET transaction_type = %s WHERE dataset_id = %s",
                         (kinds[0], did))
            for n, kind in enumerate(kinds[1:], start=2):
                conn.execute(
                    """INSERT INTO dataset_versions (dataset_id, version_number, row_count,
                                                     transaction_type) VALUES (%s, %s, 1, %s)""",
                    (did, n, kind))
        return page(client, fx, did)

    appended = history_of(["APPEND", "APPEND", "APPEND"])  # a listener's archive
    assert (appended["views"], appended["view_start"]) == (1, 1)
    assert [v["starts_view"] for v in appended["items"]] == [False, False, True]

    snapshots = history_of(["SNAPSHOT", "SNAPSHOT"])  # the first is not counted twice
    assert (snapshots["views"], snapshots["view_start"]) == (2, 2)
