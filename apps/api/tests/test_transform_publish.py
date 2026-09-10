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


# ---- a proposal over a commit (db 0039) --------------------------------------
def cbase(fx: Fixture) -> str:
    return f"{pbase(fx)}/code"


def review_on(client: TestClient, fx: Fixture, on: bool) -> None:
    r = client.put(f"{cbase(fx)}/review-policy", headers=hdr(fx.owner_sub),
                   json={"require_code_review": on})
    assert r.status_code == 200, r.text


@pytest.fixture()
def gated(client: TestClient, fx: Fixture):
    """Review on for the test, off again afterwards - it is project-wide."""
    review_on(client, fx, True)
    yield
    review_on(client, fx, False)


def propose_commit(client: TestClient, fx: Fixture, repo_id: str, commit_id: str,
                   summary: str = "Publish this commit", sub: str | None = None):
    return client.post(
        f"{cbase(fx)}/proposals", headers=hdr(sub or fx.editor_sub),
        json={"summary": summary, "source_repo_id": repo_id,
              "source_commit_id": commit_id},
    )


def test_a_gated_project_cannot_publish_directly_and_is_told_where_to_go(
    client: TestClient, fx: Fixture, repo: dict, source: str, gated
) -> None:
    commit(client, fx, repo["id"], {"src/t.sql": sql(f"g_{uuid.uuid4().hex[:8]}", source)})
    r = do_publish(client, fx, repo["id"])
    assert r.status_code == 409, r.text
    assert "open a proposal for it" in r.json()["detail"]


def test_a_proposal_over_a_commit_derives_its_files_from_the_commit(
    client: TestClient, fx: Fixture, repo: dict, source: str, gated
) -> None:
    """No `code_proposal_files` rows exist for it. The commit is immutable, so
    the code under review cannot be swapped after an approval - a stronger
    guarantee than stored files give, not a weaker one."""
    out = f"derived_{uuid.uuid4().hex[:8]}"
    made = commit(client, fx, repo["id"], {"src/t.sql": sql(out, source)})

    r = propose_commit(client, fx, repo["id"], made["id"])
    assert r.status_code == 201, r.text
    detail = r.json()
    assert detail["source_commit_id"] == made["id"]
    assert detail["source_repo_id"] == repo["id"]
    assert len(detail["files"]) == 1
    f = detail["files"][0]
    assert f["path"] == "src/t.sql"
    assert f["model_id"] is None
    assert "SELECT id, total FROM raw" in f["code"]
    assert f["rows"], "no side-by-side rows for a derived file"


def test_applying_a_commit_proposal_publishes_it(
    client: TestClient, fx: Fixture, repo: dict, source: str, gated
) -> None:
    out = f"applied_{uuid.uuid4().hex[:8]}"
    made = commit(client, fx, repo["id"], {"src/t.sql": sql(out, source)})
    p = propose_commit(client, fx, repo["id"], made["id"]).json()

    client.post(f"{cbase(fx)}/proposals/{p['id']}/reviews", headers=hdr(fx.owner_sub),
                json={"verdict": "approve", "comment": "looks right"})
    applied = client.post(f"{cbase(fx)}/proposals/{p['id']}/apply",
                          headers=hdr(fx.editor_sub))
    assert applied.status_code == 200, applied.text
    assert applied.json()["state"] == "applied"
    assert applied.json()["change_set_id"]

    models = client.get(f"{pbase(fx)}/models", headers=hdr(fx.viewer_sub)).json()
    published = next((m for m in models if m["name"] == out), None)
    assert published is not None, "applying the proposal did not publish"
    assert published["source_path"] == "src/t.sql"

    versions = client.get(
        f"{pbase(fx)}/models/{published['id']}/versions", headers=hdr(fx.viewer_sub)
    ).json()
    assert versions[-1]["source_commit_id"] == made["id"]


def test_a_commit_proposal_cannot_be_applied_without_an_approval(
    client: TestClient, fx: Fixture, repo: dict, source: str, gated
) -> None:
    """The whole point of the join: publishing now goes through the gate rather
    than round it."""
    out = f"ungated_{uuid.uuid4().hex[:8]}"
    made = commit(client, fx, repo["id"], {"src/t.sql": sql(out, source)})
    p = propose_commit(client, fx, repo["id"], made["id"]).json()
    assert any("approved" in b for b in p["blockers"]), p["blockers"]

    r = client.post(f"{cbase(fx)}/proposals/{p['id']}/apply", headers=hdr(fx.editor_sub))
    assert r.status_code == 422, r.text
    names = [m["name"] for m in
             client.get(f"{pbase(fx)}/models", headers=hdr(fx.viewer_sub)).json()]
    assert out not in names


def test_nobody_approves_their_own_commit_proposal_either(
    client: TestClient, fx: Fixture, repo: dict, source: str, gated
) -> None:
    made = commit(client, fx, repo["id"],
                  {"src/t.sql": sql(f"own_{uuid.uuid4().hex[:8]}", source)})
    p = propose_commit(client, fx, repo["id"], made["id"]).json()
    r = client.post(f"{cbase(fx)}/proposals/{p['id']}/reviews", headers=hdr(fx.editor_sub),
                    json={"verdict": "approve", "comment": ""})
    assert r.status_code == 422, r.text


def test_a_comment_on_a_file_with_no_model_yet_anchors_to_its_path(
    client: TestClient, fx: Fixture, repo: dict, source: str, gated
) -> None:
    """`code_proposal_comments.model_id` was NOT NULL, which is right for a
    change to an existing transform and impossible for a file that will produce
    a new one."""
    made = commit(client, fx, repo["id"],
                  {"src/t.sql": sql(f"anchor_{uuid.uuid4().hex[:8]}", source)})
    p = propose_commit(client, fx, repo["id"], made["id"]).json()

    r = client.post(
        f"{cbase(fx)}/proposals/{p['id']}/comments", headers=hdr(fx.viewer_sub),
        json={"source_path": "src/t.sql", "side": "proposed", "line": 3,
              "body": "does this need the total column?"},
    )
    assert r.status_code == 201, r.text
    comment = r.json()["comments"][0]
    assert comment["source_path"] == "src/t.sql" and comment["model_id"] is None
    assert [c["id"] for c in r.json()["files"][0]["comments"]] == [comment["id"]]


def test_a_comment_on_a_path_the_proposal_does_not_touch_is_refused(
    client: TestClient, fx: Fixture, repo: dict, source: str, gated
) -> None:
    made = commit(client, fx, repo["id"],
                  {"src/t.sql": sql(f"nope_{uuid.uuid4().hex[:8]}", source)})
    p = propose_commit(client, fx, repo["id"], made["id"]).json()
    r = client.post(
        f"{cbase(fx)}/proposals/{p['id']}/comments", headers=hdr(fx.viewer_sub),
        json={"source_path": "src/elsewhere.sql", "side": "proposed", "line": 1,
              "body": "nowhere"},
    )
    assert r.status_code == 422, r.text
    assert "does not change that file" in r.json()["detail"]


def test_marking_a_pathless_file_read_works_the_same_way(
    client: TestClient, fx: Fixture, repo: dict, source: str, gated
) -> None:
    made = commit(client, fx, repo["id"],
                  {"src/t.sql": sql(f"mark_{uuid.uuid4().hex[:8]}", source)})
    p = propose_commit(client, fx, repo["id"], made["id"]).json()
    r = client.put(f"{cbase(fx)}/proposals/{p['id']}/read", headers=hdr(fx.viewer_sub),
                   json={"source_path": "src/t.sql", "read": True})
    assert r.status_code == 200, r.text
    assert len(r.json()["files"][0]["read_by"]) == 1


def test_checks_run_on_a_commit_proposal_and_gate_it(
    client: TestClient, fx: Fixture, repo: dict, source: str, gated
) -> None:
    """A check that found nothing to do and reported success by silence would
    be the worst outcome here - a commit-backed proposal has no
    `code_proposal_files` rows at all."""
    good = commit(client, fx, repo["id"],
                  {"src/ok.sql": sql(f"ok_{uuid.uuid4().hex[:8]}", source)})
    p = propose_commit(client, fx, repo["id"], good["id"]).json()
    ran = client.post(f"{cbase(fx)}/proposals/{p['id']}/checks", headers=hdr(fx.editor_sub))
    assert ran.status_code == 200, ran.text
    names = sorted(c["name"] for c in ran.json()["checks"])
    assert names == ["schema_compatible", "transform_runs"]
    assert {c["status"] for c in ran.json()["checks"]} == {"pass"}, [
        (c["name"], c["status"], c["summary"]) for c in ran.json()["checks"]
    ]
    assert ran.json()["checks"][0]["source_path"] == "src/ok.sql"

    broken = commit(client, fx, repo["id"], {
        "src/bad.sql": sql(f"bad_{uuid.uuid4().hex[:8]}", source,
                           body="SELECT nosuchcolumn FROM raw"),
    }, branch="broken")
    q = propose_commit(client, fx, repo["id"], broken["id"], summary="Broken").json()
    failed = client.post(f"{cbase(fx)}/proposals/{q['id']}/checks",
                         headers=hdr(fx.editor_sub)).json()
    assert any(c["status"] == "fail" for c in failed["checks"]), failed["checks"]
    assert any(b.startswith("a check failed") for b in failed["blockers"])


def test_a_proposal_is_either_a_commit_or_a_set_of_files(
    client: TestClient, fx: Fixture, repo: dict, source: str, gated
) -> None:
    """One describes files typed into the proposal, the other describes files
    that already exist. Both would be two answers to "what is being reviewed"."""
    made = commit(client, fx, repo["id"],
                  {"src/t.sql": sql(f"both_{uuid.uuid4().hex[:8]}", source)})
    models = client.get(f"{pbase(fx)}/models", headers=hdr(fx.viewer_sub)).json()
    if not models:
        pytest.skip("no model to build a file change from")
    r = client.post(
        f"{cbase(fx)}/proposals", headers=hdr(fx.editor_sub),
        json={"summary": "Both", "source_repo_id": repo["id"],
              "source_commit_id": made["id"],
              "changes": [{"model_id": models[0]["id"], "code": "SELECT 1 AS x"}]},
    )
    assert r.status_code == 422, r.text
    assert "not both" in r.json()["detail"]


def test_a_commit_that_declares_nothing_cannot_become_a_proposal(
    client: TestClient, fx: Fixture, repo: dict, gated
) -> None:
    """Refused at the door rather than becoming a proposal nobody can apply."""
    made = commit(client, fx, repo["id"], {"README.md": "# nothing here\n"})
    r = propose_commit(client, fx, repo["id"], made["id"])
    assert r.status_code == 422, r.text


def test_a_commit_proposal_survives_the_branch_being_deleted(
    client: TestClient, fx: Fixture, repo: dict, source: str, gated
) -> None:
    """A proposal is a record of what was asked for. One whose commit vanished
    would be a review of nothing - which is why the FK is RESTRICT and why the
    branch pointer is not what it holds."""
    out = f"survives_{uuid.uuid4().hex[:8]}"
    made = commit(client, fx, repo["id"], {"src/t.sql": sql(out, source)}, branch="tmp")
    p = propose_commit(client, fx, repo["id"], made["id"]).json()

    assert client.delete(f"{rbase(fx)}/{repo['id']}/branches/tmp",
                         headers=hdr(fx.editor_sub)).status_code == 204

    still = client.get(f"{cbase(fx)}/proposals/{p['id']}", headers=hdr(fx.viewer_sub))
    assert still.status_code == 200, still.text
    assert len(still.json()["files"]) == 1


def test_a_comment_cannot_name_both_a_model_and_a_path(
    client: TestClient, fx: Fixture, repo: dict, source: str, gated
) -> None:
    """Two anchors is two answers to "which file is this about". Refused with a
    sentence rather than left to the database's own CHECK, which would arrive
    as a 500."""
    made = commit(client, fx, repo["id"],
                  {"src/t.sql": sql(f"anchors_{uuid.uuid4().hex[:8]}", source)})
    p = propose_commit(client, fx, repo["id"], made["id"]).json()
    models = client.get(f"{pbase(fx)}/models", headers=hdr(fx.viewer_sub)).json()
    if not models:
        pytest.skip("no model to name alongside a path")
    r = client.post(
        f"{cbase(fx)}/proposals/{p['id']}/comments", headers=hdr(fx.viewer_sub),
        json={"model_id": models[0]["id"], "source_path": "src/t.sql",
              "side": "proposed", "line": 1, "body": "which one?"},
    )
    assert r.status_code == 422, r.text

    neither = client.post(
        f"{cbase(fx)}/proposals/{p['id']}/comments", headers=hdr(fx.viewer_sub),
        json={"side": "proposed", "line": 1, "body": "about what?"},
    )
    assert neither.status_code == 422, neither.text


def test_a_commit_proposal_goes_stale_when_another_one_lands_first(
    client: TestClient, fx: Fixture, repo: dict, source: str, gated
) -> None:
    """Two proposals over the same file. The second must not silently overwrite
    the first - which is what `base_version` guards for a file-backed proposal,
    and what a commit-backed one derives from the version that existed when it
    was opened."""
    out = f"race_{uuid.uuid4().hex[:8]}"
    first = commit(client, fx, repo["id"], {"src/t.sql": sql(out, source)})
    a = propose_commit(client, fx, repo["id"], first["id"], summary="A").json()
    client.post(f"{cbase(fx)}/proposals/{a['id']}/reviews", headers=hdr(fx.owner_sub),
                json={"verdict": "approve", "comment": ""})
    landed = client.post(f"{cbase(fx)}/proposals/{a['id']}/apply", headers=hdr(fx.editor_sub))
    assert landed.status_code == 200, landed.text

    # On a sandbox from here: `main` is protected while review is required
    # (§284), and the successive versions are the point of this test rather
    # than the branch they sit on.
    sandbox(client, fx, repo["id"], "race")
    second = commit(client, fx, repo["id"], {
        "src/t.sql": sql(out, source, body="SELECT id, total, region FROM raw"),
    }, branch="race")
    b = propose_commit(client, fx, repo["id"], second["id"], summary="B").json()
    assert b["files"][0]["base_version"] == b["files"][0]["current_version"]

    third = commit(client, fx, repo["id"], {
        "src/t.sql": sql(out, source, body="SELECT id FROM raw"),
    }, branch="race")
    c = propose_commit(client, fx, repo["id"], third["id"], summary="C").json()
    client.post(f"{cbase(fx)}/proposals/{c['id']}/reviews", headers=hdr(fx.owner_sub),
                json={"verdict": "approve", "comment": ""})
    assert client.post(f"{cbase(fx)}/proposals/{c['id']}/apply",
                       headers=hdr(fx.editor_sub)).status_code == 200

    # B was opened against the version C has now replaced.
    stale = client.get(f"{cbase(fx)}/proposals/{b['id']}", headers=hdr(fx.viewer_sub)).json()
    assert stale["files"][0]["base_version"] < stale["files"][0]["current_version"]
    assert any("overwrite work nobody reviewed" in x for x in stale["blockers"]), \
        stale["blockers"]

    client.post(f"{cbase(fx)}/proposals/{b['id']}/reviews", headers=hdr(fx.owner_sub),
                json={"verdict": "approve", "comment": ""})
    refused = client.post(f"{cbase(fx)}/proposals/{b['id']}/apply",
                          headers=hdr(fx.editor_sub))
    assert refused.status_code == 422, refused.text


# ---- Python, which no test here had ever published (§272) --------------------
def py(output: str, source: str, alias: str = "raw") -> str:
    """A Python transform as decision 0004 prints one."""
    return (
        f"@transform(output={output!r}, inputs={{{alias!r}: {source!r}}})\n"
        f"def build({alias}):\n"
        f"    return {alias}\n"
    )


def test_publishing_a_python_transform_stores_what_the_runner_will_execute(
    client: TestClient, fx: Fixture, repo: dict, source: str
) -> None:
    """**Every file in this suite was `.sql`.** That is how a Python transform
    came to be publishable and unrunnable at the same time: the publisher
    copies the file's source into `models.code` verbatim, and the worker's
    sandbox exec'd it into a namespace with no `transform` in it, so the
    decorator raised `NameError` before any of the sandbox's limits applied.
    Neither half was wrong about itself, and nothing here crossed between them.

    This asserts the seam rather than the run: the definition that lands is
    the file, byte for byte, and `apps/worker/tests/test_python_sandbox.py`
    holds the other end - that this exact shape produces a table.
    """
    out = f"pydaily_{uuid.uuid4().hex[:8]}"
    file = py(out, source)
    commit(client, fx, repo["id"], {"src/daily.py": file})

    r = do_publish(client, fx, repo["id"])
    assert r.status_code == 200, r.text
    step = r.json()["steps"][0]
    assert step["language"] == "python", step
    assert [i["dataset"] for i in step["inputs"]] == [source]

    model = client.get(
        f"{pbase(fx)}/models/{step['model_id']}", headers=hdr(fx.viewer_sub)
    ).json()
    assert model["language"] == "python"
    # The runner is handed this string and nothing else. A publish that
    # rewrote it - stripping the decorator, wrapping the body - would make the
    # repository describe something other than what runs, which is the one
    # thing db 0038's refusal exists to prevent.
    assert model["code"] == file


def test_a_python_file_declaring_two_transforms_is_refused(
    client: TestClient, fx: Fixture, repo: dict, source: str
) -> None:
    """SQL has refused two `-- output:` lines since it was written; Python
    returned the first of two and dropped the second silently, so the second
    transform was never built and never appeared in lineage. Asserted here
    rather than only in the unit test because this is the layer where the
    consequence lives: a publish that quietly builds half a file."""
    a, b = f"one_{uuid.uuid4().hex[:6]}", f"two_{uuid.uuid4().hex[:6]}"
    both = (
        f"@transform(output={a!r}, inputs={{'raw': {source!r}}})\ndef one(raw):\n    return raw\n\n"
        f"@transform(output={b!r}, inputs={{'raw': {source!r}}})\ndef two(raw):\n    return raw\n"
    )
    commit(client, fx, repo["id"], {"src/both.py": both})

    r = do_publish(client, fx, repo["id"])
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert "more than one transform" in detail, detail
    assert "one" in detail and "two" in detail, detail

    # And nothing was created for the half it could have taken.
    models = client.get(f"{pbase(fx)}/models", headers=hdr(fx.viewer_sub)).json()
    assert a not in [m["name"] for m in models]


def test_a_comment_declared_script_publishes_and_is_stored_verbatim(
    client: TestClient, fx: Fixture, repo: dict, source: str
) -> None:
    """§273: the shape B.1 needs, on the publish path.

    A model authored in the Models editor is a *script* - inputs as
    module-level names, the result assigned to `output` - and until decision
    0017 it had no way to declare, so it could not live in a repository at all
    and its only editor was the one B.1 deletes. This is that file publishing.

    Stored verbatim, like every other published file: the header is comments,
    so the code the runner gets is the script the author wrote with two lines
    above it, and `test_python_sandbox.py` holds the other end.
    """
    out = f"script_{uuid.uuid4().hex[:8]}"
    file = f"# output: {out}\n# input: raw = {source}\n\noutput = raw\n"
    commit(client, fx, repo["id"], {"src/script.py": file})

    r = do_publish(client, fx, repo["id"])
    assert r.status_code == 200, r.text
    step = r.json()["steps"][0]
    assert step["output"] == out
    assert step["language"] == "python"
    assert [i["dataset"] for i in step["inputs"]] == [source]

    model = client.get(
        f"{pbase(fx)}/models/{step['model_id']}", headers=hdr(fx.viewer_sub)
    ).json()
    assert model["code"] == file


def test_a_python_file_declaring_both_ways_is_refused_at_publish(
    client: TestClient, fx: Fixture, repo: dict, source: str
) -> None:
    """"One file, one transform" between the forms as well as within each.
    Asserted at this layer too because this is where the consequence lives: a
    publish that picked one of two declarations would build something the file
    does not unambiguously say."""
    out = f"both_{uuid.uuid4().hex[:8]}"
    both = (
        f"# output: {out}\n"
        f"@transform(output={out!r}, inputs={{'raw': {source!r}}})\n"
        "def build(raw):\n    return raw\n"
    )
    commit(client, fx, repo["id"], {"src/both.py": both})

    r = do_publish(client, fx, repo["id"])
    assert r.status_code == 422, r.text
    assert "declares a transform twice" in r.json()["detail"], r.text


# ---- adoption: the other direction (B.1; §274) --------------------------------
def make_model(client, fx, *, name, code, language="sql", inputs=None):
    r = client.post(
        f"{pbase(fx)}/models", headers=hdr(fx.editor_sub),
        json={"name": name, "language": language, "code": code,
              "inputs": inputs or []},
    )
    assert r.status_code == 201, r.text
    return r.json()


def adopt(client, fx, model_id, repo_id, **kw):
    return client.post(
        f"{pbase(fx)}/models/{model_id}/adopt", headers=hdr(fx.editor_sub),
        json={"repository_id": repo_id, **kw},
    )


def dataset_id(client, fx, name: str) -> str:
    rows = client.get(f"{pbase(fx)}/datasets", headers=hdr(fx.viewer_sub)).json()
    rows = rows["items"] if isinstance(rows, dict) else rows
    return next(str(d["id"]) for d in rows if d["name"] == name)


def test_adopting_writes_the_file_and_points_the_model_at_it(
    client: TestClient, fx: Fixture, repo: dict, source: str
) -> None:
    """**The whole of B.1's blocker, in one test.**

    Before this, a model that had never been in a repository could only be
    edited on `code/page.tsx` — the page B.1 deletes — and in a review-required
    project it could not be edited at all. Adoption is what gives it a file.
    """
    name = f"adopted_{uuid.uuid4().hex[:8]}"
    model = make_model(
        client, fx, name=name, code="SELECT id, total FROM raw",
        inputs=[{"dataset_id": dataset_id(client, fx, source), "input_alias": "raw"}],
    )

    r = adopt(client, fx, model["id"], repo["id"])
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["path"] == f"src/{name}.sql"

    # The model now names the file...
    after = client.get(
        f"{pbase(fx)}/models/{model['id']}", headers=hdr(fx.viewer_sub)
    ).json()
    assert after["source_repo_id"] == repo["id"]
    assert after["source_path"] == out["path"]

    # ...and the file resolves back to *this* model rather than declaring a
    # second one. That is the round trip that matters: identity is
    # `(repository, path)` (db 0038), so a file whose declaration named
    # something else would publish alongside the model instead of into it.
    plan = do_plan(client, fx, repo["id"]).json()
    step = next(s for s in plan["steps"] if s["path"] == out["path"])
    assert step["output"] == name
    assert step["model_id"] == model["id"], "adoption created a second model"
    assert [i["dataset"] for i in step["inputs"]] == [source]

    # **The file is not byte-identical to `models.code`, and should not be.**
    # It is the code with a declaration above it, so the plan honestly reports
    # a change. Publishing writes that header in as a version and the two agree
    # from then on - one model throughout, and the code below the header is
    # still exactly what was written in the editor.
    assert step["unchanged"] is False
    published = do_publish(client, fx, repo["id"]).json()["steps"]
    assert [s["model_id"] for s in published] == [model["id"]]

    final = client.get(
        f"{pbase(fx)}/models/{model['id']}", headers=hdr(fx.viewer_sub)
    ).json()
    assert final["code"].endswith("SELECT id, total FROM raw")
    assert final["code"].startswith(f"-- output: {name}")


def test_an_adopted_model_refuses_a_direct_edit(
    client: TestClient, fx: Fixture, repo: dict, source: str
) -> None:
    """db 0038's refusal, now reachable by adoption rather than only by publish.
    This is the point of the whole exercise: after adoption the file is where
    the transform is edited, and a direct edit would make the repository
    describe a pipeline that is not the one running."""
    name = f"locked_{uuid.uuid4().hex[:8]}"
    model = make_model(client, fx, name=name, code="SELECT 1")
    assert adopt(client, fx, model["id"], repo["id"]).status_code == 200

    r = client.patch(
        f"{pbase(fx)}/models/{model['id']}", headers=hdr(fx.editor_sub),
        json={"code": "SELECT 2"},
    )
    assert r.status_code in (409, 422), r.text
    assert "repository" in r.text


def test_a_model_whose_name_cannot_be_declared_is_refused_naming_it(
    client: TestClient, fx: Fixture, repo: dict
) -> None:
    """Model names are constrained only by length (db 0001), so a name can
    exist that the declaration syntax cannot write. Written straight through,
    the reader's own message for this is "declares inputs but no output" —
    which sends the author to look at their inputs. So the check happens before
    the file exists and says which value is wrong."""
    model = make_model(client, fx, name=f"Daily Totals {uuid.uuid4().hex[:6]}",
                       code="SELECT 1")
    r = adopt(client, fx, model["id"], repo["id"])
    assert r.status_code in (409, 422), r.text
    assert "Daily Totals" in r.text, r.text


def test_a_model_whose_code_absorbs_the_declaration_is_refused(
    client: TestClient, fx: Fixture, repo: dict, source: str
) -> None:
    """**The measured hazard, at the layer that would suffer it.**

    The reader takes the leading comment block only, so a model whose own code
    begins with `-- input: ...` produces a file whose declaration silently
    gains an input the model never had. It does not fail — it parses — so only
    reading the composed file back catches it, and only by exact equality.
    """
    name = f"absorb_{uuid.uuid4().hex[:8]}"
    model = make_model(
        client, fx, name=name,
        code="-- input: sneaky = somewhere_else\nSELECT id FROM raw",
        inputs=[{"dataset_id": dataset_id(client, fx, source), "input_alias": "raw"}],
    )
    r = adopt(client, fx, model["id"], repo["id"])
    assert r.status_code in (409, 422), r.text
    assert "sneaky" in r.text, r.text


def test_a_model_cannot_be_adopted_twice(
    client: TestClient, fx: Fixture, repo: dict
) -> None:
    """The second adoption would write a second file declaring the same output,
    which `plan` refuses anyway — but it would already have committed it, so
    the repository would carry a file that can never be published."""
    model = make_model(client, fx, name=f"once_{uuid.uuid4().hex[:8]}", code="SELECT 1")
    assert adopt(client, fx, model["id"], repo["id"]).status_code == 200
    r = adopt(client, fx, model["id"], repo["id"])
    assert r.status_code in (409, 422), r.text
    assert "already authored" in r.text


def test_the_path_extension_has_to_match_the_language(
    client: TestClient, fx: Fixture, repo: dict
) -> None:
    """`transform_publish` reads a file's language off its path, so a Python
    model written to a `.sql` file would publish back as SQL and be handed to
    DuckDB. Refused rather than corrected: a caller that asked for the wrong one
    is confused about something, and a silent rename hides it."""
    model = make_model(client, fx, name=f"pymodel_{uuid.uuid4().hex[:8]}",
                       language="python", code="output = 1")
    r = adopt(client, fx, model["id"], repo["id"], path="src/thing.sql")
    assert r.status_code in (409, 422), r.text
    assert ".py" in r.text


def test_adopting_into_a_taken_path_is_refused_before_it_commits(
    client: TestClient, fx: Fixture, repo: dict, source: str
) -> None:
    out = f"taken_{uuid.uuid4().hex[:8]}"
    commit(client, fx, repo["id"], {"src/taken.sql": sql(out, source)})
    model = make_model(client, fx, name=f"other_{uuid.uuid4().hex[:8]}", code="SELECT 1")

    r = adopt(client, fx, model["id"], repo["id"], path="src/taken.sql")
    assert r.status_code in (409, 422), r.text
    assert "already exists" in r.text

    # And nothing moved: the model is still directly authored.
    after = client.get(
        f"{pbase(fx)}/models/{model['id']}", headers=hdr(fx.viewer_sub)
    ).json()
    assert after["source_repo_id"] is None


def test_adopting_keeps_every_file_the_repository_already_had(
    client: TestClient, fx: Fixture, repo: dict, source: str
) -> None:
    """**A commit is a snapshot, not a patch** (decision 0003), so adoption has
    to send the whole tree back with one file added. Sending only the new file
    is a commit that *deletes the repository* — and it is one character of
    difference, `{**files, target: source}` against `{target: source}`.

    Every other adoption test here used an empty repository or collided on the
    path it was adopting to, so all of them passed against that mutant. §212's
    rule in its most expensive form: a fixture that never crosses the boundary
    cannot see the boundary, and here the boundary is "the repository already
    contains something".
    """
    kept = f"kept_{uuid.uuid4().hex[:8]}"
    commit(client, fx, repo["id"], {
        "src/existing.sql": sql(kept, source),
        "README.md": "# transforms\n",
    })

    model = make_model(client, fx, name=f"added_{uuid.uuid4().hex[:8]}", code="SELECT 1")
    r = adopt(client, fx, model["id"], repo["id"])
    assert r.status_code == 200, r.text
    added = r.json()["path"]

    tree = client.get(f"{rbase(fx)}/{repo['id']}/tree", headers=hdr(fx.viewer_sub))
    assert tree.status_code == 200, tree.text
    files = tree.json()["files"]

    assert "src/existing.sql" in files, sorted(files)
    assert "README.md" in files, sorted(files)
    assert added in files, sorted(files)
    # And byte-identical, not merely present: a commit that rewrote the tree
    # would be as wrong as one that dropped it.
    assert files["README.md"] == "# transforms\n"
    assert files["src/existing.sql"] == sql(kept, source)


# ---- applying lands the commit on the branch (§283) ---------------------------
# `code-repositories.md` §2.1's protected-branch rule is what makes the Pull
# requests tab load-bearing: work happens on a sandbox and lands through a
# review. That rule is unworkable until applying a proposal *moves the branch* -
# otherwise the first person to use the review path the way it is meant to be
# used leaves the default branch behind forever, and the branch everybody opens
# the repository on stops describing the repository.
#
# It was invisible until now because everything was committed to `main` first:
# the branch was already at the commit, so "the branch does not move" and "the
# branch is right" were the same picture.
def branch_head(client: TestClient, fx: Fixture, repo_id: str, name: str) -> str | None:
    rows = client.get(f"{rbase(fx)}/{repo_id}/branches", headers=hdr(fx.viewer_sub)).json()
    row = next((b for b in rows if b["name"] == name), None)
    return row["head_commit_id"] if row else None


def sandbox(client: TestClient, fx: Fixture, repo_id: str, name: str,
            *, frm: str = "main") -> None:
    r = client.post(f"{rbase(fx)}/{repo_id}/branches", headers=hdr(fx.editor_sub),
                    json={"name": name, "from_branch": frm})
    assert r.status_code == 201, r.text


def approve_and_apply(client: TestClient, fx: Fixture, proposal_id: str):
    client.post(f"{cbase(fx)}/proposals/{proposal_id}/reviews", headers=hdr(fx.owner_sub),
                json={"verdict": "approve", "comment": "yes"})
    return client.post(f"{cbase(fx)}/proposals/{proposal_id}/apply", headers=hdr(fx.editor_sub))


def test_applying_a_proposal_made_on_a_sandbox_moves_the_default_branch(
    client: TestClient, fx: Fixture, repo: dict, source: str, gated
) -> None:
    """**The unit.** Before this, `main` stayed where it was and the work only
    existed on a branch somebody could delete."""
    out = f"landed_{uuid.uuid4().hex[:8]}"
    first = commit(client, fx, repo["id"], {"README.md": "# transforms\n"})
    sandbox(client, fx, repo["id"], "work")
    made = commit(client, fx, repo["id"],
                  {"README.md": "# transforms\n", "src/t.sql": sql(out, source)},
                  branch="work")
    assert branch_head(client, fx, repo["id"], "main") == first["id"]

    p = propose_commit(client, fx, repo["id"], made["id"]).json()
    assert p["lands_on"] == "main"
    assert p["landing"] == "fast_forward"

    applied = approve_and_apply(client, fx, p["id"])
    assert applied.status_code == 200, applied.text
    assert branch_head(client, fx, repo["id"], "main") == made["id"]

    # And the tree the repository opens on is the work, not the state before it.
    tree = client.get(f"{rbase(fx)}/{repo['id']}/tree", headers=hdr(fx.viewer_sub)).json()
    assert "src/t.sql" in tree["files"], sorted(tree["files"])


def test_a_commit_already_on_the_branch_lands_without_moving_anything(
    client: TestClient, fx: Fixture, repo: dict, source: str, gated
) -> None:
    """The path every existing proposal takes: committed to `main`, proposed,
    applied. Nothing to move, and nothing wrong - so this must not become a
    refusal now that there is something to refuse."""
    out = f"already_{uuid.uuid4().hex[:8]}"
    made = commit(client, fx, repo["id"], {"src/t.sql": sql(out, source)})
    p = propose_commit(client, fx, repo["id"], made["id"]).json()
    assert p["landing"] == "landed"

    assert approve_and_apply(client, fx, p["id"]).status_code == 200
    assert branch_head(client, fx, repo["id"], "main") == made["id"]


def test_a_proposal_over_a_commit_the_branch_has_moved_past_still_applies(
    client: TestClient, fx: Fixture, repo: dict, source: str, gated
) -> None:
    """**The branch being ahead is not a divergence.**

    `move_branch` refuses to move backwards, and rightly - that discards
    commits. But not moving at all discards nothing, and a proposal whose
    commit is already in the branch's history has simply been overtaken. A
    refusal here would strand every proposal made before somebody else's
    landed.
    """
    out = f"overtaken_{uuid.uuid4().hex[:8]}"
    first = commit(client, fx, repo["id"], {"src/t.sql": sql(out, source)})

    # `main` moves the only way it can now that it is protected (§284): another
    # proposal, over a descendant, landing first.
    sandbox(client, fx, repo["id"], "ahead")
    later = commit(client, fx, repo["id"],
                   {"src/t.sql": sql(out, source), "README.md": "# later\n"},
                   branch="ahead")
    q = propose_commit(client, fx, repo["id"], later["id"], summary="the newer one").json()
    assert approve_and_apply(client, fx, q["id"]).status_code == 200
    assert branch_head(client, fx, repo["id"], "main") == later["id"]

    # And *now* somebody opens one over the older commit. Proposed after the
    # landing, so it is not stale - it asks for code the branch already has.
    p = propose_commit(client, fx, repo["id"], first["id"], summary="the older one").json()
    assert p["landing"] == "landed", p["landing"]
    assert approve_and_apply(client, fx, p["id"]).status_code == 200
    # The branch stayed where it was: the proposal had nothing to add to it.
    assert branch_head(client, fx, repo["id"], "main") == later["id"]


def test_a_diverged_branch_is_a_blocker_before_the_button_not_an_error_after(
    client: TestClient, fx: Fixture, repo: dict, source: str, gated
) -> None:
    """Every refusal an apply can make is knowable without applying.

    Reported in the same list as every other reason, so the surface renders it
    without knowing it is special - and the publish never happens, rather than
    happening and being rolled back.
    """
    out = f"diverged_{uuid.uuid4().hex[:8]}"
    theirs_out = f"theirs_{uuid.uuid4().hex[:8]}"
    commit(client, fx, repo["id"], {"README.md": "# transforms\n"})
    sandbox(client, fx, repo["id"], "side")
    made = commit(client, fx, repo["id"],
                  {"README.md": "# transforms\n", "src/t.sql": sql(out, source)},
                  branch="side")
    p = propose_commit(client, fx, repo["id"], made["id"]).json()
    assert p["landing"] == "fast_forward"

    # Somebody else's sandbox lands, and now a pointer cannot express both
    # histories. Two branches from one base is the shape that produces this in
    # practice - and since §284 it is the only shape that can, because `main`
    # takes no direct commits while review is required.
    sandbox(client, fx, repo["id"], "theirs")
    moved = commit(client, fx, repo["id"],
                   {"README.md": "# transforms\n",
                    "src/other.sql": sql(theirs_out, source)},
                   branch="theirs")
    other = propose_commit(client, fx, repo["id"], moved["id"], summary="theirs").json()
    assert approve_and_apply(client, fx, other["id"]).status_code == 200
    detail = client.get(f"{cbase(fx)}/proposals/{p['id']}", headers=hdr(fx.viewer_sub)).json()
    assert detail["landing"] == "diverged"
    assert any("has moved on since this was proposed" in b for b in detail["blockers"]), \
        detail["blockers"]

    r = approve_and_apply(client, fx, p["id"])
    assert r.status_code == 422, r.text
    assert "moved on" in r.json()["detail"]
    # And nothing was published on the way to that refusal.
    models = client.get(f"{pbase(fx)}/models", headers=hdr(fx.viewer_sub)).json()
    assert out not in [m["name"] for m in models]
    assert branch_head(client, fx, repo["id"], "main") == moved["id"]


def test_a_typed_changes_proposal_lands_on_no_branch_and_says_so(
    client: TestClient, fx: Fixture, source: str
) -> None:
    """The one shape that names no repository (db 0039). `null` rather than a
    guessed branch: a proposal that reported landing on `main` when it touches
    no repository would be describing something that cannot happen."""
    model = make_model(client, fx, name=f"typed_{uuid.uuid4().hex[:8]}", code="SELECT 1")
    r = client.post(
        f"{cbase(fx)}/proposals", headers=hdr(fx.editor_sub),
        json={"summary": "A typed change",
              "changes": [{"model_id": model["id"], "code": "SELECT 2"}]},
    )
    assert r.status_code == 201, r.text
    assert r.json()["lands_on"] is None
    assert r.json()["landing"] is None


def test_applying_creates_the_default_branch_when_nothing_ever_made_it(
    client: TestClient, fx: Fixture, repo: dict, source: str, gated
) -> None:
    """**A repository whose commits all went somewhere else reads as empty.**

    `read_tree` falls back to the default branch and finds no row, which is the
    same answer a repository nobody has committed to gives - the shape
    `delete_branch` refuses to create. Applying is exactly the moment to put a
    row there: it is the same act by which a first commit creates the branch it
    is on, and leaving the repository opening on nothing after publishing its
    code would be the worse of the two.
    """
    out = f"nomain_{uuid.uuid4().hex[:8]}"
    made = commit(client, fx, repo["id"], {"src/t.sql": sql(out, source)}, branch="only")
    assert branch_head(client, fx, repo["id"], "main") is None

    p = propose_commit(client, fx, repo["id"], made["id"]).json()
    assert p["lands_on"] == "main"
    assert p["landing"] == "fast_forward"

    assert approve_and_apply(client, fx, p["id"]).status_code == 200
    assert branch_head(client, fx, repo["id"], "main") == made["id"]
    tree = client.get(f"{rbase(fx)}/{repo['id']}/tree", headers=hdr(fx.viewer_sub)).json()
    assert "src/t.sql" in tree["files"], sorted(tree["files"])


def test_a_repository_whose_default_branch_is_not_main_lands_on_its_own(
    client: TestClient, fx: Fixture, source: str, gated
) -> None:
    """**§212, and it took a mutant to find it.**

    Every repository in every test here is created with the default default
    branch, so `default_branch()` returning the literal `"main"` passed all of
    them - a fixture that never crosses the boundary cannot see the boundary,
    and here the boundary is a repository that named its own trunk.
    """
    r = client.post(rbase(fx), headers=hdr(fx.editor_sub),
                    json={"name": f"Trunked {uuid.uuid4().hex[:8]}",
                          "default_branch": "trunk"})
    assert r.status_code == 201, r.text
    repo = r.json()
    assert repo["default_branch"] == "trunk"

    out = f"trunk_{uuid.uuid4().hex[:8]}"
    base = commit(client, fx, repo["id"], {"README.md": "# t\n"}, branch="trunk")
    sandbox(client, fx, repo["id"], "work", frm="trunk")
    made = commit(client, fx, repo["id"],
                  {"README.md": "# t\n", "src/t.sql": sql(out, source)}, branch="work")

    p = propose_commit(client, fx, repo["id"], made["id"]).json()
    assert p["lands_on"] == "trunk", p["lands_on"]
    assert p["landing"] == "fast_forward"

    assert branch_head(client, fx, repo["id"], "trunk") == base["id"]
    assert approve_and_apply(client, fx, p["id"]).status_code == 200
    assert branch_head(client, fx, repo["id"], "trunk") == made["id"]
    # And `main` was never invented on the way: a repository that named its own
    # trunk does not acquire a second one.
    assert branch_head(client, fx, repo["id"], "main") is None


# ---- protected branches (§284; code-repositories.md §2.1, p.12) ---------------
# "To edit code in your repository, you must work in a sandbox branch -
# protected branches cannot be directly edited."
#
# **Protection is the review gate, not a second switch.** A repository's default
# branch is protected exactly when its project requires review. §278 is the
# reason: a governance setting with one control nobody could find is how the
# review gate nearly disappeared, and two controls for a rule that means the
# same thing is how they start to disagree.
def try_commit(client: TestClient, fx: Fixture, repo_id: str, files: dict,
               *, branch: str = "main"):
    return client.post(
        f"{rbase(fx)}/{repo_id}/commits", headers=hdr(fx.editor_sub),
        json={"branch": branch, "files": files, "message": ""},
    )


def test_a_gated_project_refuses_a_direct_commit_to_the_default_branch(
    client: TestClient, fx: Fixture, repo: dict, source: str, gated
) -> None:
    """**The refusal, and it names the way through.**

    A rule that only says no teaches people that the product is broken. This
    one names the branch, says why it is protected, and describes the path -
    including the part §283 built, which is that applying the pull request is
    what moves the branch.
    """
    out = f"prot_{uuid.uuid4().hex[:8]}"
    commit(client, fx, repo["id"], {"src/t.sql": sql(out, source)})

    r = try_commit(client, fx, repo["id"], {"src/t.sql": sql(out, source, body="SELECT id FROM raw")})
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert "'main' is protected" in detail, detail
    assert "requires code review" in detail
    assert "sandbox branch" in detail
    assert "pull request" in detail


def test_the_first_commit_in_a_repository_is_not_an_edit(
    client: TestClient, fx: Fixture, repo: dict, source: str, gated
) -> None:
    """**A branch with no commits is not protected**, because there is nothing
    to edit yet.

    Creating a repository and putting its first commit on the default branch is
    how a repository starts - it is what Foundry does for you from a template.
    Refusing it would leave a new repository in a gated project with no way in
    at all short of a branch created from nothing, which is a wall rather than
    a rule.
    """
    out = f"firstc_{uuid.uuid4().hex[:8]}"
    r = try_commit(client, fx, repo["id"], {"src/t.sql": sql(out, source)})
    assert r.status_code == 201, r.text
    # And the second one is refused, so the exception is about emptiness rather
    # than about the branch.
    assert try_commit(client, fx, repo["id"], {"src/t.sql": sql(out, source)}).status_code == 409


def test_an_ungated_project_still_commits_to_its_default_branch(
    client: TestClient, fx: Fixture, repo: dict, source: str
) -> None:
    """No `gated` fixture: protection is the gate, so with the gate off there
    is nothing protecting anything. A rule that fired regardless would be a
    second switch, and the one the Settings tab shows would stop describing
    what happens."""
    out = f"ungated_{uuid.uuid4().hex[:8]}"
    commit(client, fx, repo["id"], {"src/t.sql": sql(out, source)})
    assert try_commit(
        client, fx, repo["id"],
        {"src/t.sql": sql(out, source, body="SELECT id FROM raw")},
    ).status_code == 201


def test_a_sandbox_branch_takes_the_commit_the_default_branch_refused(
    client: TestClient, fx: Fixture, repo: dict, source: str, gated
) -> None:
    """The whole route, end to end: refused on `main`, accepted on a sandbox,
    and landed by the review."""
    out = f"route_{uuid.uuid4().hex[:8]}"
    first = commit(client, fx, repo["id"], {"src/t.sql": sql(out, source)})
    assert try_commit(client, fx, repo["id"], {"src/t.sql": sql(out, source)}).status_code == 409

    sandbox(client, fx, repo["id"], "work")
    made = commit(client, fx, repo["id"],
                  {"src/t.sql": sql(out, source, body="SELECT id FROM raw")},
                  branch="work")
    assert branch_head(client, fx, repo["id"], "main") == first["id"]

    p = propose_commit(client, fx, repo["id"], made["id"]).json()
    assert approve_and_apply(client, fx, p["id"]).status_code == 200
    assert branch_head(client, fx, repo["id"], "main") == made["id"]


def test_adoption_obeys_the_same_rule_as_a_commit(
    client: TestClient, fx: Fixture, repo: dict, source: str, gated
) -> None:
    """**Two paths write commits, and a gate on one of them is a gate on one
    screen.**

    Adoption (§274) turns a transform into a file by committing it, so it is an
    edit to the repository and follows the branch rule like any other. The
    check lives in `commit` rather than in the route for exactly this reason.
    """
    out = f"adopt_{uuid.uuid4().hex[:8]}"
    commit(client, fx, repo["id"], {"src/t.sql": sql(out, source)})
    model = make_model(client, fx, name=f"adopted_{uuid.uuid4().hex[:8]}", code="SELECT 1")

    refused = adopt(client, fx, model["id"], repo["id"])
    assert refused.status_code == 409, refused.text
    assert "protected" in refused.json()["detail"]

    sandbox(client, fx, repo["id"], "adopting")
    allowed = adopt(client, fx, model["id"], repo["id"], branch="adopting")
    assert allowed.status_code == 200, allowed.text


# ---- checks on a branch (§285; code-repositories.md §5, p.19) -----------------
# "In the Checks tab, you can view a summary of running and completed checks on
# each branch. Use the dropdown branch menu to select a different branch."
def branch_checks(client: TestClient, fx: Fixture, repo_id: str, branch: str | None = None):
    q = f"?branch={branch}" if branch else ""
    return client.get(f"{rbase(fx)}/{repo_id}/checks{q}", headers=hdr(fx.viewer_sub))


def run_checks(client: TestClient, fx: Fixture, proposal_id: str):
    return client.post(f"{cbase(fx)}/proposals/{proposal_id}/checks",
                       headers=hdr(fx.editor_sub))


def test_a_branchs_checks_are_the_checks_of_the_proposals_made_on_it(
    client: TestClient, fx: Fixture, repo: dict, source: str, gated
) -> None:
    """**The divergence, and the reason it is not a fudge.**

    Foundry runs checks on a commit; ours run on a proposal, because the schema
    check asks what the code would do to the project's datasets and a commit
    nobody has proposed has not said which change it means to make. Since §284
    a sandbox is where work happens and a proposal is how it lands, so every
    commit that matters is on its way to being one.
    """
    out = f"chk_{uuid.uuid4().hex[:8]}"
    commit(client, fx, repo["id"], {"README.md": "# t\n"})
    sandbox(client, fx, repo["id"], "work")
    made = commit(client, fx, repo["id"],
                  {"README.md": "# t\n", "src/t.sql": sql(out, source)}, branch="work")
    p = propose_commit(client, fx, repo["id"], made["id"], summary="Add a transform").json()
    assert run_checks(client, fx, p["id"]).status_code == 200

    seen = branch_checks(client, fx, repo["id"], "work")
    assert seen.status_code == 200, seen.text
    body = seen.json()
    assert body["branch"] == "work"
    assert body["head_commit_id"] == made["id"]
    names = {c["name"] for c in body["checks"]}
    assert names == {"transform_runs", "schema_compatible"}, names
    # Each carries the change it is about: a check without one is a verdict on
    # nothing.
    for c in body["checks"]:
        assert c["proposal_id"] == p["id"]
        assert c["proposal_summary"] == "Add a transform"
        assert c["proposal_state"] == "open"
        assert c["source_commit_id"] == made["id"]


def test_the_default_branch_is_what_you_get_without_asking(
    client: TestClient, fx: Fixture, repo: dict, source: str, gated
) -> None:
    out = f"dflt_{uuid.uuid4().hex[:8]}"
    made = commit(client, fx, repo["id"], {"src/t.sql": sql(out, source)})
    p = propose_commit(client, fx, repo["id"], made["id"]).json()
    run_checks(client, fx, p["id"])

    body = branch_checks(client, fx, repo["id"]).json()
    assert body["branch"] == "main"
    assert len(body["checks"]) == 2, body["checks"]


def test_a_branch_shows_the_checks_of_commits_it_has_moved_past(
    client: TestClient, fx: Fixture, repo: dict, source: str, gated
) -> None:
    """**The whole history, not just the head.**

    A proposal is made over the commit that existed when somebody opened it,
    and the branch has usually moved on since. Showing only the head's checks
    would empty the tab the moment anybody committed again - which is exactly
    when somebody would go looking at it.
    """
    out = f"hist_{uuid.uuid4().hex[:8]}"
    commit(client, fx, repo["id"], {"README.md": "# t\n"})
    sandbox(client, fx, repo["id"], "work")
    first = commit(client, fx, repo["id"],
                   {"README.md": "# t\n", "src/t.sql": sql(out, source)}, branch="work")
    p = propose_commit(client, fx, repo["id"], first["id"]).json()
    run_checks(client, fx, p["id"])

    commit(client, fx, repo["id"],
           {"README.md": "# t\n", "src/t.sql": sql(out, source), "docs/x.md": "# x\n"},
           branch="work")

    body = branch_checks(client, fx, repo["id"], "work").json()
    assert len(body["checks"]) == 2, body["checks"]
    assert all(c["source_commit_id"] == first["id"] for c in body["checks"])


def test_another_branchs_checks_do_not_appear_here(
    client: TestClient, fx: Fixture, repo: dict, source: str, gated
) -> None:
    """Two sandboxes from one base. A tab that showed both would be answering a
    different question from the one its branch selector asks."""
    commit(client, fx, repo["id"], {"README.md": "# t\n"})
    sandbox(client, fx, repo["id"], "mine")
    sandbox(client, fx, repo["id"], "theirs")
    mine = commit(client, fx, repo["id"],
                  {"README.md": "# t\n", "src/a.sql": sql(f"a_{uuid.uuid4().hex[:6]}", source)},
                  branch="mine")
    theirs = commit(client, fx, repo["id"],
                    {"README.md": "# t\n", "src/b.sql": sql(f"b_{uuid.uuid4().hex[:6]}", source)},
                    branch="theirs")
    run_checks(client, fx, propose_commit(client, fx, repo["id"], mine["id"]).json()["id"])
    run_checks(client, fx, propose_commit(client, fx, repo["id"], theirs["id"]).json()["id"])

    on_mine = branch_checks(client, fx, repo["id"], "mine").json()["checks"]
    assert on_mine and all(c["source_commit_id"] == mine["id"] for c in on_mine), on_mine
    on_theirs = branch_checks(client, fx, repo["id"], "theirs").json()["checks"]
    assert on_theirs and all(c["source_commit_id"] == theirs["id"] for c in on_theirs)


def test_a_branch_with_no_proposals_has_no_checks_rather_than_an_error(
    client: TestClient, fx: Fixture, repo: dict, source: str, gated
) -> None:
    """Nothing has run yet is a real state, and the tab has to be able to say
    so - "no checks" and "this branch does not exist" are different answers."""
    commit(client, fx, repo["id"], {"src/t.sql": sql(f"q_{uuid.uuid4().hex[:6]}", source)})
    body = branch_checks(client, fx, repo["id"], "main").json()
    assert body["checks"] == []
    assert body["head_commit_id"] is not None

    missing = branch_checks(client, fx, repo["id"], "nope")
    assert missing.status_code == 404, missing.text


def test_a_commit_backed_proposal_refuses_an_edit_to_its_files(
    client: TestClient, fx: Fixture, repo: dict, source: str, gated
) -> None:
    """**Found while looking for a stale check, and it was doing real damage.**

    A commit-backed proposal's files come from the commit (db 0039), so
    `code_proposal_files` rows written by a PATCH are never read - but the write
    still moved `files_updated_at`, which invalidates every approval and
    outdates every comment. A call that changes nothing about the code under
    review and drops the reviews of it is the worst combination available.

    It is also why the Checks tab carries no staleness flag: with this refused,
    a commit-backed proposal's `files_updated_at` never moves at all.
    """
    out = f"immut_{uuid.uuid4().hex[:8]}"
    made = commit(client, fx, repo["id"], {"src/t.sql": sql(out, source)})
    p = propose_commit(client, fx, repo["id"], made["id"]).json()
    models = client.get(f"{pbase(fx)}/models", headers=hdr(fx.viewer_sub)).json()
    if not models:
        pytest.skip("no model to name in a change")

    r = client.patch(f"{cbase(fx)}/proposals/{p['id']}", headers=hdr(fx.editor_sub),
                     json={"changes": [{"model_id": models[0]["id"], "code": "SELECT 1"}]})
    assert r.status_code == 422, r.text
    assert "over a commit" in r.json()["detail"]
    assert "immutable" in r.json()["detail"]

    # The prose still edits, because a reviewer approved code rather than prose.
    renamed = client.patch(f"{cbase(fx)}/proposals/{p['id']}", headers=hdr(fx.editor_sub),
                           json={"summary": "A better title"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["summary"] == "A better title"


def test_a_proposal_cannot_name_a_commit_from_another_repository(
    client: TestClient, fx: Fixture, repo: dict, source: str, gated
) -> None:
    """**The smuggling path the commit branch never had** (§285).

    `_write_files` has always checked that a typed change names a model in this
    project - "so a proposal cannot smuggle in a transform from somewhere
    else". The commit path took two ids from the caller and joined them to
    nothing, so a proposal could name repository A and a commit from repository
    B: the review surface would show one repository's code under another
    repository's name, and applying it would publish it.
    """
    out = f"smug_{uuid.uuid4().hex[:8]}"
    elsewhere = client.post(rbase(fx), headers=hdr(fx.editor_sub),
                            json={"name": f"Other {uuid.uuid4().hex[:8]}"}).json()
    theirs = commit(client, fx, elsewhere["id"], {"src/t.sql": sql(out, source)})

    r = propose_commit(client, fx, repo["id"], theirs["id"])
    assert r.status_code == 422, r.text
    assert "not in that repository" in r.json()["detail"]

    # And the honest version of the same request is accepted.
    assert propose_commit(client, fx, elsewhere["id"], theirs["id"]).status_code == 201


def test_a_commit_backed_proposal_has_to_say_which_repository(
    client: TestClient, fx: Fixture, repo: dict, source: str, gated
) -> None:
    """Refused rather than inferred from the commit. Inferring would make the
    field decorative, and a decorative field is one nothing keeps honest."""
    made = commit(client, fx, repo["id"],
                  {"src/t.sql": sql(f"norepo_{uuid.uuid4().hex[:8]}", source)})
    r = client.post(
        f"{cbase(fx)}/proposals", headers=hdr(fx.editor_sub),
        json={"summary": "No repository named", "source_commit_id": made["id"]},
    )
    assert r.status_code == 422, r.text
    assert "which repository" in r.json()["detail"]


def test_two_repositories_in_one_project_keep_their_checks_apart(
    client: TestClient, fx: Fixture, repo: dict, source: str, gated
) -> None:
    """§212: every checks test until now used one repository, so nothing here
    ever crossed the boundary the query is drawn on."""
    other = client.post(rbase(fx), headers=hdr(fx.editor_sub),
                        json={"name": f"Second {uuid.uuid4().hex[:8]}"}).json()
    mine = commit(client, fx, repo["id"],
                  {"src/a.sql": sql(f"m_{uuid.uuid4().hex[:6]}", source)})
    theirs = commit(client, fx, other["id"],
                    {"src/b.sql": sql(f"t_{uuid.uuid4().hex[:6]}", source)})
    run_checks(client, fx, propose_commit(client, fx, repo["id"], mine["id"]).json()["id"])
    run_checks(client, fx, propose_commit(client, fx, other["id"], theirs["id"]).json()["id"])

    here = branch_checks(client, fx, repo["id"]).json()["checks"]
    assert here and all(c["source_commit_id"] == mine["id"] for c in here), here
    there = branch_checks(client, fx, other["id"]).json()["checks"]
    assert there and all(c["source_commit_id"] == theirs["id"] for c in there), there


def test_a_proposal_cannot_name_a_repository_in_another_project(
    client: TestClient, fx: Fixture, source: str, gated
) -> None:
    """**The third leg of the join, and it took a mutant to reach.**

    Every repository in every test here lives in the one fixture project, so
    `r.project_id = :pid` was a condition nothing ever crossed - §212 again. It
    is reachable in the product: somebody in two projects of one workspace can
    read both, so a proposal opened in this project could name the other's
    repository and its commit, and the two ids would agree with each other
    while agreeing with nothing here.
    """
    import psycopg

    tag = uuid.uuid4().hex[:8]
    with psycopg.connect(os.environ["TEST_ADMIN_DSN"], autocommit=True) as conn:
        elsewhere = conn.execute(
            """INSERT INTO projects (workspace_id, name, slug, created_by)
               VALUES (%s,%s,%s,%s) RETURNING id""",
            (fx.workspace, f"Neighbour {tag}", f"neighbour-{tag}", fx.owner),
        ).fetchone()[0]

    other_base = f"/api/workspaces/{fx.workspace}/projects/{elsewhere}"
    repo = client.post(f"{other_base}/repositories", headers=hdr(fx.editor_sub),
                       json={"name": f"Theirs {tag}"})
    assert repo.status_code == 201, repo.text
    made = client.post(
        f"{other_base}/repositories/{repo.json()['id']}/commits",
        headers=hdr(fx.editor_sub),
        json={"branch": "main", "files": {"src/t.sql": "SELECT 1\n"}, "message": ""},
    )
    assert made.status_code == 201, made.text

    # The two ids agree with each other, and with nothing in this project.
    r = client.post(
        f"{cbase(fx)}/proposals", headers=hdr(fx.editor_sub),
        json={"summary": "Somebody else's repository",
              "source_repo_id": repo.json()["id"],
              "source_commit_id": made.json()["id"]},
    )
    assert r.status_code == 422, r.text
    assert "not in this project" in r.json()["detail"]
