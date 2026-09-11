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
from anchor_worker import user_api  # noqa: E402


def stage(tmp_path, code: str, inputs: dict[str, str] | None = None, **job) -> str:
    """Write a job the way the caller would, and return the working directory."""
    work = str(tmp_path)
    # **`anchor.py` too, because `dispatch.stage` writes it** (§292). The runner
    # reaches nothing outside this directory, so the module customer code
    # imports has to be in it - and a helper that staged a job the caller would
    # not recognise would test a contract nobody implements.
    user_api.write_into(work)
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


# ---- the declared shape, which this path could not run at all (§292) ----------
def test_a_declared_transform_runs_here_too(tmp_path) -> None:
    """**The production bug this unit found.**

    `python_sandbox.py` bound `transform` before executing the file; this
    module never did. So the shape `docs/decisions/0004-running-customer-code.md`
    documents - and that §272 made work, and that every repository-authored
    Python transform is written in - died here on `NameError: name 'transform'
    is not defined`.

    **In production only.** Development runs the subprocess path, which was
    right, so the suite was green and the deployment was broken. §272's own
    finding a second time, in the half nobody re-checked: no test on this path
    had ever used a decorator.
    """
    work = stage(
        tmp_path,
        """
        import anchor

        @anchor.transform(output="northern", inputs={"orders": "raw_orders"})
        def build(orders):
            return orders[orders["region"] == "north"]
        """,
        inputs={"orders": "orders.parquet"},
    )
    make_parquet(work, "orders.parquet",
                 [{"id": 1, "region": "north"}, {"id": 2, "region": "south"}])
    os.environ[runner.WORK_DIR_ENV] = work
    assert runner.main() == 0
    assert result(work)["row_count"] == 1
    assert os.path.exists(os.path.join(work, "output.parquet"))


def test_the_bare_spelling_of_the_decorator_works_here_too(tmp_path) -> None:
    """The declaration reader accepts `@transform` as well as
    `@anchor.transform`, and a spelling that parses as a declaration and then
    dies on NameError is the same defect in its second form."""
    work = stage(
        tmp_path,
        """
        @transform(output="all_orders", inputs={"orders": "raw_orders"})
        def build(orders):
            return orders
        """,
        inputs={"orders": "orders.parquet"},
    )
    make_parquet(work, "orders.parquet", [{"id": 1, "region": "north"}])
    os.environ[runner.WORK_DIR_ENV] = work
    assert runner.main() == 0
    assert result(work)["row_count"] == 1


def test_a_run_staged_without_anchor_is_infrastructure_not_the_transform(tmp_path) -> None:
    """The distinction this module exists to keep. A caller that forgot to
    stage `anchor.py` wrote a broken run; the author's code is fine, and
    telling them their transform failed would send the wrong person looking."""
    work = stage(tmp_path, "output = 1\n")
    os.remove(os.path.join(work, "anchor.py"))
    os.environ[runner.WORK_DIR_ENV] = work
    with pytest.raises(RuntimeError, match="anchor.py was not staged"):
        runner.main()
    assert not os.path.exists(os.path.join(work, runner.RESULT_FILE))
