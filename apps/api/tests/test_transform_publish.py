"""Publishing a transform from a repository (ROADMAP.md phase 2, item 2.5).

Migration 0033 said what repositories were for - "repositories are where code
is *authored*; publishing creates a `model_versions` row that copies the source
in" - and then nothing wrote `source_commit_id`, because there was no publish.

What these tests protect is not "does a publish work" but the properties that
make it safe to run twice: identity that survives a rename, a refusal rather
than a silent adoption of somebody else's transform, and a *copy* rather than a
pointer - so deleting the branch afterwards changes nothing about what runs.
"""
from __future__ import annotations

import io
import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

ROWS = b"id,total,region\n1,10,north\n2,20,south\n"


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("publish-storage")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def pbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


def rbase(fx: Fixture) -> str:
    return f"{pbase(fx)}/repositories"


@pytest.fixture()
def source(client: TestClient, fx: Fixture) -> str:
    """A dataset with real bytes behind it, named so a declaration can find it
    by name - which is how a transform names its inputs."""
    name = f"orders_{uuid.uuid4().hex[:8]}"
    r = client.post(
        f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": name},
        files={"file": ("rows.csv", io.BytesIO(ROWS), "text/csv")},
    )
    assert r.status_code == 201, r.text
    return name


@pytest.fixture()
def repo(client: TestClient, fx: Fixture) -> dict:
    r = client.post(
        rbase(fx), headers=hdr(fx.editor_sub),
        json={"name": f"Transforms {uuid.uuid4().hex[:8]}"},
    )
    assert r.status_code == 201, r.text
    return r.json()


def commit(client: TestClient, fx: Fixture, repo_id: str, files: dict,
           *, branch: str = "main", message: str = "") -> dict:
    r = client.post(
        f"{rbase(fx)}/{repo_id}/commits", headers=hdr(fx.editor_sub),
        json={"branch": branch, "files": files, "message": message},
    )
    assert r.status_code == 201, r.text
    return r.json()


def sql(output: str, source: str, alias: str = "raw", body: str = "SELECT id, total FROM raw"):
    return f"-- output: {output}\n-- input: {alias} = {source}\n{body}\n"


def do_publish(client: TestClient, fx: Fixture, repo_id: str, **kw):
    return client.post(f"{rbase(fx)}/{repo_id}/publish", headers=hdr(fx.editor_sub),
                       json=kw or {})


def do_plan(client: TestClient, fx: Fixture, repo_id: str, **params):
    return client.get(f"{rbase(fx)}/{repo_id}/publish", headers=hdr(fx.viewer_sub),
                      params=params)


# ---- the happy path ----------------------------------------------------------
def test_publishing_makes_a_declared_transform_a_definition(
    client: TestClient, fx: Fixture, repo: dict, source: str
) -> None:
    out = f"daily_{uuid.uuid4().hex[:8]}"
    made = commit(client, fx, repo["id"], {"src/daily.sql": sql(out, source)})

    r = do_publish(client, fx, repo["id"])
    assert r.status_code == 200, r.text
    step = r.json()["steps"][0]
    assert step["action"] == "created" and step["output"] == out
    assert step["version_number"] == 1
    assert [i["dataset"] for i in step["inputs"]] == [source]

    model = client.get(
        f"{pbase(fx)}/models/{step['model_id']}", headers=hdr(fx.viewer_sub)
    ).json()
    assert model["name"] == out
    assert model["source_path"] == "src/daily.sql"
    assert model["source_repo_id"] == repo["id"]

    versions = client.get(
        f"{pbase(fx)}/models/{step['model_id']}/versions", headers=hdr(fx.viewer_sub)
    ).json()
    assert versions[-1]["source_commit_id"] == made["id"]
    assert versions[-1]["source_path"] == "src/daily.sql"


def test_the_published_version_is_a_copy_not_a_pointer(
    client: TestClient, fx: Fixture, repo: dict, source: str
) -> None:
    """The property the whole storage decision was chosen for: a record of what
    ran must not change when a branch does."""
    out = f"copy_{uuid.uuid4().hex[:8]}"
    commit(client, fx, repo["id"], {"src/t.sql": sql(out, source)}, branch="work")
    published = do_publish(client, fx, repo["id"], branch="work").json()["steps"][0]

    assert client.delete(
        f"{rbase(fx)}/{repo['id']}/branches/work", headers=hdr(fx.editor_sub)
    ).status_code == 204

    model = client.get(
        f"{pbase(fx)}/models/{published['model_id']}", headers=hdr(fx.viewer_sub)
    ).json()
    assert "SELECT id, total FROM raw" in model["code"]


def test_publishing_the_same_commit_twice_writes_nothing_the_second_time(
    client: TestClient, fx: Fixture, repo: dict, source: str
) -> None:
    """A publish is not an event, it is a statement about what should be live.
    Saying it twice must not fill the history with identical versions."""
    out = f"twice_{uuid.uuid4().hex[:8]}"
    commit(client, fx, repo["id"], {"src/t.sql": sql(out, source)})
    first = do_publish(client, fx, repo["id"]).json()["steps"][0]
    second = do_publish(client, fx, repo["id"]).json()["steps"][0]

    assert first["action"] == "created" and second["action"] == "unchanged"
    assert second["unchanged"] is True
    versions = client.get(
        f"{pbase(fx)}/models/{first['model_id']}/versions", headers=hdr(fx.viewer_sub)
    ).json()
    assert len(versions) == 1


def test_editing_the_file_and_republishing_appends_a_version(
    client: TestClient, fx: Fixture, repo: dict, source: str
) -> None:
    out = f"edit_{uuid.uuid4().hex[:8]}"
    commit(client, fx, repo["id"], {"src/t.sql": sql(out, source)})
    made = do_publish(client, fx, repo["id"]).json()["steps"][0]

    second = commit(client, fx, repo["id"], {
        "src/t.sql": sql(out, source, body="SELECT id, total, region FROM raw"),
    })
    again = do_publish(client, fx, repo["id"]).json()["steps"][0]
    assert again["action"] == "updated"
    assert again["model_id"] == made["model_id"]

    versions = client.get(
        f"{pbase(fx)}/models/{made['model_id']}/versions", headers=hdr(fx.viewer_sub)
    ).json()
    assert len(versions) == 2
    assert versions[0]["source_commit_id"] == second["id"]


# ---- identity ----------------------------------------------------------------
def test_identity_is_the_path_so_a_declared_rename_moves_the_same_model(
    client: TestClient, fx: Fixture, repo: dict, source: str
) -> None:
    """Identity by name would leave the old model running forever and start a
    second one - and nothing in the data afterwards would say which was which."""
    first_name = f"before_{uuid.uuid4().hex[:8]}"
    second_name = f"after_{uuid.uuid4().hex[:8]}"
    commit(client, fx, repo["id"], {"src/t.sql": sql(first_name, source)})
    made = do_publish(client, fx, repo["id"]).json()["steps"][0]

    commit(client, fx, repo["id"], {"src/t.sql": sql(second_name, source)})
    again = do_publish(client, fx, repo["id"]).json()["steps"][0]

    assert again["model_id"] == made["model_id"], "a rename started a second model"
    models = client.get(f"{pbase(fx)}/models", headers=hdr(fx.viewer_sub)).json()
    names = [m["name"] for m in models]
    assert second_name in names and first_name not in names


def test_a_name_already_taken_by_a_hand_written_transform_is_refused(
    client: TestClient, fx: Fixture, repo: dict, source: str
) -> None:
    """Adopting it silently is how a publish deletes work nobody asked it to
    touch."""
    out = f"taken_{uuid.uuid4().hex[:8]}"
    ds = client.get(f"{pbase(fx)}/datasets", headers=hdr(fx.viewer_sub)).json()
    dataset_id = next(d["id"] for d in ds if d["name"] == source)
    client.post(f"{pbase(fx)}/models", headers=hdr(fx.editor_sub), json={
        "name": out, "code": "SELECT 1 AS x",
        "inputs": [{"dataset_id": dataset_id, "input_alias": "raw"}],
    })

    commit(client, fx, repo["id"], {"src/t.sql": sql(out, source)})
    r = do_publish(client, fx, repo["id"])
    assert r.status_code == 422, r.text
    assert "written directly rather than published" in r.json()["detail"]


def test_two_files_declaring_the_same_output_are_refused_naming_both(
    client: TestClient, fx: Fixture, repo: dict, source: str
) -> None:
    """Applying them in filename order would make the winner depend on what the
    files are called."""
    out = f"dup_{uuid.uuid4().hex[:8]}"
    commit(client, fx, repo["id"], {
        "src/a.sql": sql(out, source),
        "src/b.sql": sql(out, source, body="SELECT id FROM raw"),
    })
    r = do_publish(client, fx, repo["id"])
    assert r.status_code == 422, r.text
    assert "src/a.sql" in r.json()["detail"] and "src/b.sql" in r.json()["detail"]


# ---- refusals ----------------------------------------------------------------
def test_an_input_the_project_does_not_have_is_refused_by_name(
    client: TestClient, fx: Fixture, repo: dict
) -> None:
    commit(client, fx, repo["id"], {"src/t.sql": sql("out_x", "nosuchdataset")})
    r = do_publish(client, fx, repo["id"])
    assert r.status_code == 422, r.text
    assert "nosuchdataset" in r.json()["detail"]


def test_a_commit_that_declares_nothing_is_refused_rather_than_publishing_zero(
    client: TestClient, fx: Fixture, repo: dict
) -> None:
    commit(client, fx, repo["id"], {"README.md": "# notes\n", "src/helper.sql": "SELECT 1\n"})
    r = do_publish(client, fx, repo["id"])
    assert r.status_code == 422, r.text
    assert "declares a transform" in r.json()["detail"]


def test_an_empty_repository_says_so(client: TestClient, fx: Fixture, repo: dict) -> None:
    r = do_publish(client, fx, repo["id"])
    assert r.status_code == 409, r.text
    assert "no commits" in r.json()["detail"]


def test_a_project_that_requires_review_refuses_to_publish(
    client: TestClient, fx: Fixture, repo: dict, source: str
) -> None:
    """Publishing changes what runs, so it is subject to the gate. Letting it
    through would make `require_code_review` avoidable by putting the code in a
    repository first."""
    out = f"gated_{uuid.uuid4().hex[:8]}"
    commit(client, fx, repo["id"], {"src/t.sql": sql(out, source)})
    client.put(f"{pbase(fx)}/code/review-policy", headers=hdr(fx.owner_sub),
               json={"require_code_review": True})
    try:
        r = do_publish(client, fx, repo["id"])
        assert r.status_code == 409, r.text
        assert "requires code review" in r.json()["detail"]
        # and nothing was created
        names = [m["name"] for m in
                 client.get(f"{pbase(fx)}/models", headers=hdr(fx.viewer_sub)).json()]
        assert out not in names
    finally:
        client.put(f"{pbase(fx)}/code/review-policy", headers=hdr(fx.owner_sub),
                   json={"require_code_review": False})


def test_a_published_transform_refuses_a_direct_edit(
    client: TestClient, fx: Fixture, repo: dict, source: str
) -> None:
    """An edit the next publish overwrites is bad; one it does not is worse -
    the repository would describe a pipeline that is not the one running."""
    out = f"locked_{uuid.uuid4().hex[:8]}"
    commit(client, fx, repo["id"], {"src/t.sql": sql(out, source)})
    made = do_publish(client, fx, repo["id"]).json()["steps"][0]

    r = client.patch(f"{pbase(fx)}/models/{made['model_id']}", headers=hdr(fx.editor_sub),
                     json={"code": "SELECT 'sneaky' AS x"})
    assert r.status_code == 422, r.text
    assert "src/t.sql" in r.json()["detail"]

    # but how and when it runs is still editable - that is not what it computes.
    ok = client.patch(f"{pbase(fx)}/models/{made['model_id']}", headers=hdr(fx.editor_sub),
                      json={"description": "still mine to describe"})
    assert ok.status_code == 200, ok.text


# ---- the plan ----------------------------------------------------------------
def test_the_plan_says_what_would_happen_without_doing_it(
    client: TestClient, fx: Fixture, repo: dict, source: str
) -> None:
    out = f"plan_{uuid.uuid4().hex[:8]}"
    commit(client, fx, repo["id"], {"src/t.sql": sql(out, source)})

    seen = do_plan(client, fx, repo["id"])
    assert seen.status_code == 200, seen.text
    assert [s["output"] for s in seen.json()["steps"]] == [out]
    assert seen.json()["steps"][0]["model_id"] is None

    names = [m["name"] for m in
             client.get(f"{pbase(fx)}/models", headers=hdr(fx.viewer_sub)).json()]
    assert out not in names, "the plan published something"


def test_a_file_that_stops_declaring_leaves_its_model_reported_not_deleted(
    client: TestClient, fx: Fixture, repo: dict, source: str
) -> None:
    """A transform that has run holds a dataset other things read. Removing a
    file is not the same act as deciding that dataset should stop existing."""
    out = f"orphan_{uuid.uuid4().hex[:8]}"
    commit(client, fx, repo["id"], {"src/t.sql": sql(out, source), "README.md": "x\n"})
    made = do_publish(client, fx, repo["id"]).json()["steps"][0]

    commit(client, fx, repo["id"], {"README.md": "x\n"})
    seen = do_plan(client, fx, repo["id"])
    assert seen.status_code == 422, seen.text  # nothing left to publish

    # The model is still there, and still running what it last published.
    still = client.get(f"{pbase(fx)}/models/{made['model_id']}", headers=hdr(fx.viewer_sub))
    assert still.status_code == 200


def test_an_orphan_is_reported_alongside_the_transforms_that_remain(
    client: TestClient, fx: Fixture, repo: dict, source: str
) -> None:
    kept = f"kept_{uuid.uuid4().hex[:8]}"
    gone = f"gone_{uuid.uuid4().hex[:8]}"
    commit(client, fx, repo["id"], {
        "src/kept.sql": sql(kept, source), "src/gone.sql": sql(gone, source),
    })
    do_publish(client, fx, repo["id"])

    commit(client, fx, repo["id"], {"src/kept.sql": sql(kept, source)})
    seen = do_plan(client, fx, repo["id"]).json()
    assert [s["output"] for s in seen["steps"]] == [kept]
    assert [o["source_path"] for o in seen["orphaned"]] == ["src/gone.sql"]


# ---- permissions -------------------------------------------------------------
def test_a_viewer_may_read_the_plan_and_not_publish(
    client: TestClient, fx: Fixture, repo: dict, source: str
) -> None:
    commit(client, fx, repo["id"], {"src/t.sql": sql(f"v_{uuid.uuid4().hex[:8]}", source)})
    assert do_plan(client, fx, repo["id"]).status_code == 200
    r = client.post(f"{rbase(fx)}/{repo['id']}/publish", headers=hdr(fx.viewer_sub), json={})
    assert r.status_code == 403, r.text


def test_a_file_that_keeps_existing_but_stops_declaring_is_orphaned_too(
    client: TestClient, fx: Fixture, repo: dict, source: str
) -> None:
    """Deleting the declaration and deleting the file are the same act as far
    as the pipeline is concerned: nothing in the repository produces that
    dataset any more. Only noticing the second would leave a model running that
    the repository no longer describes."""
    kept = f"kept_{uuid.uuid4().hex[:8]}"
    dropped = f"dropped_{uuid.uuid4().hex[:8]}"
    commit(client, fx, repo["id"], {
        "src/kept.sql": sql(kept, source), "src/dropped.sql": sql(dropped, source),
    })
    do_publish(client, fx, repo["id"])

    # The file is still there. Its declaration is not.
    commit(client, fx, repo["id"], {
        "src/kept.sql": sql(kept, source),
        "src/dropped.sql": "SELECT id, total FROM raw\n",
    })
    seen = do_plan(client, fx, repo["id"]).json()
    assert [s["output"] for s in seen["steps"]] == [kept]
    assert [o["source_path"] for o in seen["orphaned"]] == ["src/dropped.sql"]
