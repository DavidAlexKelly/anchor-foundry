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


# ---- p.54's Schema: what the proposed code does to the columns (§365) --------

def schema_change(client: TestClient, fx: Fixture, proposal_id: str, model_id: str,
                  sub: str | None = None):
    return client.get(
        f"{cbase(fx)}/proposals/{proposal_id}/impact/{model_id}/schema",
        headers=hdr(sub or fx.viewer_sub),
    )


def test_a_dropped_column_is_reported_as_removed(
    client: TestClient, fx: Fixture, source: str
) -> None:
    """p.54's question, and the answer that matters most to a reviewer: this
    change takes a column away from everything downstream."""
    model_id = make_model(client, fx, source, "SELECT id, val FROM raw")
    run(client, fx, model_id)
    proposal = propose(client, fx, [{"model_id": model_id, "code": "SELECT id FROM raw"}])

    r = schema_change(client, fx, proposal["id"], model_id)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert [c["name"] for c in body["changes"]["removed"]] == ["val"]
    assert "added" not in body["changes"]


# ---- p.54's Expectations, answered as p.52 asks it (§371) -------------------

def add_rule(client: TestClient, fx: Fixture, dataset_id: str, rule_type: str,
             column: str, config: dict | None = None, severity: str = "error") -> dict:
    r = client.post(
        f"{pbase(fx)}/datasets/{dataset_id}/expectations",
        headers=hdr(fx.editor_sub),
        json={"rule_type": rule_type, "column_name": column,
              "config": config or {}, "severity": severity},
    )
    assert r.status_code == 201, r.text
    return r.json()


def output_of(client: TestClient, fx: Fixture, model_id: str) -> str:
    r = client.get(f"{pbase(fx)}/models/{model_id}", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return str(r.json()["output_dataset_id"])


def test_a_removed_column_fails_the_rule_that_asserts_it_and_breaks_the_rest(
    client: TestClient, fx: Fixture, source: str
) -> None:
    """**The distinction the panel exists to keep**, read out of
    `_evaluate_one` rather than assumed: `column_exists` on a removed column
    *fails* — that is the rule doing its job — and every other rule *errors*,
    because "the column is not in this version" is not a statement about the
    data. Collapsing the two would tell a reviewer their data went bad when
    their rule stopped applying.
    """
    model_id = make_model(client, fx, source, "SELECT id, val FROM raw")
    run(client, fx, model_id)
    dataset_id = output_of(client, fx, model_id)
    asserts_it = add_rule(client, fx, dataset_id, "column_exists", "val")
    needs_it = add_rule(client, fx, dataset_id, "not_null", "val", severity="warn")
    # A rule on a column the change keeps, so "everything is at risk" is
    # distinguishable from "the right things are" (§190).
    add_rule(client, fx, dataset_id, "not_null", "id")

    proposal = propose(client, fx, [{"model_id": model_id, "code": "SELECT id FROM raw"}])
    body = schema_change(client, fx, proposal["id"], model_id).json()

    at_risk = {r["expectation_id"]: r for r in body["expectations_at_risk"]}
    assert set(at_risk) == {asserts_it["id"], needs_it["id"]}
    assert at_risk[asserts_it["id"]]["outcome"] == "fail"
    assert at_risk[needs_it["id"]]["outcome"] == "error"
    assert at_risk[needs_it["id"]]["severity"] == "warn"
    assert {r["reason"] for r in at_risk.values()} == {"removed"}


def test_a_retype_breaks_a_range_rule_and_leaves_a_regex_rule_alone(
    client: TestClient, fx: Fixture, source: str
) -> None:
    """**Measured before it was claimed.** `value_in_range` compiles to
    `col < 5`, which DuckDB refuses to bind against VARCHAR; `regex_match`
    casts to VARCHAR first, so no retype can reach it. Both rules sit on the
    same retyped column here, which is what makes the pair a check rather than
    two separate half-checks.
    """
    model_id = make_model(client, fx, source, "SELECT id, val FROM raw")
    run(client, fx, model_id)
    dataset_id = output_of(client, fx, model_id)
    ranged = add_rule(client, fx, dataset_id, "value_in_range", "val",
                      {"min": 0, "max": 100})
    add_rule(client, fx, dataset_id, "regex_match", "val", {"pattern": "^[0-9]+$"})

    proposal = propose(client, fx, [
        {"model_id": model_id, "code": "SELECT id, CAST(val AS VARCHAR) AS val FROM raw"},
    ])
    body = schema_change(client, fx, proposal["id"], model_id).json()

    assert [c["name"] for c in body["changes"]["retyped"]] == ["val"]
    at_risk = body["expectations_at_risk"]
    assert [r["expectation_id"] for r in at_risk] == [ranged["id"]]
    assert at_risk[0]["reason"] == "retyped"
    assert at_risk[0]["new_type"] == "VARCHAR"


def test_a_retype_that_stays_numeric_breaks_nothing(
    client: TestClient, fx: Fixture, source: str
) -> None:
    """The half that stops this being "any retype is trouble". A range check
    against DECIMAL binds exactly as it does against BIGINT — measured across
    every type this platform produces, and the surprise was BOOLEAN, which
    also binds."""
    model_id = make_model(client, fx, source, "SELECT id, val FROM raw")
    run(client, fx, model_id)
    dataset_id = output_of(client, fx, model_id)
    add_rule(client, fx, dataset_id, "value_in_range", "val", {"min": 0, "max": 100})

    proposal = propose(client, fx, [
        {"model_id": model_id, "code": "SELECT id, val * 1.5 AS val FROM raw"},
    ])
    body = schema_change(client, fx, proposal["id"], model_id).json()

    assert [c["name"] for c in body["changes"]["retyped"]] == ["val"]
    assert body["expectations_at_risk"] == []


def test_a_change_that_moves_no_columns_puts_nothing_at_risk(
    client: TestClient, fx: Fixture, source: str
) -> None:
    """A dataset with rules on it and a proposal that leaves the columns
    alone: the panel has to be silent, or every review of a logic change would
    come with a list of rules that are perfectly fine."""
    model_id = make_model(client, fx, source, "SELECT id, val FROM raw")
    run(client, fx, model_id)
    dataset_id = output_of(client, fx, model_id)
    add_rule(client, fx, dataset_id, "not_null", "val")

    proposal = propose(client, fx, [
        {"model_id": model_id, "code": "SELECT id, val FROM raw WHERE id > 0"},
    ])
    body = schema_change(client, fx, proposal["id"], model_id).json()

    assert body["changes"] is None
    assert body["expectations_at_risk"] == []


def test_a_dataset_with_no_rules_says_nothing_rather_than_failing(
    client: TestClient, fx: Fixture, source: str
) -> None:
    """Most datasets have no expectations, so this is the common path."""
    model_id = make_model(client, fx, source, "SELECT id, val FROM raw")
    run(client, fx, model_id)
    proposal = propose(client, fx, [{"model_id": model_id, "code": "SELECT id FROM raw"}])
    body = schema_change(client, fx, proposal["id"], model_id).json()

    assert body["changes"]["removed"][0]["name"] == "val"
    assert body["expectations_at_risk"] == []


def test_a_new_column_is_reported_as_added(
    client: TestClient, fx: Fixture, source: str
) -> None:
    model_id = make_model(client, fx, source, "SELECT id FROM raw")
    run(client, fx, model_id)
    proposal = propose(
        client, fx, [{"model_id": model_id, "code": "SELECT id, val FROM raw"}]
    )

    body = schema_change(client, fx, proposal["id"], model_id).json()
    assert [c["name"] for c in body["changes"]["added"]] == ["val"]


def test_a_changed_type_is_reported_as_retyped(
    client: TestClient, fx: Fixture, source: str
) -> None:
    """The change a reader is least likely to spot in a diff, and the one most
    likely to break something downstream that was summing a number."""
    model_id = make_model(client, fx, source, "SELECT id, val FROM raw")
    run(client, fx, model_id)
    proposal = propose(
        client, fx,
        [{"model_id": model_id, "code": "SELECT id, CAST(val AS VARCHAR) AS val FROM raw"}],
    )

    body = schema_change(client, fx, proposal["id"], model_id).json()
    retyped = body["changes"]["retyped"]
    assert [c["name"] for c in retyped] == ["val"]
    assert retyped[0]["from"] == "BIGINT"
    assert retyped[0]["to"] == "VARCHAR"


def test_no_change_is_said_rather_than_left_blank(
    client: TestClient, fx: Fixture, source: str
) -> None:
    """**The answer a reviewer most wants to be told.** A proposal that rewrites
    a query without moving a column is the common case, and an endpoint that
    returned nothing for it would be indistinguishable from one that failed."""
    model_id = make_model(client, fx, source, "SELECT id, val FROM raw")
    run(client, fx, model_id)
    proposal = propose(
        client, fx,
        [{"model_id": model_id, "code": "SELECT id, val FROM raw WHERE id > 0"}],
    )

    body = schema_change(client, fx, proposal["id"], model_id).json()
    assert body["ok"] is True
    assert body["changes"] is None
    assert body["error"] is None


def test_code_that_does_not_run_says_so_where_the_schema_would_be(
    client: TestClient, fx: Fixture, source: str
) -> None:
    """**p.52's "validate that the code builds properly", for the price of a
    preview rather than two builds.** It belongs beside the schema because a
    reviewer asking what this does to the columns is owed "it does not run" in
    the same place, not in a check they have to go and find."""
    model_id = make_model(client, fx, source, "SELECT id, val FROM raw")
    run(client, fx, model_id)
    proposal = propose(
        client, fx, [{"model_id": model_id, "code": "SELECT nope FROM raw"}]
    )

    r = schema_change(client, fx, proposal["id"], model_id)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    assert body["changes"] is None
    assert "nope" in body["error"]


def test_the_sample_it_read_is_reported_rather_than_implied(
    client: TestClient, fx: Fixture, source: str
) -> None:
    """A reviewer told "this came from a sample" and not told how big a one has
    been handed a disclaimer rather than a fact. The columns do not depend on
    it — measured at 10, 1000 and 5000 rows — but saying so needs the number."""
    model_id = make_model(client, fx, source, "SELECT id, val FROM raw")
    run(client, fx, model_id)
    proposal = propose(client, fx, [{"model_id": model_id, "code": "SELECT id FROM raw"}])

    body = schema_change(client, fx, proposal["id"], model_id).json()
    assert len(body["sampled"]) == 1
    assert body["sampled"][0]["alias"] == "raw"
    assert body["sampled"][0]["rows_available"] == 3
    assert body["sampled"][0]["rows_used"] == 3


def test_the_preview_reads_this_transform_s_inputs_and_not_the_project_s(
    client: TestClient, fx: Fixture
) -> None:
    """**A fixture that can tell them apart.** Every other test here gives its
    models the same single input under the same alias, so a query that pulled
    in every input row in the project would return the same pair and look
    right. This gives the other transform an input of its own, under an alias
    nothing else uses (§190).
    """
    mine = client.post(
        f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"Mine {uuid.uuid4().hex[:6]}"},
        files={"file": ("rows.csv", io.BytesIO(b"id,val\n1,10\n"), "text/csv")},
    ).json()["id"]
    theirs = client.post(
        f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"Theirs {uuid.uuid4().hex[:6]}"},
        files={"file": ("rows.csv", io.BytesIO(b"id,val\n1,10\n2,20\n"), "text/csv")},
    ).json()["id"]

    model_id = make_model(client, fx, mine, "SELECT id, val FROM raw")
    other = client.post(
        f"{pbase(fx)}/models", headers=hdr(fx.editor_sub),
        json={"name": f"Neighbour {uuid.uuid4().hex[:6]}", "code": "SELECT id FROM elsewhere",
              "inputs": [{"dataset_id": theirs, "input_alias": "elsewhere"}]},
    )
    assert other.status_code == 201, other.text
    run(client, fx, model_id)

    proposal = propose(client, fx, [{"model_id": model_id, "code": "SELECT id FROM raw"}])
    body = schema_change(client, fx, proposal["id"], model_id).json()
    assert [s["alias"] for s in body["sampled"]] == ["raw"], body["sampled"]


def test_a_transform_that_has_never_been_built_has_no_schema_to_compare(
    client: TestClient, fx: Fixture, source: str
) -> None:
    """The same condition the list reports as `never_built`, refused here by
    name rather than answered with an empty diff — which would read as "no
    columns change"."""
    model_id = make_model(client, fx, source)
    proposal = propose(client, fx, [{"model_id": model_id, "code": "SELECT val FROM raw"}])

    r = schema_change(client, fx, proposal["id"], model_id)
    assert r.status_code == 409, r.text
    assert "never been built" in r.text


def test_a_file_the_proposal_does_not_change_is_not_answerable(
    client: TestClient, fx: Fixture, source: str
) -> None:
    """Without this, the schema of any model in any project the caller can
    reach could be asked for through a proposal that has nothing to do with it
    — and the answer would be a diff against code nobody proposed."""
    changed = make_model(client, fx, source)
    other = make_model(client, fx, source)
    run(client, fx, changed)
    run(client, fx, other)
    proposal = propose(client, fx, [{"model_id": changed, "code": "SELECT val FROM raw"}])

    r = schema_change(client, fx, proposal["id"], other)
    assert r.status_code == 404, r.text


def test_an_outsider_cannot_ask_for_a_schema_change(
    client: TestClient, fx: Fixture, source: str
) -> None:
    model_id = make_model(client, fx, source)
    run(client, fx, model_id)
    proposal = propose(client, fx, [{"model_id": model_id, "code": "SELECT val FROM raw"}])
    assert schema_change(
        client, fx, proposal["id"], model_id, sub=fx.outsider_sub
    ).status_code == 404
