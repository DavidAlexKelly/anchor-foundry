"""Python transform sandbox tests - no database needed, just the subprocess
executor against real Parquet files."""
from __future__ import annotations

import os
import sys
import tempfile

import duckdb
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from anchor_worker.dataset_engine import DatasetEngineError  # noqa: E402
from anchor_worker.python_sandbox import run_python_transform  # noqa: E402


@pytest.fixture()
def input_parquet(tmp_path) -> str:
    path = str(tmp_path / "in.parquet")
    con = duckdb.connect()
    con.execute(f"COPY (SELECT * FROM (VALUES (1,'a'),(2,'b')) t(id,name)) TO '{path}' (FORMAT parquet)")
    return path


def test_transform_produces_output(input_parquet: str, tmp_path) -> None:
    dest = str(tmp_path / "out.parquet")
    schema, rows = run_python_transform(
        {"t": input_parquet}, "output = t.copy()\noutput['upper_name'] = output['name'].str.upper()",
        dest,
    )
    assert rows == 2
    names = {c.name for c in schema}
    assert {"id", "name", "upper_name"} <= names
    result = duckdb.connect().execute(f"SELECT * FROM read_parquet('{dest}') ORDER BY id").fetchall()
    assert result == [(1, "a", "A"), (2, "b", "B")]


def test_exception_in_user_code_is_reported(input_parquet: str, tmp_path) -> None:
    dest = str(tmp_path / "out.parquet")
    with pytest.raises(DatasetEngineError, match="ZeroDivisionError"):
        run_python_transform({"t": input_parquet}, "output = 1 / 0", dest)


def test_missing_output_variable_is_reported(input_parquet: str, tmp_path) -> None:
    dest = str(tmp_path / "out.parquet")
    with pytest.raises(DatasetEngineError, match="output"):
        run_python_transform({"t": input_parquet}, "x = 1", dest)


def test_timeout_is_enforced(input_parquet: str, tmp_path) -> None:
    dest = str(tmp_path / "out.parquet")
    with pytest.raises(DatasetEngineError, match="time limit"):
        run_python_transform(
            {"t": input_parquet}, "import time\ntime.sleep(5)\noutput = t", dest, timeout_s=1,
        )


def test_row_count_cap_is_enforced(input_parquet: str, tmp_path, monkeypatch) -> None:
    import anchor_worker.python_sandbox as sandbox_module

    monkeypatch.setattr(sandbox_module, "MAX_OUTPUT_ROWS", 1)
    dest = str(tmp_path / "out.parquet")
    with pytest.raises(DatasetEngineError, match="row limit"):
        run_python_transform({"t": input_parquet}, "output = t", dest)


def test_sandbox_cannot_read_arbitrary_files(input_parquet: str, tmp_path) -> None:
    """Not a claim of a hard security boundary (see the module's docstring)
    - just confirms the subprocess's cwd/HOME are the scratch dir, not the
    caller's, so a script reading a relative path can't see unrelated data."""
    dest = str(tmp_path / "out.parquet")
    with pytest.raises(DatasetEngineError):
        run_python_transform(
            {"t": input_parquet},
            "output = t\nopen('does_not_exist_here.txt').read()",
            dest,
        )


# ---- the declared shape (§272) ----------------------------------------------
# Decision 0004 documents a Python transform as a `@transform`-decorated
# function, `transform_declarations.py` parses exactly that, and every test in
# this file used the script shape - so the documented one had never been run
# here, and could not be: `transform` was undefined in the namespace the
# sandbox execs into. These are the tests that make the two halves meet.
DECLARED = (
    "@transform(output='daily', inputs={'t': 'raw'})\n"
    "def build(t):\n"
    "    out = t.copy()\n"
    "    out['upper_name'] = out['name'].str.upper()\n"
    "    return out\n"
)


def test_a_declared_transform_runs_and_its_return_value_is_the_output(
    input_parquet: str, tmp_path
) -> None:
    """The file decision 0004 prints, run.

    Before §272 this raised `NameError: name 'transform' is not defined` -
    the decorator had no definition anywhere in the runner - so every
    repository-authored Python transform failed before reaching any of the
    limits this file's other tests check.
    """
    dest = str(tmp_path / "out.parquet")
    schema, rows = run_python_transform({"t": input_parquet}, DECLARED, dest)

    assert rows == 2
    assert {"id", "name", "upper_name"} <= {c.name for c in schema}
    result = duckdb.connect().execute(
        f"SELECT * FROM read_parquet('{dest}') ORDER BY id"
    ).fetchall()
    # **The rows, not just the schema.** A decorator that registered the
    # function and a runner that never called it would still produce a file
    # with the right columns if anything else wrote one; only the values say
    # the body ran.
    assert result == [(1, "a", "A"), (2, "b", "B")]


def test_the_attribute_spelling_of_the_decorator_runs_too(
    input_parquet: str, tmp_path
) -> None:
    """`_decorator_name` accepts `@anchor.transform(...)` as the same
    decorator, so a file spelling it that way is published as a transform. A
    spelling the reader takes and the runner cannot find is the same defect in
    its second form, and it would surface only at run time."""
    dest = str(tmp_path / "out.parquet")
    source = (
        "@anchor.transform(output='daily', inputs={'t': 'raw'})\n"
        "def build(t):\n    return t\n"
    )
    _, rows = run_python_transform({"t": input_parquet}, source, dest)
    assert rows == 2


def test_the_inputs_arrive_by_alias_and_not_by_position(
    input_parquet: str, tmp_path
) -> None:
    """`@transform` refuses positional arguments so the file says which name
    means what rather than relying on order (`_from_call`). Calling the
    function positionally would put that back through the other door: two
    inputs whose parameters are in the other order would read the wrong
    dataset each, and produce a table rather than an error.

    So the parameters here are declared in the **opposite** order to the
    aliases. Bound positionally, `left` gets the right-hand dataset.
    """
    other = str(tmp_path / "other.parquet")
    duckdb.connect().execute(
        f"COPY (SELECT * FROM (VALUES (9,'z')) t(id,name)) TO '{other}' (FORMAT parquet)"
    )
    dest = str(tmp_path / "out.parquet")
    source = (
        "@transform(output='joined', inputs={'left': 'a', 'right': 'b'})\n"
        "def build(right, left):\n"
        "    return left\n"
    )
    run_python_transform({"left": input_parquet, "right": other}, source, dest)

    rows = duckdb.connect().execute(
        f"SELECT id FROM read_parquet('{dest}') ORDER BY id"
    ).fetchall()
    assert rows == [(1,), (2,)], "the function got the dataset bound by position"


def test_a_function_whose_parameters_do_not_match_says_so(
    input_parquet: str, tmp_path
) -> None:
    """The common mistake, and a raw TypeError names the function rather than
    the mismatch - "build() got an unexpected keyword argument 't'" reads as a
    bug in the platform to whoever wrote `def build(orders)`."""
    dest = str(tmp_path / "out.parquet")
    source = "@transform(output='daily', inputs={'t': 'raw'})\ndef build(orders):\n    return orders\n"
    with pytest.raises(DatasetEngineError, match="does not take the inputs it declares"):
        run_python_transform({"t": input_parquet}, source, dest)


def test_a_declared_transform_that_returns_nothing_says_which_function(
    input_parquet: str, tmp_path
) -> None:
    """The script shape's message - "did not set a variable named `output`" -
    is advice for a file that does not have one, and printing it here would
    send somebody looking for an assignment their file is not supposed to
    contain."""
    dest = str(tmp_path / "out.parquet")
    source = "@transform(output='daily', inputs={'t': 'raw'})\ndef build(t):\n    t.copy()\n"
    with pytest.raises(DatasetEngineError, match="build returned nothing"):
        run_python_transform({"t": input_parquet}, source, dest)


def test_two_declared_transforms_are_refused_rather_than_picked(
    input_parquet: str, tmp_path
) -> None:
    """The publisher refuses this (`transform_declarations`), so reaching it
    means the file changed between publish and run. Running the first would
    make "what was declared" and "what ran" two different sentences, which is
    the property `model_runs.model_version` exists to keep singular."""
    dest = str(tmp_path / "out.parquet")
    source = (
        "@transform(output='a', inputs={'t': 'raw'})\ndef one(t):\n    return t\n\n"
        "@transform(output='b', inputs={'t': 'raw'})\ndef two(t):\n    return t\n"
    )
    with pytest.raises(DatasetEngineError, match="more than one transform"):
        run_python_transform({"t": input_parquet}, source, dest)


def test_the_script_shape_still_wins_when_a_file_has_both(
    input_parquet: str, tmp_path
) -> None:
    """**The old shape is not merely still supported, it takes precedence.**

    Every model authored before repositories is a script, and a run is stamped
    to the exact code that produced it (decision 0001) - so a change that made
    an old definition mean something new would rewrite history rather than
    extend it. A file with both is a script that also declares, and the
    assignment is what ran last.
    """
    dest = str(tmp_path / "out.parquet")
    source = (
        "@transform(output='daily', inputs={'t': 'raw'})\n"
        "def build(t):\n    return t.head(1)\n\n"
        "output = t\n"
    )
    _, rows = run_python_transform({"t": input_parquet}, source, dest)
    assert rows == 2, "the decorated function's one row won over the script's two"


def test_a_file_with_neither_says_both_things_it_could_have_done(
    input_parquet: str, tmp_path
) -> None:
    """There are two ways to produce a table now, so the refusal names both.
    A message about only `output` would be advice to write the shape the
    author may deliberately not be writing."""
    dest = str(tmp_path / "out.parquet")
    with pytest.raises(DatasetEngineError, match="nor declared a transform"):
        run_python_transform({"t": input_parquet}, "x = 1", dest)


def test_a_comment_declared_script_runs_as_the_script_it_is(
    input_parquet: str, tmp_path
) -> None:
    """§273's form, run here on purpose rather than only parsed over there.

    §272's whole finding was two halves each thorough about itself and never
    tested against each other, so a new declaration form gets a test on *this*
    side of the seam the same day it gets one on the reader's side. The
    declaration is comments; Python ignores comments; so this must behave
    exactly like the bare script - which is the claim, and claims get asserted.
    """
    dest = str(tmp_path / "out.parquet")
    source = "# output: daily\n# input: t = raw\n\noutput = t.copy()\n"
    _, rows = run_python_transform({"t": input_parquet}, source, dest)
    assert rows == 2
    result = duckdb.connect().execute(
        f"SELECT * FROM read_parquet('{dest}') ORDER BY id"
    ).fetchall()
    assert result == [(1, "a"), (2, "b")]
