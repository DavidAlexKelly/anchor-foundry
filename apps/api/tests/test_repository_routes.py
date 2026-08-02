"""The repository HTTP surface (roadmap phase 2, section 2).

`code_repos` has been in the schema since migration 0003 and empty in every
deployment - decision 0001 declined to build a git server and left it with
nothing to do. These tests are the first thing that puts a row in it through
the API, so they check the door as well as the room: role floors, a repository
appearing in the resource registry without this code knowing the registry
exists, and an empty repository reading as empty rather than as missing.
"""
from __future__ import annotations

import os
import sys
import uuid

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


# ---- permissions -------------------------------------------------------------
def test_a_viewer_reads_and_cannot_write(client: TestClient, fx: Fixture) -> None:
    repo = make_repo(client, fx)
    assert client.get(f"{base(fx)}/{repo['id']}", headers=hdr(fx.viewer_sub)).status_code == 200

    for method, path, body in [
        ("post", base(fx), {"name": "Nope"}),
        ("post", f"{base(fx)}/{repo['id']}/commits",
         {"branch": "main", "files": {"a.sql": "1"}, "message": ""}),
        ("post", f"{base(fx)}/{repo['id']}/branches", {"name": "nope"}),
    ]:
        r = getattr(client, method)(path, headers=hdr(fx.viewer_sub), json=body)
        assert r.status_code == 403, (path, r.text)


def test_an_outsider_sees_nothing(client: TestClient, fx: Fixture) -> None:
    repo = make_repo(client, fx)
    for sub in (fx.outsider_sub, fx.foreign_sub):
        r = client.get(f"{base(fx)}/{repo['id']}", headers=hdr(sub))
        assert r.status_code in (403, 404), (sub, r.text)
