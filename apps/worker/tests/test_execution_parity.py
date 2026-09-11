"""The two places customer Python runs, asked the same questions (§298).

**This repository has two implementations of "run a transform", and they have
already disagreed in production.** `python_sandbox.py` runs one in a subprocess
and is what development uses; `transform_runner.py` runs one inside the
no-egress container and is what a deployment uses
(`transform_dispatch.isolation_mode()` picks). §292 found the second had never
supported the declared `@transform` shape at all — so a repository-authored
Python transform ran locally and answered `NameError` when deployed, with every
suite green, because no test on the container path had ever used a decorator.

That is the failure a **differential test** exists to catch: feed both the same
input, compare what comes back. Agreement does not prove either is right; it is
disagreement that is the point, and it arrives as a precise list of which case
rather than as a bug report months later.

**What must agree, and what deliberately does not.** The list below is the
whole contract, and a divergence that is not on it fails here:

- the rows written, the schema, and the row count
- every refusal *the platform* makes: which shape a file used, an input that was
  not provided, a parameter list that does not match, a transform that returned
  nothing, and the row cap
- **not** the text of an error raised by the author's own code: the container
  carries a traceback and the subprocess does not, deliberately, because a
  container's run is asynchronous and cannot be re-run by pressing a button.
  The first line agrees, and that is asserted.

Read `docs/decisions/0004-running-customer-code.md` for why there are two at
all: the container is the isolation, and the subprocess is what a machine
without ECS can run.
"""
from __future__ import annotations

import json
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from anchor_worker import transform_dispatch as dispatch  # noqa: E402
from anchor_worker import transform_runner as runner  # noqa: E402
from anchor_worker import python_sandbox  # noqa: E402
from anchor_worker.dataset_engine import DatasetEngineError  # noqa: E402

ROWS = [(1, "north"), (2, "south"), (3, "north")]


def make_parquet(path: str, rows: list[tuple[int, str]]) -> str:
    import duckdb

    os.makedirs(os.path.dirname(path), exist_ok=True)
    values = ", ".join(f"({i}, '{region}')" for i, region in rows)
    duckdb.connect().execute(
        f"COPY (SELECT * FROM (VALUES {values}) t(id, region)) TO '{path}' (FORMAT parquet)"
    )
    return path


def read_parquet(path: str) -> list[tuple]:
    import duckdb

    if not os.path.exists(path):
        return []
    return sorted(
        duckdb.connect().execute(f"SELECT * FROM read_parquet('{path}')").fetchall()
    )


def _normalise(error: str) -> str:
    """One answer's error, comparable with the other's.

    Only the first line: the container adds a traceback to an error raised by
    the author's own code and the subprocess does not, which is the one
    difference this module allows. See the header.
    """
    return error.splitlines()[0].strip()


def through_the_sandbox(tmp_path, code: str, with_input: bool) -> dict:
    """The development path: a subprocess with a stripped environment."""
    work = str(tmp_path / f"sandbox-{uuid.uuid4().hex[:8]}")
    os.makedirs(work, exist_ok=True)
    inputs = {}
    if with_input:
        inputs["orders"] = make_parquet(os.path.join(work, "orders.parquet"), ROWS)
    destination = os.path.join(work, "out", "output.parquet")
    try:
        schema, row_count = python_sandbox.run_python_transform(inputs, code, destination)
    except DatasetEngineError as exc:
        return {"ok": False, "error": _normalise(str(exc))}
    return {
        "ok": True,
        "row_count": row_count,
        "schema": [(column.name, column.data_type) for column in schema],
        "rows": read_parquet(destination),
    }


def through_the_container(tmp_path, code: str, with_input: bool) -> dict:
    """The deployment path: staged into a directory and run by the entrypoint.

    `runner.main()` in this process rather than a real Fargate task - what is
    skipped is ECS, not the code. `dispatch.stage` is the same caller the worker
    uses, so the directory the runner reads is the one it would really find.
    """
    root = str(tmp_path / f"scratch-{uuid.uuid4().hex[:8]}")
    os.makedirs(root, exist_ok=True)
    inputs = {}
    if with_input:
        inputs["orders"] = make_parquet(str(tmp_path / f"in-{uuid.uuid4().hex[:8]}.parquet"), ROWS)
    handle = dispatch.stage(dispatch.TransformJob(code=code, inputs=inputs), root=root)

    before = os.environ.get(runner.WORK_DIR_ENV)
    os.environ[runner.WORK_DIR_ENV] = handle.work_dir
    try:
        code_returned = runner.main()
    finally:
        if before is None:
            os.environ.pop(runner.WORK_DIR_ENV, None)
        else:
            os.environ[runner.WORK_DIR_ENV] = before

    with open(os.path.join(handle.work_dir, runner.RESULT_FILE)) as answer:
        result = json.load(answer)
    if code_returned != 0:
        return {"ok": False, "error": _normalise(result["error"])}
    return {
        "ok": True,
        "row_count": result["row_count"],
        "schema": [(column["name"], column["data_type"]) for column in result["schema"]],
        "rows": read_parquet(os.path.join(handle.work_dir, handle.output_filename)),
    }


def both(tmp_path, code: str, with_input: bool = True) -> tuple[dict, dict]:
    return (
        through_the_sandbox(tmp_path, code, with_input),
        through_the_container(tmp_path, code, with_input),
    )


def assert_agree(sandbox: dict, container: dict) -> dict:
    assert sandbox == container, (
        "the two places customer Python runs disagree about this transform.\n"
        f"  subprocess (development): {sandbox}\n"
        f"  container  (deployment):  {container}\n"
        "One of them is what a customer will actually get, and which one depends "
        "on where the platform is running - see decision 0004."
    )
    return sandbox


# ---- the shapes that work ------------------------------------------------------
SCRIPT = """\
output = orders[orders["region"] == "north"]
"""

DECLARED = """\
import anchor


@anchor.transform(output="northern", inputs={"orders": "raw_orders"})
def build(orders):
    return orders[orders["region"] == "north"]
"""

BARE_DECORATOR = """\
@transform(output="northern", inputs={"orders": "raw_orders"})
def build(orders):
    return orders[orders["region"] == "north"]
"""


@pytest.mark.parametrize(
    "name, code",
    [("script", SCRIPT), ("declared", DECLARED), ("bare decorator", BARE_DECORATOR)],
)
def test_both_paths_produce_the_same_table(tmp_path, name: str, code: str) -> None:
    """**The regression §292 could not have had.** Its fix was checked on each
    path separately; this asks them the same question and compares."""
    agreed = assert_agree(*both(tmp_path, code))
    assert agreed["ok"], agreed
    assert agreed["row_count"] == 2
    assert agreed["rows"] == [(1, "north"), (3, "north")]
    assert [column for column, _type in agreed["schema"]] == ["id", "region"]


def test_both_paths_agree_on_an_untouched_table(tmp_path) -> None:
    """The identity case, and worth having on its own: a transform that changes
    nothing is where a difference in *reading* rather than in running would
    show, and every other case here would blame the transform for it."""
    agreed = assert_agree(*both(tmp_path, "output = orders\n"))
    assert agreed["rows"] == sorted(ROWS)


# ---- the refusals, which are the platform's own words -----------------------------
NEITHER_SHAPE = "answer = 42\n"

TWO_DECLARATIONS = """\
import anchor


@anchor.transform(output="one", inputs={})
def a():
    return 1


@anchor.transform(output="two", inputs={})
def b():
    return 2
"""

INPUT_NOT_PROVIDED = """\
import anchor


@anchor.transform(output="x", inputs={"missing": "nowhere"})
def build(missing):
    return missing
"""

PARAMETERS_DO_NOT_MATCH = """\
import anchor


@anchor.transform(output="x", inputs={"orders": "raw_orders"})
def build():
    return 1
"""

RETURNED_NOTHING = """\
import anchor


@anchor.transform(output="x", inputs={"orders": "raw_orders"})
def build(orders):
    return None
"""


@pytest.mark.parametrize(
    "name, code, expected",
    [
        ("neither shape", NEITHER_SHAPE, "neither set a variable named `output`"),
        ("two declarations", TWO_DECLARATIONS, "more than one transform"),
        ("input not provided", INPUT_NOT_PROVIDED, "inputs that were not provided"),
        ("parameters do not match", PARAMETERS_DO_NOT_MATCH, "does not take the inputs it declares"),
        ("returned nothing", RETURNED_NOTHING, "returned nothing"),
    ],
)
def test_both_paths_refuse_with_the_same_sentence(
    tmp_path, name: str, code: str, expected: str
) -> None:
    """**The platform's refusals are the platform's, so they must be one
    sentence.** Two wordings for one rule is how §292's disagreement started:
    each side was right about itself, and nothing compared them.

    Asserted as equality first and content second, so a divergence fails here
    with both texts rather than with "did not contain".
    """
    agreed = assert_agree(*both(tmp_path, code))
    assert not agreed["ok"], agreed
    assert expected in agreed["error"], agreed["error"]


def test_an_error_in_the_authors_own_code_agrees_on_its_first_line(tmp_path) -> None:
    """**The one allowed divergence, pinned rather than left open.**

    The container appends a traceback and the subprocess does not, deliberately:
    a container's run is asynchronous, and whoever reads the result cannot press
    a button to see more. The *first line* is the sentence a person reads, and
    it has to be the same one - so that is what agrees, and the difference below
    it is asserted to exist rather than assumed.
    """
    sandbox, container = both(tmp_path, "output = 1 / 0\n")
    assert not sandbox["ok"] and not container["ok"]
    assert sandbox["error"] == container["error"] == "ZeroDivisionError: division by zero"

    # And the divergence is real, not a coincidence of this example: the
    # container's *unnormalised* error carries more. If this ever stops being
    # true the comment above is wrong and should go.
    root = str(tmp_path / "traceback-check")
    os.makedirs(root, exist_ok=True)
    handle = dispatch.stage(dispatch.TransformJob(code="output = 1 / 0\n"), root=root)
    os.environ[runner.WORK_DIR_ENV] = handle.work_dir
    runner.main()
    with open(os.path.join(handle.work_dir, runner.RESULT_FILE)) as answer:
        assert "Traceback" in json.load(answer)["error"]


def test_both_paths_refuse_the_same_number_of_rows(tmp_path, monkeypatch) -> None:
    """**A cap declared twice.**

    `python_sandbox.MAX_OUTPUT_ROWS` and `transform_runner.MAX_OUTPUT_ROWS` are
    separate constants, and deliberately: the container keeps its import surface
    tiny - a test asserts it pulls in neither boto3 nor psycopg - so it does not
    reach into the module beside it. Their agreement is therefore a *test*
    rather than a mechanism, which is the same arrangement §289 made for the
    commit message the browser prefills and the server derives.

    Lowered on both for the run, because a five-million-row fixture is not a
    test anybody would run.
    """
    assert python_sandbox.MAX_OUTPUT_ROWS == runner.MAX_OUTPUT_ROWS, (
        "the two runners cap a transform's output at different sizes, so the "
        "same transform is refused in one place and written in the other"
    )

    monkeypatch.setattr(python_sandbox, "MAX_OUTPUT_ROWS", 2)
    monkeypatch.setattr(runner, "MAX_OUTPUT_ROWS", 2)
    agreed = assert_agree(*both(tmp_path, "output = orders\n"))
    assert not agreed["ok"], agreed
    # The size and the limit both named, because "too many rows" without either
    # leaves the author guessing at which join lost its condition.
    assert "3" in agreed["error"] and "2" in agreed["error"], agreed["error"]

# ---- the comparison itself, given a case that fires it -------------------------
def test_the_comparison_catches_a_real_divergence(tmp_path, monkeypatch) -> None:
    """**A survivor found that `assert_agree` could be switched off** and every
    test in this file still passed: each case also asserts on the dict it
    returns, and that dict is the *subprocess* answer. So the comparison — the
    only thing this module exists for — was a check nothing could make fail.

    Every real case here agrees, which is the problem: a guard with no case in
    the tree that fires it can be deleted with nothing noticing. §293 hit the
    same shape twice. So this manufactures a divergence, by lowering the cap on
    one runner and not the other, and asserts the comparison sees it and says
    which side said what.
    """
    monkeypatch.setattr(runner, "MAX_OUTPUT_ROWS", 2)
    sandbox, container = both(tmp_path, "output = orders\n")
    assert sandbox["ok"], "the subprocess path should still have written 3 rows"
    assert not container["ok"], "the container should have refused at 2"

    with pytest.raises(AssertionError) as caught:
        assert_agree(sandbox, container)
    # And the failure names both answers, because "they disagree" without them
    # is a message that sends somebody back to run it again by hand.
    assert "subprocess (development)" in str(caught.value)
    assert "container  (deployment)" in str(caught.value)
    assert "row limit" in str(caught.value)
