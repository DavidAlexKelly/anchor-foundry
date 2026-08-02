"""The transform runner container entrypoint (decision 0004).

Two things are under test. The obvious one is that a transform runs and its
output lands. The one that matters is **the distinction between a transform
that failed and infrastructure that failed**: `result.json` is written when the
transform is wrong and *not* written when the run never got off the ground,
because those are different problems with different owners and a caller that
could not tell them apart would report the wrong one to the wrong person.

Also asserted: this module does not import boto3 or psycopg. It runs in a
container with an empty task role and no egress, so a client for either would
be a client that can only fail confusingly - and its presence would be a sign
somebody had started to undo decision 0004.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from anchor_worker import transform_runner as runner  # noqa: E402


def stage(tmp_path, code: str, inputs: dict[str, str] | None = None, **job) -> str:
    """Write a job the way the caller would, and return the working directory."""
    work = str(tmp_path)
    with open(os.path.join(work, "transform.py"), "w") as handle:
        handle.write(textwrap.dedent(code))
    payload = {"code_path": "transform.py", "output_path": "output.parquet",
               "inputs": inputs or {}, **job}
    with open(os.path.join(work, runner.JOB_FILE), "w") as handle:
        json.dump(payload, handle)
    return work


def make_parquet(work: str, name: str, rows: list[dict]) -> None:
    import duckdb

    con = duckdb.connect()
    con.execute(
        "CREATE TABLE t AS SELECT * FROM (VALUES "
        + ", ".join(f"({r['id']}, '{r['region']}')" for r in rows)
        + ") AS v(id, region)"
    )
    con.execute(f"COPY t TO '{os.path.join(work, name)}' (FORMAT parquet)")


def result(work: str) -> dict:
    with open(os.path.join(work, runner.RESULT_FILE)) as handle:
        return json.load(handle)


# ---- the happy path ----------------------------------------------------------
def test_a_transform_runs_and_its_output_lands(tmp_path) -> None:
    work = stage(
        tmp_path,
        """
        output = orders[orders["region"] == "north"]
        """,
        inputs={"orders": "orders.parquet"},
    )
    make_parquet(work, "orders.parquet",
                 [{"id": 1, "region": "north"}, {"id": 2, "region": "south"},
                  {"id": 3, "region": "north"}])

    os.environ[runner.WORK_DIR_ENV] = work
    assert runner.main() == 0

    payload = result(work)
    assert payload["status"] == "ok"
    assert payload["row_count"] == 2
    assert [c["name"] for c in payload["schema"]] == ["id", "region"]
    assert os.path.exists(os.path.join(work, "output.parquet"))


# ---- the distinction that matters --------------------------------------------
def test_a_failing_transform_writes_a_result_saying_why(tmp_path) -> None:
    """The transform is wrong. That is an answer, and it belongs in the result
    file where the caller reads it."""
    work = stage(tmp_path, "output = 1 / 0\n")
    os.environ[runner.WORK_DIR_ENV] = work

    assert runner.main() == 1
    payload = result(work)
    assert payload["status"] == "failed"
    assert "ZeroDivisionError" in payload["error"]


def test_a_transform_that_never_sets_output_is_told_what_to_do(tmp_path) -> None:
    work = stage(tmp_path, "answer = 42\n")
    os.environ[runner.WORK_DIR_ENV] = work
    assert runner.main() == 1
    assert "assign the table it produces" in result(work)["error"]


def test_a_run_that_was_never_staged_leaves_no_result_file(tmp_path) -> None:
    """Infrastructure failed, not the transform. No result file is the signal,
    and a caller must not read its absence as success."""
    os.environ[runner.WORK_DIR_ENV] = str(tmp_path)
    with pytest.raises(RuntimeError, match="did not stage this run"):
        runner.main()
    assert not os.path.exists(os.path.join(str(tmp_path), runner.RESULT_FILE))


def test_a_missing_input_is_the_transform_s_problem_not_the_platform_s(tmp_path) -> None:
    """The job named an input that is not there. That is a run that should not
    have been dispatched, and it is reported rather than crashing the
    container, so the caller learns which input."""
    work = stage(tmp_path, "output = orders\n", inputs={"orders": "orders.parquet"})
    os.environ[runner.WORK_DIR_ENV] = work
    assert runner.main() == 1
    assert "orders" in result(work)["error"]


# ---- the working directory is the boundary -----------------------------------
@pytest.mark.parametrize("bad", ["/etc/passwd", "../outside.parquet", "a/../../b.parquet"])
def test_an_input_path_that_escapes_the_working_directory_is_refused(tmp_path, bad: str) -> None:
    work = stage(tmp_path, "output = x\n", inputs={"x": bad})
    os.environ[runner.WORK_DIR_ENV] = work
    with pytest.raises(RuntimeError, match="outside the working directory"):
        runner.main()


# ---- what this module may not depend on --------------------------------------
def test_the_runner_imports_no_aws_or_database_client() -> None:
    """It runs with an empty task role and no egress, so a client for either
    could only fail confusingly - and its appearance here would be a sign
    somebody had started to undo decision 0004."""
    source_root = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"
    )
    probe = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {source_root!r})
        import anchor_worker.transform_runner  # noqa: F401
        banned = [m for m in sys.modules if m.split(".")[0] in
                  {{"boto3", "botocore", "psycopg", "sqlalchemy", "requests", "urllib3"}}]
        print(",".join(sorted(banned)))
        """
    )
    completed = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "", f"imported: {completed.stdout.strip()}"
