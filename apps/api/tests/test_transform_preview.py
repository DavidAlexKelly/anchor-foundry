"""Previewing a transform without committing it (roadmap phase 2, item 2.6).

Real Postgres, real uploaded datasets, real Parquet, real DuckDB. What is under
test is not "does SQL run" - `test_models.py` covers that - but the three
things that make a preview a preview:

  1. it runs **the editor's buffer**, not what is committed, or it is
     ceremonial;
  2. it runs against a **sample**, and says so, or it quietly misleads whoever
     reads the number;
  3. it says what the change would do to the dataset the transform already
     writes, which is the drift the roadmap asked this to catch.

The refusals matter as much: a transform naming a dataset the project does not
have, and a Python transform, which cannot run here at all (decision 0004).
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


def rbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/repositories"


def dbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets"


# Deliberately more than one sample's worth in one of them, so "sampled" is a
# real state rather than a flag nothing ever sets.
ORDERS = b"order_id,region,total_pence\n" + b"".join(
    f"{i},{'north' if i % 2 else 'south'},{100 + i}\n".encode() for i in range(1, 1501)
)
REGIONS = b"region,manager\nnorth,Ada\nsouth,Grace\n"


@pytest.fixture(scope="module")
def datasets(client: TestClient, fx: Fixture) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, filename, content in [
        (f"orders_p_{fx.tag}", "orders.csv", ORDERS),
        (f"regions_p_{fx.tag}", "regions.csv", REGIONS),
    ]:
        r = client.post(
            f"{dbase(fx)}/upload",
            headers=hdr(fx.editor_sub),
            data={"name": name},
            files={"file": (filename, io.BytesIO(content), "text/csv")},
        )
        assert r.status_code == 201, r.text
        out[name] = r.json()["id"]
    return out


@pytest.fixture(scope="module")
def repo(client: TestClient, fx: Fixture) -> str:
    r = client.post(
        rbase(fx), headers=hdr(fx.editor_sub),
        json={"name": f"Transforms P {uuid.uuid4().hex[:8]}"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def preview(client: TestClient, fx: Fixture, repo_id: str, **body):
    return client.post(
        f"{rbase(fx)}/{repo_id}/preview", headers=hdr(fx.editor_sub), json=body
    )


def sql(fx: Fixture, select: str, output: str = "daily_orders") -> str:
    return (
        f"-- output: {output}\n"
        f"-- input: orders = orders_p_{fx.tag}\n"
        f"{select}\n"
    )


# ---- the point of previewing -------------------------------------------------
def test_it_runs_what_is_in_the_editor_not_what_was_committed(
    client: TestClient, fx: Fixture, repo: str, datasets
) -> None:
    """The load-bearing one. A person asks "does what I just typed work" before
    they are willing to commit it; a preview that could only run committed code
    would answer a question nobody asked."""
    committed = sql(fx, "SELECT order_id FROM orders")
    r = client.post(
        f"{rbase(fx)}/{repo}/commits", headers=hdr(fx.editor_sub),
        json={"branch": "main", "files": {"src/daily.sql": committed}, "message": "first"},
    )
    assert r.status_code == 201, r.text

    edited = sql(fx, "SELECT order_id, region, total_pence * 2 AS doubled FROM orders")
    r = preview(client, fx, repo, path="src/daily.sql", content=edited)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [c["name"] for c in body["columns"]] == ["order_id", "region", "doubled"]
    assert body["output"] == "daily_orders"
    assert body["rows"], "a preview with no rows is not a preview"

    # And the committed version is still what a preview without content runs.
    r = preview(client, fx, repo, path="src/daily.sql")
    assert r.status_code == 200, r.text
    assert [c["name"] for c in r.json()["columns"]] == ["order_id"]


def test_a_preview_over_a_sample_says_that_it_was_a_sample(
    client: TestClient, fx: Fixture, repo: str, datasets
) -> None:
    """1500 rows in, 1000 sampled. A count over a sample is not the count, and
    a screen that showed it without saying so would be believed."""
    r = preview(client, fx, repo, path="q.sql", content=sql(fx, "SELECT * FROM orders"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sampled"] is True
    (orders,) = body["inputs"]
    assert orders["rows_available"] == 1500
    assert orders["rows_used"] == 1000
    assert orders["sampled"] is True
    assert body["row_count"] == 1000
    assert body["truncated"] is True, "100 rows returned out of 1000 produced"
    assert len(body["rows"]) == 100


def test_an_input_that_fits_is_not_reported_as_sampled(
    client: TestClient, fx: Fixture, repo: str, datasets
) -> None:
    """The counterweight: crying sample on a two-row table would train people
    to ignore the warning that matters."""
    source = (
        f"-- output: region_list\n"
        f"-- input: regions = regions_p_{fx.tag}\n"
        f"SELECT * FROM regions\n"
    )
    r = preview(client, fx, repo, path="r.sql", content=source)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sampled"] is False
    assert body["inputs"][0]["rows_available"] == 2
    assert body["inputs"][0]["rows_used"] == 2


# ---- the drift the roadmap asked for -----------------------------------------
def test_it_says_what_the_change_would_do_to_the_dataset_it_writes(
    client: TestClient, fx: Fixture, repo: str, datasets
) -> None:
    """The transform's output names a dataset that already exists, and this
    edit drops a column from it. Finding that out at preview is the whole
    point; finding it out after the pipeline ran is a support ticket."""
    source = (
        f"-- output: orders_p_{fx.tag}\n"
        f"-- input: orders = orders_p_{fx.tag}\n"
        "SELECT order_id, region, total_pence::VARCHAR AS total_pence FROM orders\n"
    )
    r = preview(client, fx, repo, path="drift.sql", content=source)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["writes_to_existing_dataset"] is True
    changes = body["schema_changes"]
    assert changes is not None, "a retyped column is drift and must be reported"
    assert changes["retyped"][0]["name"] == "total_pence"


def test_a_transform_writing_a_new_dataset_reports_no_drift(
    client: TestClient, fx: Fixture, repo: str, datasets
) -> None:
    r = preview(client, fx, repo, path="new.sql", content=sql(fx, "SELECT order_id FROM orders"))
    assert r.status_code == 200, r.text
    assert r.json()["writes_to_existing_dataset"] is False
    assert r.json()["schema_changes"] is None


# ---- refusals ----------------------------------------------------------------
def test_a_transform_reading_a_dataset_this_project_lacks_names_it(
    client: TestClient, fx: Fixture, repo: str, datasets
) -> None:
    source = "-- output: x\n-- input: orders = no_such_dataset\nSELECT 1\n"
    r = preview(client, fx, repo, path="missing.sql", content=source)
    assert r.status_code == 422, r.text
    assert "no_such_dataset" in r.json()["detail"]


def test_a_file_that_declares_nothing_is_refused_with_the_reason(
    client: TestClient, fx: Fixture, repo: str, datasets
) -> None:
    r = preview(client, fx, repo, path="plain.sql", content="SELECT 1\n")
    assert r.status_code == 422, r.text
    assert "does not declare a transform" in r.json()["detail"]


def test_broken_sql_is_reported_as_the_author_s_problem(
    client: TestClient, fx: Fixture, repo: str, datasets
) -> None:
    r = preview(client, fx, repo, path="bad.sql", content=sql(fx, "SELECT nope FROM orders"))
    assert r.status_code == 422, r.text
    assert "nope" in r.json()["detail"].lower()


def test_previewing_python_refuses_rather_than_running_it_here(
    client: TestClient, fx: Fixture, repo: str, datasets
) -> None:
    """Decision 0004: customer Python runs in an isolated task with an empty
    role, never in the API process. A refusal that says why and says what does
    work beats an endpoint that quietly executes it in the wrong place."""
    source = (
        "@transform(output='daily_orders', inputs={'orders': 'orders_p_x'})\n"
        "def build(orders):\n    return orders\n"
    )
    r = preview(client, fx, repo, path="build.py", content=source)
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert "isolated task" in detail
    assert "SQL transforms preview now" in detail


def test_a_declaration_that_cannot_be_read_is_refused_not_guessed(
    client: TestClient, fx: Fixture, repo: str, datasets
) -> None:
    source = "NAME = 'a' + 'b'\n\n@transform(output=NAME)\ndef build(): ...\n"
    r = preview(client, fx, repo, path="computed.py", content=source)
    assert r.status_code == 422, r.text
    assert "computed" in r.json()["detail"]


def test_previewing_a_path_that_is_not_in_the_commit_says_so(
    client: TestClient, fx: Fixture, repo: str, datasets
) -> None:
    r = preview(client, fx, repo, path="src/nowhere.sql")
    assert r.status_code == 404, r.text


# ---- the sandbox ------------------------------------------------------------
def test_preview_sql_cannot_read_a_file_it_was_not_given(
    client: TestClient, fx: Fixture, repo: str, datasets, tmp_path
) -> None:
    """Preview executes caller-supplied SQL, so it needs the boundary the
    saved-model path has - and it is a *second* sandbox, so proving that one
    holds proves nothing about this one.

    Verified by mutation: with `enable_external_access` left on, the token
    below comes back in the response body and this fails on the first
    assertion. (The mutation that appeared to disprove it was hitting
    `run_transform`'s identical line earlier in the same file - the two
    sandboxes are set up with byte-identical statements, which is worth
    knowing before mutating either.)

    A CSV this test wrote rather than `/etc/passwd`: both discriminate, but
    this one does not depend on the host having a file DuckDB happens to be
    able to parse.
    """
    secret = tmp_path / "not-a-dataset.csv"
    secret.write_text("word\nkumquat\n")
    source = (
        "-- output: leak\n"
        f"-- input: orders = orders_p_{fx.tag}\n"
        f"SELECT * FROM read_csv_auto('{secret}')\n"
    )
    r = preview(client, fx, repo, path="leak.sql", content=source)
    assert "kumquat" not in r.text, "the preview sandbox read a file outside its inputs"
    assert r.status_code == 422, r.text


def test_preview_sql_is_one_statement_so_it_cannot_smuggle_a_second(
    client: TestClient, fx: Fixture, repo: str, datasets, tmp_path
) -> None:
    """`COPY ... TO` is the write this would otherwise permit, and it can only
    be a statement of its own. User SQL is always wrapped in one
    `CREATE TABLE ... AS (...)`, so a second statement is a syntax error rather
    than an escape - worth asserting once rather than assuming."""
    escape = str(tmp_path / "escaped.csv")
    source = (
        "-- output: leak\n"
        f"-- input: orders = orders_p_{fx.tag}\n"
        f"SELECT * FROM orders; COPY orders TO '{escape}' (FORMAT csv)\n"
    )
    r = preview(client, fx, repo, path="write.sql", content=source)
    assert r.status_code == 422, r.text
    assert not os.path.exists(escape), "the preview sandbox wrote outside itself"


# ---- who may preview ---------------------------------------------------------
def test_a_viewer_may_not_preview(
    client: TestClient, fx: Fixture, repo: str, datasets
) -> None:
    """A preview executes caller-supplied SQL against the project's datasets.
    The floor matches who may write the file, not who may read it."""
    r = client.post(
        f"{rbase(fx)}/{repo}/preview",
        headers=hdr(fx.viewer_sub),
        json={"path": "q.sql", "content": sql(fx, "SELECT * FROM orders")},
    )
    assert r.status_code == 403, r.text
