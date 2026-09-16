"""Which datasets a proposal changes (§364; `code-repositories` p.52-55).

> "The Impact analysis tab provides information on datasets affected by the
>  pull request. By default, it will only show **directly affected** datasets…
>  In Java transforms, datasets are considered directly affected if their
>  source file is changed by the pull request." (p.53)

`code-repositories.md` §4.1: "Ours reviews text; Foundry reviews the
consequences of text."

Every assertion here is about a list that has to be **exactly as long as the
diff**: a file with no dataset behind it is a different answer from a file with
one, and dropping it would leave a reader to work out which parts of the change
were silently not considered.
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
        LocalStorageGateway(str(tmp_path_factory.mktemp("impact-storage")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def pbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


def cbase(fx: Fixture) -> str:
    return f"{pbase(fx)}/code"


@pytest.fixture(scope="module")
def source(client: TestClient, fx: Fixture) -> str:
    r = client.post(
        f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"Impact rows {fx.tag}"},
        files={"file": ("rows.csv", io.BytesIO(ROWS), "text/csv")},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def make_model(client: TestClient, fx: Fixture, source: str, code: str = "SELECT id FROM raw") -> str:
    r = client.post(
        f"{pbase(fx)}/models", headers=hdr(fx.editor_sub),
        json={"name": f"Impact {uuid.uuid4().hex[:6]}", "code": code,
              "inputs": [{"dataset_id": source, "input_alias": "raw"}]},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def run(client: TestClient, fx: Fixture, model_id: str) -> dict:
    r = client.post(f"{pbase(fx)}/models/{model_id}/run", headers=hdr(fx.editor_sub))
    assert r.status_code in (200, 201), r.text
    return r.json()


def propose(client: TestClient, fx: Fixture, changes: list[dict], sub: str | None = None) -> dict:
    r = client.post(
        f"{cbase(fx)}/proposals", headers=hdr(sub or fx.editor_sub),
        json={"summary": f"Edit {uuid.uuid4().hex[:6]}", "changes": changes},
    )
    assert r.status_code == 201, r.text
    return r.json()


def impact(client: TestClient, fx: Fixture, proposal_id: str, sub: str | None = None):
    return client.get(
        f"{cbase(fx)}/proposals/{proposal_id}/impact", headers=hdr(sub or fx.viewer_sub)
    )


def test_a_proposal_names_the_dataset_its_transform_produces(
    client: TestClient, fx: Fixture, source: str
) -> None:
    """p.53's Java rule, which is the one that translates: a dataset is
    directly affected if the file that produces it is changed."""
    model_id = make_model(client, fx, source)
    output = run(client, fx, model_id)["output_dataset"]

    proposal = propose(client, fx, [{"model_id": model_id, "code": "SELECT val FROM raw"}])
    r = impact(client, fx, proposal["id"])
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["state"] == "affected"
    assert rows[0]["model_id"] == model_id
    assert rows[0]["dataset"]["id"] == output["id"]
    assert rows[0]["dataset"]["name"] == output["name"]


def test_a_transform_that_has_never_run_has_no_dataset_to_affect(
    client: TestClient, fx: Fixture, source: str
) -> None:
    """**A different answer from "nothing is affected".** A proposal against a
    transform nobody has built yet changes something real; there is simply no
    dataset to compare against, and saying so is what stops a reader reading an
    empty list as a safe change."""
    model_id = make_model(client, fx, source)
    proposal = propose(client, fx, [{"model_id": model_id, "code": "SELECT val FROM raw"}])

    rows = impact(client, fx, proposal["id"]).json()
    assert len(rows) == 1
    assert rows[0]["state"] == "never_built"
    assert rows[0]["model_id"] == model_id
    assert rows[0]["dataset"] is None
    # Named, because "one of your transforms has no dataset" is not an answer
    # on a proposal that changes several — and the row that would have carried
    # the name is the one that is not there, so it comes from the file entry.
    listed = client.get(
        f"{pbase(fx)}/models/{model_id}", headers=hdr(fx.viewer_sub)
    ).json()["name"]
    assert rows[0]["model_name"] == listed


def test_the_list_is_as_long_as_the_diff(
    client: TestClient, fx: Fixture, source: str
) -> None:
    """One row per file, in both states at once — the arrangement that tells a
    partial answer from a complete one. A build that returned only the datasets
    would look right until somebody counted."""
    built = make_model(client, fx, source)
    run(client, fx, built)
    unbuilt = make_model(client, fx, source)

    proposal = propose(client, fx, [
        {"model_id": built, "code": "SELECT val FROM raw"},
        {"model_id": unbuilt, "code": "SELECT val FROM raw"},
    ])
    rows = impact(client, fx, proposal["id"]).json()
    assert len(rows) == 2, rows
    by_model = {r["model_id"]: r for r in rows}
    assert by_model[built]["state"] == "affected"
    assert by_model[unbuilt]["state"] == "never_built"


def test_the_dataset_is_named_as_itself_and_not_as_its_transform(
    client: TestClient, fx: Fixture, source: str
) -> None:
    """**A fixture that can tell them apart.** A model's first run names its
    output dataset after the model (`record_output`), so in the ordinary case
    the two strings are equal and a build that printed the model's name where
    the dataset's belongs would look right everywhere. Renamed here, because
    the reviewer is being told which *dataset* changes."""
    model_id = make_model(client, fx, source)
    output = run(client, fx, model_id)["output_dataset"]
    renamed = f"Ledger {uuid.uuid4().hex[:6]}"
    r = client.patch(
        f"{pbase(fx)}/datasets/{output['id']}", headers=hdr(fx.editor_sub),
        json={"name": renamed},
    )
    assert r.status_code == 200, r.text

    proposal = propose(client, fx, [{"model_id": model_id, "code": "SELECT val FROM raw"}])
    rows = impact(client, fx, proposal["id"]).json()
    assert len(rows) == 1
    assert rows[0]["dataset"]["name"] == renamed
    assert rows[0]["model_name"] != renamed, "and the model still has its own name"


def test_the_dataset_reported_is_the_one_that_transform_produces(
    client: TestClient, fx: Fixture, source: str
) -> None:
    """Two transforms with two outputs: a build that joined them by anything
    other than the model would pass a one-model test and put the wrong name in
    front of a reviewer here."""
    first = make_model(client, fx, source)
    second = make_model(client, fx, source)
    first_out = run(client, fx, first)["output_dataset"]
    second_out = run(client, fx, second)["output_dataset"]
    assert first_out["id"] != second_out["id"]

    proposal = propose(client, fx, [
        {"model_id": second, "code": "SELECT val FROM raw"},
    ])
    rows = impact(client, fx, proposal["id"]).json()
    assert len(rows) == 1
    assert rows[0]["dataset"]["id"] == second_out["id"]


def test_an_empty_impact_list_cannot_happen_and_that_is_why_there_is_no_empty_state(
    client: TestClient, fx: Fixture, source: str
) -> None:
    """**Measured rather than designed around.** A reviewer might reasonably
    ask what an impact tab shows for a proposal that changes nothing — and the
    answer is that there is no such proposal: removing the last file is refused
    with "a proposal needs at least one file".

    So the list is never empty, and the surface has no empty state, which is a
    decision rather than an omission (§213: a state that cannot be reached does
    not get a control, or a test that pretends to reach it).
    """
    model_id = make_model(client, fx, source)
    run(client, fx, model_id)
    proposal = propose(client, fx, [{"model_id": model_id, "code": "SELECT val FROM raw"}])

    r = client.patch(
        f"{cbase(fx)}/proposals/{proposal['id']}", headers=hdr(fx.editor_sub),
        json={"changes": []},
    )
    assert r.status_code == 422, r.text
    assert "at least one file" in r.text
    assert len(impact(client, fx, proposal["id"]).json()) == 1, "and the list is untouched"


def test_anybody_who_can_read_the_project_can_read_the_impact(
    client: TestClient, fx: Fixture, source: str
) -> None:
    """A review is something a viewer takes part in, and this reads rather than
    runs."""
    model_id = make_model(client, fx, source)
    run(client, fx, model_id)
    proposal = propose(client, fx, [{"model_id": model_id, "code": "SELECT val FROM raw"}])
    assert impact(client, fx, proposal["id"], sub=fx.viewer_sub).status_code == 200


def test_an_outsider_cannot_read_the_impact(
    client: TestClient, fx: Fixture, source: str
) -> None:
    model_id = make_model(client, fx, source)
    proposal = propose(client, fx, [{"model_id": model_id, "code": "SELECT val FROM raw"}])
    assert impact(client, fx, proposal["id"], sub=fx.outsider_sub).status_code == 404


# ---- a proposal over a commit (db 0039) --------------------------------------

def rbase(fx: Fixture) -> str:
    return f"{pbase(fx)}/repositories"


def test_a_file_that_would_create_a_new_transform_has_no_dataset_yet(
    client: TestClient, fx: Fixture, source: str
) -> None:
    """**The third state, and it needed a commit-backed proposal to reach.**

    db 0039's header says a commit-backed proposal "may create transforms that
    do not exist yet". Such a file has no model, so it has no output dataset —
    and it is not the same answer as a transform that has never run, which does
    have a model. The sweep found this branch unreachable by every test in this
    file, because all of them proposed changes to models that already existed.
    """
    repo = client.post(
        rbase(fx), headers=hdr(fx.editor_sub),
        json={"name": f"Impact repo {uuid.uuid4().hex[:8]}"},
    )
    assert repo.status_code == 201, repo.text
    repo_id = repo.json()["id"]

    # A declaration names its input by *name*, not by id — which is how a
    # transform in a repository refers to a dataset.
    source_name = client.get(
        f"{pbase(fx)}/datasets/{source}", headers=hdr(fx.viewer_sub)
    ).json()["name"]
    output = f"fresh_{uuid.uuid4().hex[:8]}"
    made = client.post(
        f"{rbase(fx)}/{repo_id}/commits", headers=hdr(fx.editor_sub),
        json={"branch": "main", "message": "declare a transform", "files": {
            "src/fresh.sql":
                f"-- output: {output}\n-- input: raw = {source_name}\nSELECT id FROM raw\n",
        }},
    )
    assert made.status_code == 201, made.text

    proposal = client.post(
        f"{cbase(fx)}/proposals", headers=hdr(fx.editor_sub),
        json={"summary": "Publish a new transform", "source_repo_id": repo_id,
              "source_commit_id": made.json()["id"]},
    )
    assert proposal.status_code == 201, proposal.text

    rows = impact(client, fx, proposal.json()["id"]).json()
    assert len(rows) == 1, rows
    assert rows[0]["state"] == "new_transform"
    assert rows[0]["model_id"] is None
    assert rows[0]["dataset"] is None
    assert rows[0]["path"] == "src/fresh.sql"
