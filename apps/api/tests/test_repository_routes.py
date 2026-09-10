"""The repository HTTP surface (roadmap phase 2, section 2).

`code_repos` has been in the schema since migration 0003 and empty in every
deployment - decision 0001 declined to build a git server and left it with
nothing to do. These tests are the first thing that puts a row in it through
the API, so they check the door as well as the room: role floors, a repository
appearing in the resource registry without this code knowing the registry
exists, and an empty repository reading as empty rather than as missing.
"""
from __future__ import annotations

import json
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


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client() -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def base(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/repositories"


def make_repo(client: TestClient, fx: Fixture, name: str | None = None) -> dict:
    r = client.post(
        base(fx),
        headers=hdr(fx.editor_sub),
        json={"name": name or f"Transforms {uuid.uuid4().hex[:8]}"},
    )
    assert r.status_code == 201, r.text
    return r.json()


def commit(client: TestClient, fx: Fixture, repo_id: str, files: dict, *,
           branch: str = "main", message: str = "") -> dict:
    r = client.post(
        f"{base(fx)}/{repo_id}/commits",
        headers=hdr(fx.editor_sub),
        json={"branch": branch, "files": files, "message": message},
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---- the repository ----------------------------------------------------------
def test_a_new_repository_is_empty_rather_than_missing(client: TestClient, fx: Fixture) -> None:
    """A repository that has just been created has no commits. That is a real
    state, and a tree read of it must return nothing rather than 404 - an
    editor cannot open a repository it is told does not exist."""
    repo = make_repo(client, fx)
    r = client.get(f"{base(fx)}/{repo['id']}/tree", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    assert r.json() == {"commit_id": None, "files": {}}


def test_creating_a_repository_registers_it_as_a_resource(
    client: TestClient, fx: Fixture
) -> None:
    """The registry trigger (db 0032) does this, and neither the repository
    route nor the registry knows about the other. A repository shows up in the
    project browser and resolves at /r/{id} for free."""
    repo = make_repo(client, fx, name=f"Registered {uuid.uuid4().hex[:6]}")
    r = client.get(f"/api/resources/{repo['resource_id']}", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "code_repo"
    assert r.json()["kind_id"] == repo["id"]
    assert r.json()["name"] == repo["name"]


def test_two_repositories_cannot_share_a_slug(client: TestClient, fx: Fixture) -> None:
    name = f"Duplicate {uuid.uuid4().hex[:6]}"
    make_repo(client, fx, name=name)
    r = client.post(base(fx), headers=hdr(fx.editor_sub), json={"name": name})
    assert r.status_code == 409, r.text
    assert isinstance(r.json()["detail"], str)


# ---- commits and trees -------------------------------------------------------
def test_a_commit_replaces_the_tree_rather_than_patching_it(
    client: TestClient, fx: Fixture
) -> None:
    """`files` is the whole snapshot. A file left out of a commit is deleted by
    it, which is what "the commit *is* the answer to what the repository looked
    like" means."""
    repo = make_repo(client, fx)
    commit(client, fx, repo["id"], {"a.sql": "SELECT 1", "b.sql": "SELECT 2"})
    commit(client, fx, repo["id"], {"a.sql": "SELECT 1"})

    tree = client.get(f"{base(fx)}/{repo['id']}/tree", headers=hdr(fx.viewer_sub)).json()
    assert tree["files"] == {"a.sql": "SELECT 1"}


def test_an_earlier_commit_still_reads_as_it_did(client: TestClient, fx: Fixture) -> None:
    repo = make_repo(client, fx)
    first = commit(client, fx, repo["id"], {"a.sql": "SELECT 1"})
    commit(client, fx, repo["id"], {"a.sql": "SELECT 999"})

    old = client.get(
        f"{base(fx)}/{repo['id']}/tree",
        headers=hdr(fx.viewer_sub),
        params={"commit_id": first["id"]},
    ).json()
    assert old["files"] == {"a.sql": "SELECT 1"}


def test_a_path_that_escapes_the_repository_is_refused(client: TestClient, fx: Fixture) -> None:
    repo = make_repo(client, fx)
    r = client.post(
        f"{base(fx)}/{repo['id']}/commits",
        headers=hdr(fx.editor_sub),
        json={"branch": "main", "files": {"../escape.sql": "x"}, "message": ""},
    )
    assert r.status_code == 422, r.text
    assert "escapes" in r.json()["detail"]


def test_history_walks_back_from_a_branch(client: TestClient, fx: Fixture) -> None:
    repo = make_repo(client, fx)
    first = commit(client, fx, repo["id"], {"a.sql": "1"}, message="one")
    second = commit(client, fx, repo["id"], {"a.sql": "2"}, message="two")

    rows = client.get(
        f"{base(fx)}/{repo['id']}/commits", headers=hdr(fx.viewer_sub), params={"branch": "main"}
    ).json()
    assert [r["id"] for r in rows] == [second["id"], first["id"]]
    assert rows[0]["parent_id"] == first["id"]


def test_a_diff_defaults_to_what_changed_in_this_commit(
    client: TestClient, fx: Fixture
) -> None:
    repo = make_repo(client, fx)
    commit(client, fx, repo["id"], {"keep.sql": "same", "gone.sql": "x"})
    second = commit(client, fx, repo["id"], {"keep.sql": "same", "new.sql": "y"})

    diff = client.get(
        f"{base(fx)}/{repo['id']}/diff",
        headers=hdr(fx.viewer_sub),
        params={"to_commit_id": second["id"]},
    ).json()
    assert diff == {"added": ["new.sql"], "deleted": ["gone.sql"], "modified": []}


def test_the_first_commit_diffs_against_nothing(client: TestClient, fx: Fixture) -> None:
    """It has no parent, so everything in it is added - rather than the read
    failing on a null base."""
    repo = make_repo(client, fx)
    first = commit(client, fx, repo["id"], {"a.sql": "1", "b.sql": "2"})
    diff = client.get(
        f"{base(fx)}/{repo['id']}/diff",
        headers=hdr(fx.viewer_sub),
        params={"to_commit_id": first["id"]},
    ).json()
    assert diff["added"] == ["a.sql", "b.sql"]


# ---- branches ----------------------------------------------------------------
def test_a_branch_starts_where_it_is_told_and_moves_forward(
    client: TestClient, fx: Fixture
) -> None:
    repo = make_repo(client, fx)
    first = commit(client, fx, repo["id"], {"a.sql": "1"})
    commit(client, fx, repo["id"], {"a.sql": "2"})

    r = client.post(
        f"{base(fx)}/{repo['id']}/branches",
        headers=hdr(fx.editor_sub),
        json={"name": "feature", "from_commit_id": first["id"]},
    )
    assert r.status_code == 201, r.text
    assert r.json()["head_commit_id"] == first["id"]

    # Committing on the branch moves it, and leaves main where it was.
    on_branch = commit(client, fx, repo["id"], {"a.sql": "3"}, branch="feature")
    branches = {
        b["name"]: b["head_commit_id"]
        for b in client.get(
            f"{base(fx)}/{repo['id']}/branches", headers=hdr(fx.viewer_sub)
        ).json()
    }
    assert branches["feature"] == on_branch["id"]
    assert branches["main"] != on_branch["id"]


def test_deleting_a_branch_leaves_its_commits_readable(
    client: TestClient, fx: Fixture
) -> None:
    repo = make_repo(client, fx)
    commit(client, fx, repo["id"], {"a.sql": "1"})
    made = commit(client, fx, repo["id"], {"a.sql": "2"}, branch="doomed")

    assert client.delete(
        f"{base(fx)}/{repo['id']}/branches/doomed", headers=hdr(fx.editor_sub)
    ).status_code == 204

    tree = client.get(
        f"{base(fx)}/{repo['id']}/tree",
        headers=hdr(fx.viewer_sub),
        params={"commit_id": made["id"]},
    ).json()
    assert tree["files"] == {"a.sql": "2"}


def test_a_commit_from_another_repository_is_not_readable_here(
    client: TestClient, fx: Fixture
) -> None:
    """An id in a query string is never trusted to belong to the resource in
    the path."""
    one, two = make_repo(client, fx), make_repo(client, fx)
    made = commit(client, fx, one["id"], {"a.sql": "1"})
    r = client.get(
        f"{base(fx)}/{two['id']}/tree",
        headers=hdr(fx.viewer_sub),
        params={"commit_id": made["id"]},
    )
    assert r.status_code == 404, r.text


# ---- comparing and merging (roadmap 2.4) -------------------------------------
def test_a_comparison_says_what_merging_would_do_without_doing_it(
    client: TestClient, fx: Fixture
) -> None:
    repo = make_repo(client, fx)
    first = commit(client, fx, repo["id"], {"a.sql": "1"})
    client.post(
        f"{base(fx)}/{repo['id']}/branches",
        headers=hdr(fx.editor_sub),
        json={"name": "feature", "from_commit_id": first["id"]},
    )
    landed = commit(client, fx, repo["id"], {"a.sql": "2", "b.sql": "9"}, branch="feature")

    # A viewer may look. Reading what a merge would do is reading.
    r = client.get(
        f"{base(fx)}/{repo['id']}/compare",
        headers=hdr(fx.viewer_sub),
        params={"base": "main", "head": "feature"},
    )
    assert r.status_code == 200, r.text
    seen = r.json()
    assert seen["state"] == "fast_forward"
    assert seen["ahead_by"] == 1 and seen["behind_by"] == 0
    assert [c["id"] for c in seen["commits"]] == [landed["id"]]
    assert seen["files"]["added"] == ["b.sql"] and seen["files"]["modified"] == ["a.sql"]

    # and main has not moved.
    branches = {
        b["name"]: b["head_commit_id"]
        for b in client.get(
            f"{base(fx)}/{repo['id']}/branches", headers=hdr(fx.viewer_sub)
        ).json()
    }
    assert branches["main"] == first["id"]


def test_merging_fast_forwards_the_branch(client: TestClient, fx: Fixture) -> None:
    repo = make_repo(client, fx)
    first = commit(client, fx, repo["id"], {"a.sql": "1"})
    client.post(
        f"{base(fx)}/{repo['id']}/branches",
        headers=hdr(fx.editor_sub),
        json={"name": "feature", "from_commit_id": first["id"]},
    )
    landed = commit(client, fx, repo["id"], {"a.sql": "2"}, branch="feature")

    r = client.post(
        f"{base(fx)}/{repo['id']}/merge",
        headers=hdr(fx.editor_sub),
        json={"base": "main", "head": "feature"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["merged"] is True

    branches = {
        b["name"]: b["head_commit_id"]
        for b in client.get(
            f"{base(fx)}/{repo['id']}/branches", headers=hdr(fx.viewer_sub)
        ).json()
    }
    assert branches["main"] == landed["id"]

    # Merging again is a no-op rather than a failure: the second click of a
    # double-click lands here.
    again = client.post(
        f"{base(fx)}/{repo['id']}/merge",
        headers=hdr(fx.editor_sub),
        json={"base": "main", "head": "feature"},
    )
    assert again.status_code == 200, again.text
    assert again.json()["merged"] is False and again.json()["state"] == "identical"


def test_a_diverged_merge_is_refused_and_names_the_files(
    client: TestClient, fx: Fixture
) -> None:
    repo = make_repo(client, fx)
    first = commit(client, fx, repo["id"], {"a.sql": "1"})
    client.post(
        f"{base(fx)}/{repo['id']}/branches",
        headers=hdr(fx.editor_sub),
        json={"name": "feature", "from_commit_id": first["id"]},
    )
    on_main = commit(client, fx, repo["id"], {"a.sql": "1", "main.sql": "m"})
    commit(client, fx, repo["id"], {"a.sql": "1", "feature.sql": "f"}, branch="feature")

    seen = client.get(
        f"{base(fx)}/{repo['id']}/compare",
        headers=hdr(fx.viewer_sub),
        params={"base": "main", "head": "feature"},
    ).json()
    assert seen["state"] == "diverged"
    assert seen["ahead_by"] == 1 and seen["behind_by"] == 1

    r = client.post(
        f"{base(fx)}/{repo['id']}/merge",
        headers=hdr(fx.editor_sub),
        json={"base": "main", "head": "feature"},
    )
    assert r.status_code == 409, r.text
    assert "feature.sql" in r.json()["detail"] and "main.sql" in r.json()["detail"]

    branches = {
        b["name"]: b["head_commit_id"]
        for b in client.get(
            f"{base(fx)}/{repo['id']}/branches", headers=hdr(fx.viewer_sub)
        ).json()
    }
    assert branches["main"] == on_main["id"]


def test_a_branch_cannot_be_merged_into_itself(client: TestClient, fx: Fixture) -> None:
    repo = make_repo(client, fx)
    commit(client, fx, repo["id"], {"a.sql": "1"})
    r = client.post(
        f"{base(fx)}/{repo['id']}/merge",
        headers=hdr(fx.editor_sub),
        json={"base": "main", "head": "main"},
    )
    assert r.status_code == 422, r.text


def test_merging_a_branch_that_does_not_exist_says_which(
    client: TestClient, fx: Fixture
) -> None:
    repo = make_repo(client, fx)
    commit(client, fx, repo["id"], {"a.sql": "1"})
    r = client.post(
        f"{base(fx)}/{repo['id']}/merge",
        headers=hdr(fx.editor_sub),
        json={"base": "main", "head": "ghost"},
    )
    assert r.status_code == 404, r.text
    assert "ghost" in r.json()["detail"]


def test_the_default_branch_cannot_be_deleted(client: TestClient, fx: Fixture) -> None:
    """Deleting it would make the repository open as empty, which is what a
    repository that has lost everything also looks like."""
    repo = make_repo(client, fx)
    made = commit(client, fx, repo["id"], {"a.sql": "1"})
    r = client.delete(
        f"{base(fx)}/{repo['id']}/branches/main", headers=hdr(fx.editor_sub)
    )
    assert r.status_code == 409, r.text

    tree = client.get(f"{base(fx)}/{repo['id']}/tree", headers=hdr(fx.viewer_sub)).json()
    assert tree["commit_id"] == made["id"]


# ---- permissions -------------------------------------------------------------
def test_a_viewer_reads_and_cannot_write(client: TestClient, fx: Fixture) -> None:
    repo = make_repo(client, fx)
    assert client.get(f"{base(fx)}/{repo['id']}", headers=hdr(fx.viewer_sub)).status_code == 200

    for method, path, body in [
        ("post", base(fx), {"name": "Nope"}),
        ("post", f"{base(fx)}/{repo['id']}/commits",
         {"branch": "main", "files": {"a.sql": "1"}, "message": ""}),
        ("post", f"{base(fx)}/{repo['id']}/branches", {"name": "nope"}),
        ("post", f"{base(fx)}/{repo['id']}/merge", {"base": "main", "head": "nope"}),
    ]:
        r = getattr(client, method)(path, headers=hdr(fx.viewer_sub), json=body)
        assert r.status_code == 403, (path, r.text)


def test_an_outsider_sees_nothing(client: TestClient, fx: Fixture) -> None:
    repo = make_repo(client, fx)
    for sub in (fx.outsider_sub, fx.foreign_sub):
        r = client.get(f"{base(fx)}/{repo['id']}", headers=hdr(sub))
        assert r.status_code in (403, 404), (sub, r.text)


# ---- the sidebar badge (§291) ------------------------------------------------
def test_the_code_badge_counts_repositories_not_transforms(
    client: TestClient, fx: Fixture
) -> None:
    """**A count is a promise about what is behind the link.**

    The Code badge counted `models` - the same rows the Models badge counts -
    because decision 0001 had made the pillar a view over `model_versions`, and
    the comment in `projects.py` said `code_repos` "has never had a row written
    to it". That stopped being true at §94, and §291 made the pillar the list of
    repositories, so a project with one repository and forty transforms would
    have shown 40 beside a list of one.

    Written as a *difference*: a transform is created and the badge does not
    move, then a repository is and it does. Asserting an absolute number would
    pass on a module-scoped fixture whose other tests happen to leave the two
    counts equal.
    """
    detail = f"/api/workspaces/{fx.workspace}/projects/{fx.project}"

    def code_count() -> int:
        r = client.get(detail, headers=hdr(fx.viewer_sub))
        assert r.status_code == 200, r.text
        return int(r.json()["resource_counts"]["code"])

    before = code_count()

    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/models",
        headers=hdr(fx.editor_sub),
        json={"name": f"badge_{uuid.uuid4().hex[:8]}", "language": "sql",
              "code": "SELECT 1", "inputs": []},
    )
    assert r.status_code == 201, r.text
    assert code_count() == before, "a transform is not a repository"

    make_repo(client, fx)
    assert code_count() == before + 1


# ---- unit test runs (§294; db 0071) -------------------------------------------
def test_asking_for_tests_queues_a_job_rather_than_running_them(
    client: TestClient, fx: Fixture
) -> None:
    """**202, not 200, and the status code is the design.**

    Running a repository's unit tests is running customer Python, which
    decision 0004 confines to a process holding no platform credentials. §286's
    Problems panel could answer inline because it parses and reads names; this
    cannot, and `preview_transform` one route over already refuses Python for
    exactly this reason. So the API writes a job and the worker executes it.
    """
    repo = make_repo(client, fx)
    r = client.post(
        f"{base(fx)}/{repo['id']}/tests",
        headers=hdr(fx.editor_sub),
        json={"overrides": {"tests/test_it.py": "def test_it():\n    assert 1\n"}},
    )
    assert r.status_code == 202, r.text
    run = r.json()
    assert run["status"] == "queued"
    assert run["outcomes"] is None, "nothing has run yet"
    assert run["error"] is None
    assert run["branch"] == "main"

    # And it is readable back by id, which is what the panel watches.
    got = client.get(
        f"{base(fx)}/{repo['id']}/tests/{run['id']}", headers=hdr(fx.viewer_sub)
    )
    assert got.status_code == 200, got.text
    assert got.json()["status"] == "queued"


def test_the_working_set_is_the_commit_plus_the_authors_edits(
    client: TestClient, fx: Fixture
) -> None:
    """The same delta the Problems panel sends (§286): the server has the
    commit, so only the changes travel. A run over the committed tree alone
    would answer a question nobody asked."""
    repo = make_repo(client, fx)
    commit(client, fx, repo["id"], {
        "src/daily.py": "def build(rows):\n    return rows\n",
        "tests/test_daily.py": "from src.daily import build\n\ndef test_it():\n    assert build([1]) == [1]\n",
    })
    r = client.post(
        f"{base(fx)}/{repo['id']}/tests",
        headers=hdr(fx.editor_sub),
        # One file edited, one deleted, and the third arrives from the commit.
        json={"overrides": {
            "tests/test_daily.py": "def test_new():\n    assert 1\n",
            "src/daily.py": None,
        }},
    )
    assert r.status_code == 202, r.text

    with psycopg.connect(os.environ["TEST_ADMIN_DSN"], autocommit=True) as conn:
        files = conn.execute(
            "SELECT files FROM code_test_runs WHERE id = %s", (r.json()["id"],)
        ).fetchone()[0]
    assert set(files) == {"tests/test_daily.py"}, files
    assert files["tests/test_daily.py"] == "def test_new():\n    assert 1\n"


def test_a_run_with_no_files_is_refused_rather_than_queued(
    client: TestClient, fx: Fixture
) -> None:
    """422: a request naming nothing is malformed. An empty run would sit in
    the queue, come back with no outcomes, and read as "your repository has no
    tests" - an answer about their code for a request that had none."""
    repo = make_repo(client, fx)
    r = client.post(
        f"{base(fx)}/{repo['id']}/tests", headers=hdr(fx.editor_sub), json={}
    )
    assert r.status_code == 422, r.text
    assert "no files" in r.text


def test_a_repositorys_queue_does_not_grow_without_limit(
    client: TestClient, fx: Fixture
) -> None:
    """A panel with a press-and-press-again button is the ordinary way this
    table fills up, and every extra queued run over the same working set
    produces the same answer more slowly."""
    repo = make_repo(client, fx)
    body = {"overrides": {"tests/test_it.py": "def test_it():\n    assert 1\n"}}
    for _ in range(3):
        assert client.post(
            f"{base(fx)}/{repo['id']}/tests", headers=hdr(fx.editor_sub), json=body
        ).status_code == 202
    r = client.post(
        f"{base(fx)}/{repo['id']}/tests", headers=hdr(fx.editor_sub), json=body
    )
    assert r.status_code == 409, r.text
    assert "already waiting" in r.text


def test_a_run_from_another_repository_is_not_found_here(
    client: TestClient, fx: Fixture
) -> None:
    """Scoped to the repository as well as the id, so a run id from elsewhere
    reads as absent rather than as somebody else's answer - the three-legged
    check `code._assert_commit_belongs` makes, for the same reason."""
    mine = make_repo(client, fx)
    theirs = make_repo(client, fx)
    r = client.post(
        f"{base(fx)}/{theirs['id']}/tests",
        headers=hdr(fx.editor_sub),
        json={"overrides": {"tests/test_it.py": "def test_it():\n    assert 1\n"}},
    )
    assert r.status_code == 202
    run_id = r.json()["id"]

    assert client.get(
        f"{base(fx)}/{mine['id']}/tests/{run_id}", headers=hdr(fx.viewer_sub)
    ).status_code == 404
    assert client.get(
        f"{base(fx)}/{theirs['id']}/tests/{run_id}", headers=hdr(fx.viewer_sub)
    ).status_code == 200


def test_running_tests_is_editor_and_reading_them_is_viewer(
    client: TestClient, fx: Fixture
) -> None:
    """**The line `preview_transform` draws.** Asking for tests to run executes
    code the caller supplied, so the floor matches who may write the file.
    Reading what they said touches nothing."""
    repo = make_repo(client, fx)
    body = {"overrides": {"tests/test_it.py": "def test_it():\n    assert 1\n"}}
    assert client.post(
        f"{base(fx)}/{repo['id']}/tests", headers=hdr(fx.viewer_sub), json=body
    ).status_code == 403

    made = client.post(
        f"{base(fx)}/{repo['id']}/tests", headers=hdr(fx.editor_sub), json=body
    )
    assert made.status_code == 202
    assert client.get(
        f"{base(fx)}/{repo['id']}/tests/{made.json()['id']}", headers=hdr(fx.viewer_sub)
    ).status_code == 200
    assert client.get(
        f"{base(fx)}/{repo['id']}/tests", headers=hdr(fx.viewer_sub)
    ).status_code == 200


def test_recent_runs_are_newest_first(client: TestClient, fx: Fixture) -> None:
    """What the panel opens on is "what happened last time", which is the
    question somebody has before they have any other."""
    repo = make_repo(client, fx)
    body = {"overrides": {"tests/test_it.py": "def test_it():\n    assert 1\n"}}
    ids = [
        client.post(
            f"{base(fx)}/{repo['id']}/tests", headers=hdr(fx.editor_sub), json=body
        ).json()["id"]
        for _ in range(2)
    ]
    listed = client.get(
        f"{base(fx)}/{repo['id']}/tests", headers=hdr(fx.viewer_sub)
    ).json()
    assert [r["id"] for r in listed][:2] == list(reversed(ids))

def test_the_listing_can_be_asked_about_one_branch(client: TestClient, fx: Fixture) -> None:
    """**A survivor found this untested.** The Tests panel shows the branch it
    is on, and a listing that ignored the filter would put a sandbox's failures
    under `main` - a wrong answer that looks exactly like a right one."""
    repo = make_repo(client, fx)
    client.post(
        f"{base(fx)}/{repo['id']}/branches",
        headers=hdr(fx.editor_sub), json={"name": "sandbox", "from_branch": "main"},
    )
    body = {"overrides": {"tests/test_it.py": "def test_it():\n    assert 1\n"}}
    on_main = client.post(
        f"{base(fx)}/{repo['id']}/tests", headers=hdr(fx.editor_sub), json=body
    ).json()["id"]
    on_sandbox = client.post(
        f"{base(fx)}/{repo['id']}/tests", headers=hdr(fx.editor_sub),
        json={**body, "branch": "sandbox"},
    ).json()["id"]

    listed = client.get(
        f"{base(fx)}/{repo['id']}/tests?branch=sandbox", headers=hdr(fx.viewer_sub)
    ).json()
    assert [r["id"] for r in listed] == [on_sandbox]

    # And unfiltered still means every branch, rather than the last one asked
    # about - the two are different questions and both are asked.
    everything = [
        r["id"] for r in
        client.get(f"{base(fx)}/{repo['id']}/tests", headers=hdr(fx.viewer_sub)).json()
    ]
    assert on_main in everything and on_sandbox in everything


# ---- tags (§299; p.17) --------------------------------------------------------
SEMVER_SETTINGS = json.dumps({
    "tagNameValidation": {
        # p.17's own example, verbatim.
        "regex": r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-rc\d+)?$",
        "errorMessage": "Tag name must have the format x.x.x or x.x.x-rcx.",
    }
})


def test_a_tag_can_be_made_from_a_branch_or_from_any_commit(
    client: TestClient, fx: Fixture
) -> None:
    """p.17: "A tag can be created from the current version of a branch, or from
    any arbitrary commit." Both, and the second is what makes a tag useful after
    the fact - you rarely know at the time which version mattered."""
    repo = make_repo(client, fx)
    # A message on the first, because the list is asserted to carry it - the
    # helper's default is empty, which is what a tags list would then show.
    first = commit(client, fx, repo["id"], {"src/a.sql": "SELECT 1\n"},
                   message="the first cut")
    second = commit(client, fx, repo["id"], {"src/a.sql": "SELECT 2\n"})

    from_branch = client.post(
        f"{base(fx)}/{repo['id']}/tags", headers=hdr(fx.editor_sub),
        json={"name": "1.1.0"},
    )
    assert from_branch.status_code == 201, from_branch.text
    assert from_branch.json()["commit_id"] == second["id"]

    from_commit = client.post(
        f"{base(fx)}/{repo['id']}/tags", headers=hdr(fx.editor_sub),
        json={"name": "1.0.0", "commit_id": first["id"], "message": "the first cut"},
    )
    assert from_commit.status_code == 201, from_commit.text
    assert from_commit.json()["commit_id"] == first["id"]

    listed = client.get(
        f"{base(fx)}/{repo['id']}/tags", headers=hdr(fx.viewer_sub)
    ).json()
    # Newest first: a tags list is read to answer "what did we cut recently",
    # and a version number sorts by neither of the orders people expect.
    assert [t["name"] for t in listed] == ["1.0.0", "1.1.0"]
    # The commit's own message travels, so the list says what was cut and not
    # only when.
    assert listed[0]["commit_message"] == "the first cut"


def test_a_tag_never_moves(client: TestClient, fx: Fixture) -> None:
    """**"Like immutable branches", and immutable is the whole difference.**

    A branch is a name whose commit moves; a tag is a name whose commit does
    not. Re-tagging is refused with what the name already points at, because
    the reader's next question is always "the same commit, or a different one?"
    """
    repo = make_repo(client, fx)
    first = commit(client, fx, repo["id"], {"src/a.sql": "SELECT 1\n"})
    assert client.post(
        f"{base(fx)}/{repo['id']}/tags", headers=hdr(fx.editor_sub),
        json={"name": "2.0.0"},
    ).status_code == 201

    commit(client, fx, repo["id"], {"src/a.sql": "SELECT 2\n"})
    again = client.post(
        f"{base(fx)}/{repo['id']}/tags", headers=hdr(fx.editor_sub),
        json={"name": "2.0.0"},
    )
    assert again.status_code == 409, again.text
    assert "never moves" in again.text
    assert first["id"][:8] in again.text, "the refusal should say what it points at"


def test_the_database_refuses_to_move_a_tag_even_from_outside_the_service(
    client: TestClient, fx: Fixture
) -> None:
    """**The rule is a trigger, not a service check, and this is why.**

    A refusal that lives only in `code_tags.create` is one the next writer of an
    UPDATE does not meet - a migration, a repair script, a feature nobody has
    thought of. A tag whose commit moved is a lie discovered by whoever resolves
    it, possibly a year later. So the check is where every writer has to pass.
    """
    repo = make_repo(client, fx)
    first = commit(client, fx, repo["id"], {"src/a.sql": "SELECT 1\n"})
    second = commit(client, fx, repo["id"], {"src/a.sql": "SELECT 2\n"})
    tag = client.post(
        f"{base(fx)}/{repo['id']}/tags", headers=hdr(fx.editor_sub),
        json={"name": "3.0.0", "commit_id": first["id"]},
    ).json()

    with psycopg.connect(os.environ["TEST_ADMIN_DSN"], autocommit=True) as conn:
        with pytest.raises(psycopg.errors.RaiseException, match="a tag is immutable"):
            conn.execute(
                "UPDATE code_tags SET commit_id = %s WHERE id = %s",
                (second["id"], tag["id"]),
            )
        with pytest.raises(psycopg.errors.RaiseException, match="cannot be renamed"):
            conn.execute(
                "UPDATE code_tags SET name = %s WHERE id = %s", ("3.0.1", tag["id"])
            )
        # The message may be corrected: a sentence about *why* is not what
        # anything resolves.
        conn.execute(
            "UPDATE code_tags SET message = %s WHERE id = %s", ("clearer", tag["id"])
        )


def test_the_repositorys_own_naming_convention_is_enforced(
    client: TestClient, fx: Fixture
) -> None:
    """p.17's `tagNameValidation` in `repoSettings.json`, which is **Foundry's
    own mechanism and the first thing here to read that file**.

    A settings table would have been easier and worse: the rule is about a
    repository's contents, so it travels with them - a branch that adds it, a
    commit that relaxes it, and a history that says who changed the convention
    and when.
    """
    repo = make_repo(client, fx)
    commit(client, fx, repo["id"], {
        "repoSettings.json": SEMVER_SETTINGS,
        "src/a.sql": "SELECT 1\n",
    })

    refused = client.post(
        f"{base(fx)}/{repo['id']}/tags", headers=hdr(fx.editor_sub),
        json={"name": "release-candidate"},
    )
    assert refused.status_code == 422, refused.text
    # **The repository's own sentence**, not ours. p.17 shows the field for
    # exactly this, and replacing it with "invalid tag name" would throw away
    # the only part of the refusal that helps.
    assert "Tag name must have the format x.x.x" in refused.text

    accepted = client.post(
        f"{base(fx)}/{repo['id']}/tags", headers=hdr(fx.editor_sub),
        json={"name": "1.4.0-rc2"},
    )
    assert accepted.status_code == 201, accepted.text


def test_a_settings_file_that_will_not_parse_does_not_block_every_tag(
    client: TestClient, fx: Fixture
) -> None:
    """**A convention, not a permission.** A syntax error in the settings file
    would otherwise stop every tag in the repository until somebody fixed it -
    and the person blocked is rarely the person who broke it. The convention
    stops being enforced, which the next tag makes visible."""
    repo = make_repo(client, fx)
    commit(client, fx, repo["id"], {
        "repoSettings.json": "{ this is not json",
        "src/a.sql": "SELECT 1\n",
    })
    made = client.post(
        f"{base(fx)}/{repo['id']}/tags", headers=hdr(fx.editor_sub),
        json={"name": "anything-at-all"},
    )
    assert made.status_code == 201, made.text


def test_an_empty_repository_has_no_version_to_tag(
    client: TestClient, fx: Fixture
) -> None:
    """A tag pointing at nothing is the state db 0072 refuses outright, so the
    refusal happens here where it can say why."""
    repo = make_repo(client, fx)
    made = client.post(
        f"{base(fx)}/{repo['id']}/tags", headers=hdr(fx.editor_sub),
        json={"name": "0.1.0"},
    )
    assert made.status_code == 409, made.text
    assert "nothing committed" in made.text


def test_a_tag_can_be_deleted_and_takes_nothing_with_it(
    client: TestClient, fx: Fixture
) -> None:
    """A mistyped name has to be removable, and deleting a tag is safe in a way
    deleting a branch is not: `ON DELETE RESTRICT` on the commit means the code
    is exactly as safe afterwards."""
    repo = make_repo(client, fx)
    made = commit(client, fx, repo["id"], {"src/a.sql": "SELECT 1\n"})
    tag = client.post(
        f"{base(fx)}/{repo['id']}/tags", headers=hdr(fx.editor_sub),
        json={"name": "0.9.0"},
    ).json()

    assert client.delete(
        f"{base(fx)}/{repo['id']}/tags/{tag['id']}", headers=hdr(fx.editor_sub)
    ).status_code == 204
    assert client.get(
        f"{base(fx)}/{repo['id']}/tags", headers=hdr(fx.viewer_sub)
    ).json() == []
    # The commit it pointed at is still there and still readable.
    tree = client.get(
        f"{base(fx)}/{repo['id']}/tree?commit_id={made['id']}", headers=hdr(fx.viewer_sub)
    )
    assert tree.status_code == 200, tree.text


def test_tagging_is_editor_and_reading_is_viewer(client: TestClient, fx: Fixture) -> None:
    """A tag marks a version; it changes no code and moves no branch, and the
    trigger means it cannot later be pointed elsewhere. Whoever may commit may
    say which commit mattered."""
    repo = make_repo(client, fx)
    commit(client, fx, repo["id"], {"src/a.sql": "SELECT 1\n"})
    assert client.post(
        f"{base(fx)}/{repo['id']}/tags", headers=hdr(fx.viewer_sub),
        json={"name": "5.0.0"},
    ).status_code == 403
    assert client.get(
        f"{base(fx)}/{repo['id']}/tags", headers=hdr(fx.viewer_sub)
    ).status_code == 200


def test_a_tag_from_another_repository_is_not_deletable_here(
    client: TestClient, fx: Fixture
) -> None:
    """Scoped to the repository as well as the id, the same three-legged check
    every other route here makes."""
    mine = make_repo(client, fx)
    theirs = make_repo(client, fx)
    commit(client, fx, theirs["id"], {"src/a.sql": "SELECT 1\n"})
    tag = client.post(
        f"{base(fx)}/{theirs['id']}/tags", headers=hdr(fx.editor_sub),
        json={"name": "6.0.0"},
    ).json()

    assert client.delete(
        f"{base(fx)}/{mine['id']}/tags/{tag['id']}", headers=hdr(fx.editor_sub)
    ).status_code == 404
    assert client.delete(
        f"{base(fx)}/{theirs['id']}/tags/{tag['id']}", headers=hdr(fx.editor_sub)
    ).status_code == 204


def test_an_unanchored_convention_still_has_to_match_the_whole_name(
    client: TestClient, fx: Fixture
) -> None:
    """**`fullmatch`, not `search`**, and a survivor found this untested.

    p.17's example regex is anchored with `^` and `$` and most people's will be,
    so the two agree on it — which is why every other test here passed either
    way. One that is *not* anchored would, under `search`, accept
    `1.4-DO-NOT-USE` because `1.4` appears inside it: the opposite of what
    somebody writing a convention meant, and silently, on the one name they most
    wanted to keep out.
    """
    repo = make_repo(client, fx)
    commit(client, fx, repo["id"], {
        "repoSettings.json": json.dumps({
            "tagNameValidation": {"regex": r"\d+\.\d+", "errorMessage": "x.y please"}
        }),
        "src/a.sql": "SELECT 1\n",
    })

    sneaky = client.post(
        f"{base(fx)}/{repo['id']}/tags", headers=hdr(fx.editor_sub),
        json={"name": "1.4-DO-NOT-USE"},
    )
    assert sneaky.status_code == 422, sneaky.text
    assert client.post(
        f"{base(fx)}/{repo['id']}/tags", headers=hdr(fx.editor_sub),
        json={"name": "1.4"},
    ).status_code == 201


def test_a_regex_that_will_not_compile_does_not_block_every_tag(
    client: TestClient, fx: Fixture
) -> None:
    """The same reason an unparseable settings file does not: it is a
    convention, not a permission. Failing closed would stop every tag in the
    repository while the person who can fix the regex is elsewhere.

    Untested until a survivor said so — the JSON case was covered and this one,
    one line below it in the same module, was not.
    """
    repo = make_repo(client, fx)
    commit(client, fx, repo["id"], {
        "repoSettings.json": json.dumps({"tagNameValidation": {"regex": "([unclosed"}}),
        "src/a.sql": "SELECT 1\n",
    })
    made = client.post(
        f"{base(fx)}/{repo['id']}/tags", headers=hdr(fx.editor_sub),
        json={"name": "anything-at-all"},
    )
    assert made.status_code == 201, made.text


def test_a_regex_long_enough_to_be_a_weapon_is_not_run(
    client: TestClient, fx: Fixture
) -> None:
    """**A regex is code**, and one assembled to be pathological is the ordinary
    way a validator becomes a denial of service — here, code from a customer's
    file, run on every tag anybody makes.

    Length is a blunt guard and the test has to be blunt with it: the regex
    below is valid and *would* refuse this name, so the tag being accepted is
    the guard having fired. Asserting a refusal would have passed whether or not
    the guard existed.
    """
    repo = make_repo(client, fx)
    long_enough = "^(?:1\\.0\\.0)$" + ("|(?:x)" * 60)
    assert len(long_enough) > 200
    commit(client, fx, repo["id"], {
        "repoSettings.json": json.dumps({"tagNameValidation": {"regex": long_enough}}),
        "src/a.sql": "SELECT 1\n",
    })
    made = client.post(
        f"{base(fx)}/{repo['id']}/tags", headers=hdr(fx.editor_sub),
        json={"name": "2.2.2"},
    )
    assert made.status_code == 201, made.text


# ---- p.16's Checks and Pull request columns (§300) -----------------------------
#: A file that actually declares, because a proposal cannot be made over a
#: commit with nothing to publish - the publish path refuses it, which is right
#: and which a fixture of `SELECT 1` walks straight into.
def declaring(name: str) -> str:
    return f"-- output: {name}\nSELECT 1 AS id\n"


def summary(client: TestClient, fx: Fixture, repo_id: str) -> dict:
    r = client.get(f"{base(fx)}/{repo_id}/branch-summary", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return {row["name"]: row for row in r.json()}


def test_a_branch_with_nothing_run_against_it_is_not_reported_as_passing(
    client: TestClient, fx: Fixture
) -> None:
    """**`none`, never `passed`.** "Nothing failed" and "everything passed" are
    the same number, and a green tick over a branch nothing has run against is
    the same lie §295 refuses about a test suite that ran nothing — arriving on
    the column somebody glances at before merging."""
    repo = make_repo(client, fx)
    commit(client, fx, repo["id"], {"src/a.sql": "SELECT 1\n"})

    rows = summary(client, fx, repo["id"])
    assert rows["main"]["checks"] == "none"
    assert rows["main"]["proposal_id"] is None


def test_the_pull_request_column_finds_the_proposal_over_the_branchs_head(
    client: TestClient, fx: Fixture
) -> None:
    """p.16: "tells you about any existing Pull requests in a branch".

    **Ours names an immutable commit rather than a branch** (db 0039), so "this
    branch's pull request" means a proposal over the commit the branch is
    currently on — exactly what "Propose changes" would create. §285 recorded
    the same divergence about checks; this is it on the other column.
    """
    repo = make_repo(client, fx)
    made = commit(client, fx, repo["id"],
                  {"src/a.sql": declaring(f"daily_{uuid.uuid4().hex[:8]}")})
    proposal = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/code/proposals",
        headers=hdr(fx.editor_sub),
        json={"summary": "Publish it", "description": "",
              "source_repo_id": repo["id"], "source_commit_id": made["id"]},
    )
    assert proposal.status_code == 201, proposal.text

    rows = summary(client, fx, repo["id"])
    assert rows["main"]["proposal_id"] == proposal.json()["id"]
    assert rows["main"]["proposal_state"] == "open"
    assert rows["main"]["proposal_summary"] == "Publish it"


def test_a_branch_that_has_moved_on_no_longer_carries_that_proposal(
    client: TestClient, fx: Fixture
) -> None:
    """**The divergence, made visible rather than described.**

    A proposal here is a review of a snapshot. Commit again and the branch is a
    different snapshot, so the column stops claiming a pull request that no
    longer covers what is on the branch — which is more honest than Foundry's
    branch-tracking PR would be about our model, and would be wrong about
    Foundry's.
    """
    repo = make_repo(client, fx)
    output = f"daily_{uuid.uuid4().hex[:8]}"
    first = commit(client, fx, repo["id"], {"src/a.sql": declaring(output)})
    client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/code/proposals",
        headers=hdr(fx.editor_sub),
        json={"summary": "Publish the first", "description": "",
              "source_repo_id": repo["id"], "source_commit_id": first["id"]},
    )
    assert summary(client, fx, repo["id"])["main"]["proposal_id"] is not None

    commit(client, fx, repo["id"],
           {"src/a.sql": declaring(output) + "-- and again\n"})
    assert summary(client, fx, repo["id"])["main"]["proposal_id"] is None


def test_every_branch_comes_back_in_one_request(client: TestClient, fx: Fixture) -> None:
    """A repository with twenty branches would otherwise open the tab with
    twenty round trips, which is how a column becomes something people wait for
    rather than glance at."""
    repo = make_repo(client, fx)
    commit(client, fx, repo["id"], {"src/a.sql": "SELECT 1\n"})
    for name in ("alpha", "beta"):
        client.post(f"{base(fx)}/{repo['id']}/branches", headers=hdr(fx.editor_sub),
                    json={"name": name, "from_branch": "main"})

    rows = summary(client, fx, repo["id"])
    assert set(rows) == {"main", "alpha", "beta"}
    # Ordered by name, so the list does not reshuffle between visits.
    listed = client.get(
        f"{base(fx)}/{repo['id']}/branch-summary", headers=hdr(fx.viewer_sub)
    ).json()
    assert [r["name"] for r in listed] == ["alpha", "beta", "main"]


def test_a_check_that_could_not_run_is_not_a_pass_in_the_column(
    client: TestClient, fx: Fixture
) -> None:
    """**A survivor found this untested.** `fail` and `error` are both worst: a
    check that could not run says as little about the branch as one that ran and
    failed, and a column showing the second as a pass is the quietest way to
    merge broken code.

    Written through the database because the API has no way to make a check
    error on demand — and inventing one would be building a hook for a test.
    """
    repo = make_repo(client, fx)
    made = commit(client, fx, repo["id"],
                  {"src/a.sql": declaring(f"daily_{uuid.uuid4().hex[:8]}")})
    proposal = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/code/proposals",
        headers=hdr(fx.editor_sub),
        json={"summary": "Publish it", "description": "",
              "source_repo_id": repo["id"], "source_commit_id": made["id"]},
    ).json()

    with psycopg.connect(os.environ["TEST_ADMIN_DSN"], autocommit=True) as conn:
        conn.execute(
            """INSERT INTO code_proposal_checks
                   (proposal_id, name, status, summary, anchored_at)
               VALUES (%s, 'schema', 'error', 'the checker fell over', now())""",
            (proposal["id"],),
        )

    assert summary(client, fx, repo["id"])["main"]["checks"] == "failed"


def test_a_withdrawn_proposal_is_not_the_branchs_pull_request(
    client: TestClient, fx: Fixture
) -> None:
    """**A survivor found this too.** p.16's column is about *existing* pull
    requests, and a withdrawn one is a decision somebody already made. Showing
    it would leave a branch looking as though it were under review when nobody
    is reviewing it — and, worse, would hide the Propose changes button, which
    p.16 says means a pull request exists.
    """
    repo = make_repo(client, fx)
    made = commit(client, fx, repo["id"],
                  {"src/a.sql": declaring(f"daily_{uuid.uuid4().hex[:8]}")})
    proposal = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/code/proposals",
        headers=hdr(fx.editor_sub),
        json={"summary": "Publish it", "description": "",
              "source_repo_id": repo["id"], "source_commit_id": made["id"]},
    ).json()
    assert summary(client, fx, repo["id"])["main"]["proposal_id"] == proposal["id"]

    assert client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}"
        f"/code/proposals/{proposal['id']}/withdraw",
        headers=hdr(fx.editor_sub),
    ).status_code == 200

    row = summary(client, fx, repo["id"])["main"]
    assert row["proposal_id"] is None, "a withdrawn proposal is not under review"
