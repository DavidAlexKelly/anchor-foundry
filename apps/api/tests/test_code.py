"""The Code pillar's repository surface (ROADMAP Code item 2, migration 0030).

`docs/decisions/0001-where-code-lives.md` decided there is no second store:
the repository *is* the project's models and the history *is*
`model_versions`. So what these tests protect is that the surface stays a
view rather than becoming a parallel system - a change set writes the same
rows a run resolves against, cannot bypass a check the inline editor
enforces, and cannot record an edit that did not happen.
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

ROWS = b"id,val\n1,10\n2,20\n3,30\n"


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("code-storage")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def pbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


def mbase(fx: Fixture) -> str:
    return f"{pbase(fx)}/models"


def cbase(fx: Fixture) -> str:
    return f"{pbase(fx)}/code"


@pytest.fixture(scope="module")
def source(client: TestClient, fx: Fixture) -> str:
    r = client.post(
        f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"Code rows {fx.tag}"},
        files={"file": ("rows.csv", io.BytesIO(ROWS), "text/csv")},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def make_model(client: TestClient, fx: Fixture, source: str, name: str, code: str) -> str:
    r = client.post(
        mbase(fx), headers=hdr(fx.editor_sub),
        json={"name": name, "code": code,
              "inputs": [{"dataset_id": source, "input_alias": "raw"}]},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture()
def pair(client: TestClient, fx: Fixture, source: str) -> dict[str, str]:
    tag = uuid.uuid4().hex[:6]
    return {
        "a": make_model(client, fx, source, f"Daily orders {tag}", "SELECT id FROM raw"),
        "b": make_model(client, fx, source, f"Weekly rollup {tag}", "SELECT val FROM raw"),
    }


# ---- the tree ---------------------------------------------------------------
def test_the_tree_gives_every_transform_a_stable_path(
    client: TestClient, fx: Fixture, pair: dict[str, str]
) -> None:
    """A repository has files. A path that changed between two reads would
    not be one, so it is derived from the name and the language and nothing
    else."""
    r = client.get(f"{cbase(fx)}/tree", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    entries = {e["id"]: e for e in r.json()}
    assert entries[pair["a"]]["path"].startswith("models/daily_orders_")
    assert entries[pair["a"]]["path"].endswith(".sql")
    assert entries[pair["a"]]["current_version"] == 1
    again = client.get(f"{cbase(fx)}/tree", headers=hdr(fx.viewer_sub)).json()
    assert [e["path"] for e in again] == [e["path"] for e in r.json()]


def test_colliding_names_both_take_a_suffix(
    client: TestClient, fx: Fixture, source: str
) -> None:
    """"Daily orders" and "Daily Orders!" collapse to the same stem. Both
    sides take the id suffix, not just the second one - a path that depended
    on creation order would move under an unrelated model's rename."""
    tag = uuid.uuid4().hex[:6]
    first = make_model(client, fx, source, f"Clash {tag}", "SELECT 1 AS x")
    second = make_model(client, fx, source, f"clash  {tag}!", "SELECT 2 AS x")
    entries = {e["id"]: e for e in client.get(
        f"{cbase(fx)}/tree", headers=hdr(fx.viewer_sub)).json()}
    assert entries[first]["path"] != entries[second]["path"]
    assert first[:8] in entries[first]["path"]
    assert second[:8] in entries[second]["path"]


# ---- reading a file ---------------------------------------------------------
def test_reading_an_old_version_returns_the_inputs_it_was_saved_with(
    client: TestClient, fx: Fixture, pair: dict[str, str]
) -> None:
    """Code without its input bindings is not a definition: `FROM raw` means
    nothing without knowing what `raw` was bound to (migration 0024)."""
    client.patch(f"{mbase(fx)}/{pair['a']}", headers=hdr(fx.editor_sub),
                 json={"code": "SELECT id, val FROM raw"})
    head = client.get(f"{cbase(fx)}/files/{pair['a']}", headers=hdr(fx.viewer_sub)).json()
    assert head["code"] == "SELECT id, val FROM raw"
    assert head["version_number"] == 2

    old = client.get(f"{cbase(fx)}/files/{pair['a']}?version=1",
                     headers=hdr(fx.viewer_sub)).json()
    assert old["code"] == "SELECT id FROM raw"
    assert old["inputs"][0]["input_alias"] == "raw"


def test_a_missing_version_is_404(client: TestClient, fx: Fixture, pair: dict[str, str]) -> None:
    r = client.get(f"{cbase(fx)}/files/{pair['a']}?version=99", headers=hdr(fx.viewer_sub))
    assert r.status_code == 404


# ---- diffs ------------------------------------------------------------------
def test_a_diff_is_computed_between_two_versions(
    client: TestClient, fx: Fixture, pair: dict[str, str]
) -> None:
    client.patch(f"{mbase(fx)}/{pair['a']}", headers=hdr(fx.editor_sub),
                 json={"code": "SELECT id, val FROM raw"})
    r = client.get(f"{cbase(fx)}/files/{pair['a']}/diff?from_version=1&to_version=2",
                   headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    body = r.json()
    assert "-SELECT id FROM raw" in body["diff"]
    assert "+SELECT id, val FROM raw" in body["diff"]
    assert (body["added"], body["removed"]) == (1, 1)


def test_a_diff_with_no_from_version_shows_the_file_being_added(
    client: TestClient, fx: Fixture, pair: dict[str, str]
) -> None:
    """"Before version 1" is a real thing to ask for, and is not the same as
    diffing v1 against itself."""
    body = client.get(f"{cbase(fx)}/files/{pair['a']}/diff?to_version=1",
                      headers=hdr(fx.viewer_sub)).json()
    assert "/dev/null" in body["diff"]
    assert body["removed"] == 0 and body["added"] == 1


# ---- change sets ------------------------------------------------------------
def test_a_change_set_groups_one_edit_across_several_transforms(
    client: TestClient, fx: Fixture, pair: dict[str, str]
) -> None:
    """The one thing this pillar genuinely adds: before it, a save wrote one
    version per model and "these changed together, for one reason" could not
    be said."""
    r = client.post(
        f"{cbase(fx)}/change-sets", headers=hdr(fx.editor_sub),
        json={
            "summary": "Rename the value column everywhere",
            "description": "One rename, two transforms.",
            "changes": [
                {"model_id": pair["a"], "code": "SELECT id AS key FROM raw"},
                {"model_id": pair["b"], "code": "SELECT val AS amount FROM raw"},
            ],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["summary"] == "Rename the value column everywhere"
    assert {m["model_id"] for m in body["models"]} == {pair["a"], pair["b"]}
    assert all(m["version_number"] == 2 for m in body["models"])
    assert all(m["previous_version"] == 1 for m in body["models"])


def test_a_change_set_writes_the_same_rows_a_run_resolves_against(
    client: TestClient, fx: Fixture, pair: dict[str, str]
) -> None:
    """The whole point of the item 1 decision: Code is not a second store, so
    a version written here is visible to Models' own history endpoint and is
    what a run would be stamped with."""
    client.post(
        f"{cbase(fx)}/change-sets", headers=hdr(fx.editor_sub),
        json={"summary": "Tighten the projection",
              "changes": [{"model_id": pair["a"], "code": "SELECT id FROM raw WHERE id > 1"}]},
    )
    history = client.get(f"{mbase(fx)}/{pair['a']}/versions", headers=hdr(fx.viewer_sub)).json()
    assert history[0]["version_number"] == 2
    assert history[0]["code"] == "SELECT id FROM raw WHERE id > 1"


def test_a_change_set_cannot_bypass_a_check_the_inline_editor_enforces(
    client: TestClient, fx: Fixture, pair: dict[str, str], source: str
) -> None:
    """Every file goes through models.update, so cycle refusal (Models item 7)
    applies here too. A second authoring surface with weaker validation is a
    bug with a UI in front of it."""
    # A model's output dataset only exists once it has run, so run it first -
    # then feed its own output back into it, which is a self-cycle.
    run = client.post(f"{mbase(fx)}/{pair['a']}/run", headers=hdr(fx.editor_sub))
    assert run.status_code == 200 and run.json()["ok"], run.text
    a_out = run.json()["output_dataset"]["id"]
    r = client.post(
        f"{cbase(fx)}/change-sets", headers=hdr(fx.editor_sub),
        json={"summary": "Introduce a cycle",
              "changes": [{
                  "model_id": pair["a"],
                  "code": "SELECT id FROM raw",
                  "inputs": [{"dataset_id": a_out, "input_alias": "raw"}],
              }]},
    )
    assert r.status_code == 422, r.text
    # And nothing was recorded: the change set rolls back with the edit.
    log = client.get(f"{cbase(fx)}/history", headers=hdr(fx.viewer_sub)).json()
    assert all(e["summary"] != "Introduce a cycle" for e in log)


def test_a_change_set_that_changes_nothing_is_refused(
    client: TestClient, fx: Fixture, pair: dict[str, str]
) -> None:
    """A commit message attached to nothing is a lie about history rather
    than an empty entry in it."""
    current = client.get(f"{cbase(fx)}/files/{pair['a']}", headers=hdr(fx.viewer_sub)).json()
    r = client.post(
        f"{cbase(fx)}/change-sets", headers=hdr(fx.editor_sub),
        json={"summary": "No-op", "changes": [
            {"model_id": pair["a"], "code": current["code"]}]},
    )
    assert r.status_code == 422, r.text
    assert "changed" in r.json()["detail"]


def test_the_same_model_twice_in_one_change_set_is_refused(
    client: TestClient, fx: Fixture, pair: dict[str, str]
) -> None:
    r = client.post(
        f"{cbase(fx)}/change-sets", headers=hdr(fx.editor_sub),
        json={"summary": "Twice", "changes": [
            {"model_id": pair["a"], "code": "SELECT 1 AS x"},
            {"model_id": pair["a"], "code": "SELECT 2 AS x"},
        ]},
    )
    assert r.status_code == 422, r.text


def test_an_unlabelled_change_set_is_refused(
    client: TestClient, fx: Fixture, pair: dict[str, str]
) -> None:
    """A change set exists to say *why* several edits belong together."""
    r = client.post(
        f"{cbase(fx)}/change-sets", headers=hdr(fx.editor_sub),
        json={"summary": "", "changes": [{"model_id": pair["a"], "code": "SELECT 9 AS x"}]},
    )
    assert r.status_code == 422


# ---- history ----------------------------------------------------------------
def test_history_shows_change_sets_and_standalone_saves_in_one_timeline(
    client: TestClient, fx: Fixture, pair: dict[str, str]
) -> None:
    """Two kinds of entry, because that is the truth about how the code gets
    edited: the inline Models editor writes a version with no change set, and
    inventing a synthetic one for it would claim an intention nobody
    expressed (migration 0030)."""
    client.patch(f"{mbase(fx)}/{pair['b']}", headers=hdr(fx.editor_sub),
                 json={"code": "SELECT val FROM raw WHERE val > 10"})
    summary = f"Grouped edit {uuid.uuid4().hex[:6]}"
    client.post(
        f"{cbase(fx)}/change-sets", headers=hdr(fx.editor_sub),
        json={"summary": summary,
              "changes": [{"model_id": pair["a"], "code": "SELECT id FROM raw LIMIT 2"}]},
    )
    log = client.get(f"{cbase(fx)}/history", headers=hdr(fx.viewer_sub)).json()
    kinds = {e["kind"] for e in log}
    assert kinds == {"change_set", "version"}
    grouped = next(e for e in log if e["summary"] == summary)
    assert grouped["kind"] == "change_set" and grouped["model_count"] == 1
    standalone = next(e for e in log if e["kind"] == "version" and "Weekly rollup" in e["summary"])
    assert standalone["path"].endswith(".sql")


def test_a_restore_reads_as_a_revert_in_the_log(
    client: TestClient, fx: Fixture, pair: dict[str, str]
) -> None:
    client.patch(f"{mbase(fx)}/{pair['a']}", headers=hdr(fx.editor_sub),
                 json={"code": "SELECT id FROM raw WHERE id > 2"})
    r = client.post(f"{mbase(fx)}/{pair['a']}/versions/1/restore", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    log = client.get(f"{cbase(fx)}/history", headers=hdr(fx.viewer_sub)).json()
    assert any("Reverted" in e["summary"] and "v1" in e["summary"] for e in log)


# ---- permissions ------------------------------------------------------------
def test_reading_is_viewer_level_and_writing_is_editor_level(
    client: TestClient, fx: Fixture, pair: dict[str, str]
) -> None:
    """The floors match Models exactly. A second authoring surface with a
    different floor is a permission bug waiting for somebody to notice which
    door was unlocked."""
    assert client.get(f"{cbase(fx)}/tree", headers=hdr(fx.viewer_sub)).status_code == 200
    r = client.post(
        f"{cbase(fx)}/change-sets", headers=hdr(fx.viewer_sub),
        json={"summary": "Nope", "changes": [{"model_id": pair["a"], "code": "SELECT 1 AS x"}]},
    )
    assert r.status_code == 403
    assert client.get(f"{cbase(fx)}/tree", headers=hdr(fx.outsider_sub)).status_code == 404


def test_change_sets_are_audited(client: TestClient, fx: Fixture, pair: dict[str, str]) -> None:
    client.post(
        f"{cbase(fx)}/change-sets", headers=hdr(fx.editor_sub),
        json={"summary": "Audited edit",
              "changes": [{"model_id": pair["b"], "code": "SELECT val FROM raw LIMIT 1"}]},
    )
    r = client.get("/api/org/audit?limit=200", headers=hdr(fx.admin_sub))
    assert "code_change_set.create" in {e["action"] for e in r.json()}
