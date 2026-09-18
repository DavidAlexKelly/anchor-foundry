"""The worker half of a Python transform preview (§390; db 0092).

Decision 0004 keeps customer Python out of the API process, so pressing Preview
on a `.py` file queues a row and this job answers it. What needs a database and
real Parquet is everything interesting about that:

  * that a queued row is claimed exactly once and lands in the shape the panel
    reads;
  * that **the transform raising and the run not happening end differently** -
    `failed` sends the author to their code, `errored` does not;
  * that the sample is really a sample, and that both numbers survive to the
    row, because a preview that reported a count without saying it was sampled
    would be confidently wrong.

`test_transform_dispatch.py` holds what the runner does with the code. This
holds what the platform does with the answer.
"""
from __future__ import annotations

import json
import os
import sys
import uuid

import duckdb
import psycopg
import pytest
from dagster import build_op_context

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import anchor_worker.jobs.code_preview_runs as preview_job  # noqa: E402
from anchor_worker.dataset_engine import DatasetEngineError  # noqa: E402
from anchor_worker.jobs.code_preview_runs import run_queued_preview_runs  # noqa: E402
from anchor_worker.resources import PlatformDatabase  # noqa: E402

ADMIN_DSN = os.environ["TEST_ADMIN_DSN"]
APP_DSN = os.environ["WORKER_DATABASE_URL"]

#: Deliberately more than one sample's worth, so "sampled" is a state the
#: fixture really reaches rather than a flag nothing sets.
INPUT_ROWS = 1500

PASSING = (
    "@transform(output='doubled', inputs={'orders': 'orders'})\n"
    "def build(orders):\n"
    "    out = orders.copy()\n"
    "    out['doubled'] = out['id'] * 2\n"
    "    return out\n"
)


@pytest.fixture()
def storage_root(tmp_path, monkeypatch) -> str:
    root = str(tmp_path / "storage")
    monkeypatch.setenv("LOCAL_STORAGE_ROOT", root)
    monkeypatch.delenv("DATA_BUCKET", raising=False)
    return root


@pytest.fixture()
def repository(storage_root: str):
    """One org/workspace/project/repository, and one input dataset on disk."""
    tag = uuid.uuid4().hex[:8]
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        org = conn.execute(
            "INSERT INTO organisations (name, slug) VALUES (%s,%s) RETURNING id",
            (f"PrevOrg {tag}", f"prev-org-{tag}"),
        ).fetchone()[0]
        user = conn.execute(
            """INSERT INTO users (organisation_id, email, display_name, org_role,
                                  cognito_sub, status)
               VALUES (%s,%s,%s,'owner',%s,'active') RETURNING id""",
            (org, f"prev-{tag}@example.com", "Prev", f"sub-prev-{tag}"),
        ).fetchone()[0]
        wid = uuid.uuid4()
        short = wid.hex[:12]
        conn.execute(
            """INSERT INTO workspaces (id, organisation_id, name, slug, s3_prefix,
                                       pg_schema, search_prefix, created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (wid, org, f"W {tag}", f"w-{tag}", f"workspaces/w-{tag}/",
             f"ws_{short}", f"ws-{short}-", user),
        )
        pid = conn.execute(
            "INSERT INTO projects (workspace_id, name, slug, created_by) "
            "VALUES (%s,%s,%s,%s) RETURNING id",
            (wid, f"P {tag}", f"p-{tag}", user),
        ).fetchone()[0]
        rid = conn.execute(
            """INSERT INTO code_repos (project_id, name, slug, s3_prefix, created_by)
               VALUES (%s,%s,%s,%s,%s) RETURNING id""",
            (pid, f"Transforms {tag}", f"transforms-{tag}",
             f"workspaces/w-{tag}/repos/{tag}/", user),
        ).fetchone()[0]

        did = uuid.uuid4()
        key = f"workspaces/w-{tag}/datasets/{did}/v1/data.parquet"
        full = os.path.join(storage_root, key)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        duckdb.connect().execute(
            f"COPY (SELECT i AS id FROM range({INPUT_ROWS}) t(i)) "
            f"TO '{full}' (FORMAT parquet)"
        )
        conn.execute(
            """INSERT INTO datasets (id, project_id, workspace_id, name, slug, origin,
                                     s3_location, table_schema, row_count,
                                     current_version, created_by)
               VALUES (%s,%s,%s,%s,%s,'upload',%s,'[]'::jsonb,%s,1,%s)""",
            (did, pid, wid, f"Orders {tag}", f"orders-{tag}", key, INPUT_ROWS, user),
        )
    return {
        "workspace_id": wid, "project_id": pid, "repo_id": rid,
        "user_id": user, "dataset_id": did,
    }


def queue(repository: dict, content: str = PASSING, *, inputs=None,
          path: str = "src/build.py") -> uuid.UUID:
    inputs = {"orders": str(repository["dataset_id"])} if inputs is None else inputs
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        return conn.execute(
            """INSERT INTO code_preview_runs
                      (repo_id, branch, path, content, input_datasets, requested_by)
               VALUES (%s,'main',%s,%s,CAST(%s AS jsonb),%s) RETURNING id""",
            (repository["repo_id"], path, content, json.dumps(inputs),
             repository["user_id"]),
        ).fetchone()[0]


def row(run_id: uuid.UUID) -> dict:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        got = conn.execute(
            "SELECT status, result, inputs, error, started_at, finished_at "
            "  FROM code_preview_runs WHERE id = %s",
            (run_id,),
        ).fetchone()
    return {
        "status": got[0], "result": got[1], "inputs": got[2],
        "error": got[3], "started_at": got[4], "finished_at": got[5],
    }


def poll() -> int:
    context = build_op_context(resources={"platform_db": PlatformDatabase(dsn=APP_DSN)})
    return run_queued_preview_runs(context)


def test_a_queued_preview_is_picked_up_and_answered(repository) -> None:
    run_id = queue(repository)
    assert poll() >= 1

    got = row(run_id)
    assert got["status"] == "succeeded", got["error"]
    assert got["error"] is None
    assert got["started_at"] is not None and got["finished_at"] is not None
    assert [c["name"] for c in got["result"]["columns"]] == ["id", "doubled"]
    assert got["result"]["rows"][0] == ["0", "0"]
    assert got["result"]["rows"][1] == ["1", "2"]


def test_the_rows_are_capped_and_the_real_count_is_kept(repository) -> None:
    """**The number and the page are different facts.**

    A thousand sampled rows in produce a thousand rows out, and the panel shows
    a hundred of them. Reporting `len(rows)` as the count would tell somebody
    their transform produced a hundred rows, which is the kind of wrong nobody
    checks because it looks like a real answer (§214).
    """
    run_id = queue(repository)
    poll()

    result = row(run_id)["result"]
    assert len(result["rows"]) == preview_job.engine.PREVIEW_ROWS == 100
    assert result["total_rows"] == preview_job.engine.PREVIEW_SAMPLE_ROWS == 1000


def test_the_sample_is_a_sample_and_both_numbers_reach_the_row(repository) -> None:
    """1500 rows in, 1000 read. A preview over a join or a group-by finds fewer
    matches and smaller groups than the real run will, so a count that did not
    say it came from a sample would be believed."""
    run_id = queue(repository)
    poll()

    (orders,) = row(run_id)["inputs"]
    assert orders["alias"] == "orders"
    assert orders["rows_available"] == INPUT_ROWS
    assert orders["rows_used"] == 1000


def test_a_transform_that_raises_ends_failed_with_what_it_said(repository) -> None:
    """The author's answer about their own code, on their own data. A status
    that said `errored` would send them to ask the platform about it."""
    run_id = queue(
        repository,
        "@transform(output='doubled', inputs={'orders': 'orders'})\n"
        "def build(orders):\n"
        "    raise ValueError('the region column is missing')\n",
    )
    poll()

    got = row(run_id)
    assert got["status"] == "failed"
    assert got["error"] is None, "a transform raising is a result, not an error"
    assert "region column is missing" in got["result"]["error"]
    assert got["result"]["rows"] == []


def test_a_preview_that_could_not_happen_ends_errored_and_not_failed(
    repository, monkeypatch
) -> None:
    """**The distinction db 0092 is built around**, and the one this job could
    most easily lose: an infrastructure failure that reported `failed` would
    tell an author their transform is broken when it never ran."""
    def refuse(*args, **kwargs):
        raise RuntimeError("the runner task would not start")

    monkeypatch.setattr(preview_job, "run_python_transform", refuse)
    run_id = queue(repository)
    poll()

    got = row(run_id)
    assert got["status"] == "errored"
    assert got["result"] is None, "there is no answer about their code here"
    assert "could not preview" in got["error"]


def test_an_input_that_vanished_between_queueing_and_running_errors(repository) -> None:
    """Resolved at the button and gone by the time the worker looked. Not the
    author's code, so `errored` - and the alias is in the message, because
    "a dataset" is not something anybody can act on."""
    run_id = queue(repository, inputs={"orders": str(uuid.uuid4())})
    poll()

    got = row(run_id)
    assert got["status"] == "errored"
    assert "orders" in got["error"]
    assert got["inputs"] is None


def test_a_preview_is_claimed_once_even_when_two_workers_found_it(repository) -> None:
    """Two workers polling the same minute must not both run the same buffer.

    Called directly, twice, for `test_code_test_runs_job.py`'s reason: polling
    twice proves only that `list_queued_preview_runs()` filters on status, and
    the claim would be doing nothing that filter was not already doing. Here
    both workers have discovered the row while it was still queued, which is
    the case the claim exists for.
    """
    run_id = queue(repository)
    db = PlatformDatabase(dsn=APP_DSN)
    context = build_op_context(resources={"platform_db": db})

    assert preview_job._run_one(context, db, run_id, repository["workspace_id"]) is True
    assert preview_job._run_one(context, db, run_id, repository["workspace_id"]) is False

    assert row(run_id)["status"] == "succeeded"


def test_one_preview_going_wrong_does_not_end_the_poll(repository, monkeypatch) -> None:
    """§263. Two queued rows and the first blows up outside the run itself;
    the second still gets its turn."""
    first = queue(repository, path="src/a.py")
    second = queue(repository, path="src/b.py")

    real = preview_job._run_one
    seen: list = []

    def explode(context, db, run_id, workspace_id):
        seen.append(run_id)
        if len(seen) == 1:
            raise RuntimeError("the storage gateway is not reachable")
        return real(context, db, run_id, workspace_id)

    monkeypatch.setattr(preview_job, "_run_one", explode)
    poll()

    assert len(seen) == 2
    finished = [row(first)["status"], row(second)["status"]]
    assert "succeeded" in finished, "the second preview never ran"
