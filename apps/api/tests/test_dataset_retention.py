"""A dataset's retention policy, and what it would remove (§964; decision 0005).

Nothing here deletes anything: the sweeper is the next unit. What these hold
is the answer it will act on - which versions a policy lets go - because a
delete is only as safe as that answer, and the decision's own order is to
show it before anything is removed.
"""
from __future__ import annotations

import os
import sys
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import hdr  # noqa: E402
from test_time_travel import base, client, fx, versioned  # noqa: E402,F401 (fixtures)

ADMIN_DSN = os.environ["TEST_ADMIN_DSN"]


def put(client: TestClient, fx, dataset: str, keep, who=None):
    return client.put(f"{base(fx)}/datasets/{dataset}/retention",
                      headers=hdr(who or fx.editor_sub), json={"keep_versions": keep})


def report(client: TestClient, fx, dataset: str) -> dict:
    r = client.get(f"{base(fx)}/datasets/{dataset}/retention", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return r.json()


def sizes(client: TestClient, fx, dataset: str) -> dict[int, int]:
    rows = client.get(f"{base(fx)}/datasets/{dataset}/versions",
                      headers=hdr(fx.viewer_sub)).json()["items"]
    return {r["version_number"]: r["size_bytes"] for r in rows}


def test_by_default_every_version_is_kept(client, fx, versioned) -> None:
    got = report(client, fx, versioned)
    assert (got["keep_versions"], got["would_expire"], got["would_free_bytes"], got["expired"]) == (
        None, [], 0, 0)


def test_a_policy_says_what_it_would_remove_before_anything_is(client, fx, versioned) -> None:
    by_version = sizes(client, fx, versioned)
    r = put(client, fx, versioned, 1)
    assert r.status_code == 200, r.text
    assert r.json()["would_expire"] == [1, 2]
    assert r.json()["would_free_bytes"] == by_version[1] + by_version[2]
    assert report(client, fx, versioned)["would_expire"] == [1, 2]
    # Said, not done: every version is still there to read.
    assert all(size for size in sizes(client, fx, versioned).values())
    dataset = client.get(f"{base(fx)}/datasets/{versioned}", headers=hdr(fx.viewer_sub)).json()
    assert dataset["retention_versions"] == 1

    assert put(client, fx, versioned, 2).json()["would_expire"] == [1]
    assert put(client, fx, versioned, 3).json()["would_expire"] == []
    assert put(client, fx, versioned, None).json()["would_expire"] == []


def test_only_an_editor_sets_it_and_only_to_a_count(client, fx, versioned) -> None:
    assert put(client, fx, versioned, 1, who=fx.viewer_sub).status_code == 403
    assert put(client, fx, versioned, 0).status_code == 422
    assert report(client, fx, versioned)["keep_versions"] is None


def test_the_current_version_is_never_among_them(client, fx, versioned) -> None:
    """Decision 0005 §3. Made current the way a rollback's history can leave
    an older number current, by hand."""
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE datasets SET current_version = 1 WHERE id = %s", (versioned,))
    assert put(client, fx, versioned, 1).json()["would_expire"] == [2]


def _export(fx, dataset: str, mode: str, last_version) -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        cid = conn.execute(
            """INSERT INTO connections (workspace_id, project_id, scope, name, source_type,
                                        config, created_by)
               VALUES (%s, %s, 'project', %s, 'postgres', '{}'::jsonb, %s) RETURNING id""",
            (fx.workspace, fx.project, f"Out {uuid.uuid4().hex[:6]}", fx.owner)).fetchone()[0]
        conn.execute(
            """INSERT INTO exports (project_id, connection_id, dataset_id, name, kind, mode,
                                    last_version, created_by)
               VALUES (%s, %s, %s, %s, 'table', CAST(%s AS export_mode), %s, %s)""",
            (fx.project, cid, dataset, f"Export {uuid.uuid4().hex[:6]}", mode, last_version,
             fx.owner))


@pytest.mark.parametrize("mode, last_version, expected", [
    # A transactional export that last sent v2 reads v2 and everything after.
    ("incremental", 2, [1]),
    ("append_only", 1, []),
    ("efficient_mirror", 2, [1]),
    # One that has sent nothing sends the current view whole: nothing held.
    ("incremental", None, [1, 2]),
    # A mirror sends the dataset as it is, whatever came before.
    ("mirror", 1, [1, 2]),
])
def test_a_transactional_export_holds_what_it_will_read(
    client, fx, versioned, mode, last_version, expected
) -> None:
    _export(fx, versioned, mode, last_version)
    assert put(client, fx, versioned, 1).json()["would_expire"] == expected


def test_an_expired_version_is_counted_and_not_offered_again(client, fx, versioned) -> None:
    by_version = sizes(client, fx, versioned)
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE dataset_versions SET expired_at = now()"
                     " WHERE dataset_id = %s AND version_number = 1", (versioned,))
    got = put(client, fx, versioned, 1).json()
    assert got["would_expire"] == [2]
    assert got["expired"] == 1
    # Its bytes are no longer counted as held, nor as unmeasured.
    assert got["total_bytes"] == by_version[2] + by_version[3]
    assert got["unmeasured"] == 0
    rows = client.get(f"{base(fx)}/datasets/{versioned}/versions",
                      headers=hdr(fx.viewer_sub)).json()["items"]
    assert [r["version_number"] for r in rows if r["expired_at"]] == [1]


def test_a_change_of_policy_is_audited(client, fx, versioned) -> None:
    put(client, fx, versioned, 2)
    with psycopg.connect(ADMIN_DSN) as conn:
        meta = conn.execute(
            "SELECT metadata FROM audit_log WHERE action = 'dataset.retention'"
            " AND resource_id = %s ORDER BY created_at DESC LIMIT 1", (versioned,)).fetchone()[0]
    assert (meta["from"], meta["to"], meta["would_expire"]) == (None, 2, 1)


def test_a_version_a_rollback_reads_is_never_among_them(client, fx, versioned) -> None:
    """A rollback does not copy (§361): rolling back to v1 makes v4 read v1's
    own file, so expiring v1 would delete the current data."""
    r = client.post(f"{base(fx)}/datasets/{versioned}/rollback", headers=hdr(fx.editor_sub),
                    json={"version_number": 1})
    assert r.status_code == 200, r.text
    assert r.json()["current_version"] == 4
    # v1 shares v4's file; v2 and v3 are older than the newest one and their own.
    assert put(client, fx, versioned, 1).json()["would_expire"] == [2, 3]


def test_two_old_versions_sharing_a_file_go_together_or_not_at_all(client, fx, versioned) -> None:
    """v2 pointed at v1's file, as a rollback that is itself now old would."""
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            """UPDATE dataset_versions SET s3_manifest_key =
                   (SELECT s3_manifest_key FROM dataset_versions WHERE dataset_id = %s
                     AND version_number = 1)
                WHERE dataset_id = %s AND version_number = 2""", (versioned, versioned))
    assert put(client, fx, versioned, 1).json()["would_expire"] == [1, 2]
    assert put(client, fx, versioned, 2).json()["would_expire"] == []


def test_a_file_another_dataset_reads_as_its_current_data_is_kept(client, fx, versioned) -> None:
    """A dataset can name its current file without a version row saying so -
    ones made before versions were recorded do - so the location is asked
    as well as the history."""
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        key = conn.execute("SELECT s3_manifest_key FROM dataset_versions WHERE dataset_id = %s"
                           " AND version_number = 1", (versioned,)).fetchone()[0]
        conn.execute(
            """INSERT INTO datasets (project_id, workspace_id, name, slug, origin, s3_location,
                                     table_schema, row_count, current_version, created_by)
               VALUES (%s, %s, %s, %s, 'upload', %s, '[]'::jsonb, 0, 1, %s)""",
            (fx.project, fx.workspace, f"Reader {uuid.uuid4().hex[:6]}",
             f"reader-{uuid.uuid4().hex[:6]}", key, fx.owner))
    assert put(client, fx, versioned, 1).json()["would_expire"] == [2]


def test_what_a_policy_would_remove_is_shown_before_it_is_saved(client, fx, versioned) -> None:
    """Decision 0005's order: see it, then save it."""
    r = client.get(f"{base(fx)}/datasets/{versioned}/retention?keep_versions=1",
                   headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    assert r.json()["would_expire"] == [1, 2]
    # Asked, not set.
    assert r.json()["keep_versions"] is None
    assert report(client, fx, versioned)["would_expire"] == []
    assert client.get(f"{base(fx)}/datasets/{versioned}/retention?keep_versions=0",
                      headers=hdr(fx.viewer_sub)).status_code == 422

def test_an_expired_version_is_refused_in_words_wherever_it_would_be_read(
    client, fx, versioned
) -> None:
    """§965: its data is gone on purpose. Read, rolled back to or forked, it
    says so - not that a file went missing, which reads as an accident."""
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE dataset_versions SET expired_at = now()"
                     " WHERE dataset_id = %s AND version_number = 1", (versioned,))
    said = "removed by this dataset's retention policy"
    preview = client.get(f"{base(fx)}/datasets/{versioned}/preview?version=1",
                         headers=hdr(fx.viewer_sub))
    assert preview.status_code == 409 and said in preview.json()["detail"]
    back = client.post(f"{base(fx)}/datasets/{versioned}/rollback", headers=hdr(fx.editor_sub),
                       json={"version_number": 1})
    assert back.status_code == 409 and said in back.json()["detail"]
    fork = client.post(f"{base(fx)}/datasets/{versioned}/fork", headers=hdr(fx.editor_sub),
                       json={"name": f"From v1 {uuid.uuid4().hex[:6]}", "version_number": 1})
    assert fork.status_code == 409 and said in fork.json()["detail"]
    # A version that was kept still reads.
    assert client.get(f"{base(fx)}/datasets/{versioned}/preview?version=2",
                      headers=hdr(fx.viewer_sub)).status_code == 200
