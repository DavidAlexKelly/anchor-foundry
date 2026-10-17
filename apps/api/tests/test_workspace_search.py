"""Searching a workspace's resources by name (§990; db 0174).

The resource browser searched one project at a time, so finding a dataset
meant knowing which project it was in first. These hold the workspace-wide
search: names that hold the words, in every project the person can read,
the name itself first and the ones that start with it next, nothing in the
trash, and nothing from anybody else's workspace.
"""
from __future__ import annotations

import io
import os
import sys
import uuid
from typing import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

ADMIN_DSN = os.environ["TEST_ADMIN_DSN"]


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(LocalStorageGateway(str(tmp_path_factory.mktemp("search"))))
    with TestClient(create_app(), raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def upload(client: TestClient, fx: Fixture, project, name: str) -> str:
    r = client.post(f"/api/workspaces/{fx.workspace}/projects/{project}/datasets/upload",
                    headers=hdr(fx.editor_sub), data={"name": name},
                    files={"file": ("x.csv", io.BytesIO(b"id\n1\n"), "text/csv")})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture(scope="module")
def workspace(client: TestClient) -> dict:
    fx = Fixture()
    tag = uuid.uuid4().hex[:6]
    r = client.post(f"/api/workspaces/{fx.workspace}/projects", headers=hdr(fx.owner_sub),
                    json={"name": f"Second {tag}", "slug": f"second-{tag}"})
    assert r.status_code == 201, r.text
    second = r.json()["id"]
    word = f"orders{tag}"
    made = {
        "exact": upload(client, fx, fx.project, word),
        "prefix": upload(client, fx, second, f"{word}_clean"),
        "inside": upload(client, fx, fx.project, f"Daily {word}"),
        "other": upload(client, fx, fx.project, f"customers{tag}"),
        "binned": upload(client, fx, fx.project, f"{word} old"),
    }
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE resources SET trashed_at = now() WHERE id = "
                     "(SELECT resource_id FROM datasets WHERE id = %s)", (made["binned"],))
    return {"fx": fx, "word": word, "second": second, "tag": tag}


def search(client: TestClient, fx: Fixture, q: str, who=None) -> list[dict]:
    r = client.get(f"/api/workspaces/{fx.workspace}/search", params={"q": q},
                   headers=hdr(who or fx.viewer_sub))
    assert r.status_code == 200, r.text
    return r.json()


def test_the_name_itself_then_the_ones_starting_with_it_then_the_rest(client, workspace) -> None:
    fx, word = workspace["fx"], workspace["word"]
    hits = search(client, fx, word.upper())
    assert [h["name"] for h in hits] == [word, f"{word}_clean", f"Daily {word}"]


def test_every_project_is_searched_and_each_hit_says_which(client, workspace) -> None:
    fx = workspace["fx"]
    [hit] = search(client, fx, f"{workspace['word']}_clean")
    assert hit["project_id"] == workspace["second"]
    assert hit["project_slug"] == f"second-{workspace['tag']}"
    assert hit["kind"] == "dataset"


def test_nothing_in_the_trash(client, workspace) -> None:
    fx = workspace["fx"]
    assert search(client, fx, f"{workspace['word']} old") == []


def test_what_is_typed_is_matched_as_typed(client, workspace) -> None:
    """A wildcard typed is the character: `_` is not "any letter"."""
    fx, tag = workspace["fx"], workspace["tag"]
    assert search(client, fx, f"orders{tag}%") == []
    assert [h["name"] for h in search(client, fx, "_clean") if tag in h["name"]] == [
        f"orders{tag}_clean"]


def test_nobody_reads_another_workspace_through_it(client, workspace) -> None:
    fx = workspace["fx"]
    other = Fixture()
    assert all(workspace["tag"] not in h["name"]
               for h in search(client, other, workspace["word"], who=other.viewer_sub))
    r = client.get(f"/api/workspaces/{fx.workspace}/search", params={"q": workspace["word"]},
                   headers=hdr(other.viewer_sub))
    assert r.status_code == 404


def test_an_empty_search_is_refused(client, workspace) -> None:
    fx = workspace["fx"]
    r = client.get(f"/api/workspaces/{fx.workspace}/search", params={"q": ""},
                   headers=hdr(fx.viewer_sub))
    assert r.status_code == 422
