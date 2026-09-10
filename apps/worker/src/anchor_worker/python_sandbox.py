"""Python model transform execution - the worker slice the spec's "isolated
worker runtime" note anticipated (SQL transforms run inline in the API,
sandboxed via DuckDB's `enable_external_access` switch; Python needs a real
process boundary DuckDB can't give it, which is why the API rejects
language='python' at run time and leaves the run 'queued' for this module).

Honesty about what this actually is, flagged clearly: this is process-level
isolation - a fresh OS process, capped CPU/memory, a wall-clock timeout, and
a stripped environment - not a hard multi-tenant security boundary. It does
not stop the transform from opening a network socket or reading files
outside its working directory; that needs a real sandbox (gVisor, a
Firecracker microVM, a network-denied container) applied at the worker's
deployment layer, which is a production hardening step out of scope for
this build. Treat this the same way the rest of this platform treats size
caps: a conservative day-one boundary, not the final word.

Contract with user code: **two shapes, and the file says which** (§272).

*The declared transform* — what `docs/decisions/0004-running-customer-code.md`
shows, what `transform_declarations.py` parses, and the shape a file published
from a repository is written in:

    @transform(output="daily_orders", inputs={"orders": "raw_orders"})
    def build(orders):
        return orders

*The script* — every model authored directly in the Models editor since before
repositories existed: each input arrives as a plain module-level name and the
script assigns its result to `output`.

**These had never met, and the first one could not run.** Decision 0004
documents the decorator; this file documented the script; each was right about
itself. A repository-authored Python transform died on `NameError: name
'transform' is not defined` before reaching any of the sandbox's actual
limits - and if `transform` had been defined as a no-op, the function's return
value still went nowhere, because nothing called it. Neither half was wrong;
they were two contracts for one thing, written eleven units apart, and no test
used a `.py` file on the publish path or a decorator in this one.

The script shape stays because every existing model is written in it, and a
run is stamped to the exact code that produced it (0001) - a contract change
that broke old definitions would rewrite history rather than extend it.
"""
from __future__ import annotations

import os
import resource
import subprocess
import sys
import tempfile
from typing import Any

from . import user_api
from .dataset_engine import ColumnSchema, DatasetEngineError

DEFAULT_TIMEOUT_S = 300
MEMORY_LIMIT_BYTES = 1024 * 1024 * 1024  # 1 GB, flag: worker-tier day-one cap
CPU_LIMIT_S = 120
MAX_OUTPUT_ROWS = 5_000_000  # matches the SQL transform's day-one cap

_RUNNER_TEMPLATE = """
import json
import sys

import duckdb

_inputs = {inputs!r}
_namespace: dict = {{}}
for _alias, _path in _inputs.items():
    _namespace[_alias] = duckdb.connect().execute(
        f"SELECT * FROM read_parquet({{_path!r}})"
    ).df()

# **The decorator, imported rather than defined** (§292). It used to be
# written out here: a `transform` function and a shim `anchor` object built in
# this template, so that a file saying `@transform(...)` could find one. That
# was enough to *run* a transform and not enough to **import** one, which is a
# unit test's first line - `import anchor` found no module, because there was
# no such file anywhere on disk. So `user_api.py` is copied in beside the code
# as `anchor.py` and this reads the same decorator the tests do.
#
# Both spellings, because the declaration reader accepts both
# (`_decorator_name`), and a spelling that parses as a declaration and then
# dies on NameError is the same defect in its second form.
import anchor

_namespace["transform"] = anchor.transform
_namespace["anchor"] = anchor

with open({code_path!r}) as _f:
    _user_code = _f.read()

try:
    exec(compile(_user_code, "<model>", "exec"), _namespace)
except Exception as exc:
    print(f"MODEL_ERROR: {{type(exc).__name__}}: {{exc}}", file=sys.stderr)
    sys.exit(1)

# **The shape rules live in `anchor`, not here** (§292). They used to be
# written out in this template and again, differently and incompletely, in
# `transform_runner.py` - the container that runs this in production, which
# never bound `transform` at all. One implementation, imported by both.
try:
    _output = anchor.resolve_output(_namespace)
except anchor.ShapeError as exc:
    print(f"MODEL_ERROR: {{exc}}", file=sys.stderr)
    sys.exit(1)
except Exception as exc:
    print(f"MODEL_ERROR: {{type(exc).__name__}}: {{exc}}", file=sys.stderr)
    sys.exit(1)

_con = duckdb.connect()
_con.register("_output_df", _output)
try:
    _con.execute(f"COPY _output_df TO {dest_path!r} (FORMAT parquet)")
    _schema = _con.execute("DESCRIBE _output_df").fetchall()
    _row_count = _con.execute("SELECT count(*) FROM _output_df").fetchone()[0]
except duckdb.Error as exc:
    print(f"MODEL_ERROR: output is not a valid table: {{exc}}", file=sys.stderr)
    sys.exit(1)

print(json.dumps({{
    "schema": [{{"name": r[0], "data_type": r[1]}} for r in _schema],
    "row_count": int(_row_count),
}}))
"""


def _limit_resources() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_LIMIT_S, CPU_LIMIT_S))
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))


def run_python_transform(
    inputs: dict[str, str],
    code: str,
    dest_parquet: str,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> tuple[list[ColumnSchema], int]:
    os.makedirs(os.path.dirname(dest_parquet), exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        user_api.write_into(tmp)
        code_path = os.path.join(tmp, "model.py")
        with open(code_path, "w") as f:
            f.write(code)
        runner_path = os.path.join(tmp, "runner.py")
        with open(runner_path, "w") as f:
            f.write(_RUNNER_TEMPLATE.format(inputs=inputs, code_path=code_path, dest_path=dest_parquet))

        env = {"PATH": "/usr/bin:/bin", "HOME": tmp}
        try:
            result = subprocess.run(
                [sys.executable, runner_path],
                cwd=tmp,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                preexec_fn=_limit_resources if os.name == "posix" else None,
            )
        except subprocess.TimeoutExpired as exc:
            raise DatasetEngineError(f"transform exceeded the {timeout_s}s time limit") from exc

        if result.returncode != 0:
            message = next(
                (line for line in result.stderr.splitlines() if line.startswith("MODEL_ERROR:")),
                None,
            )
            if message is None:
                stderr_lines = result.stderr.strip().splitlines()
                message = stderr_lines[-1] if stderr_lines else "transform failed"
            raise DatasetEngineError(message.removeprefix("MODEL_ERROR: ")[:500])

        import json

        try:
            payload: dict[str, Any] = json.loads(result.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError) as exc:
            raise DatasetEngineError("transform produced no readable output") from exc

    row_count = int(payload["row_count"])
    if row_count > MAX_OUTPUT_ROWS:
        raise DatasetEngineError(
            f"the transform produced {row_count:,} rows - above this build's "
            f"{MAX_OUTPUT_ROWS:,} row limit"
        )
    schema = [ColumnSchema(name=c["name"], data_type=c["data_type"]) for c in payload["schema"]]
    return schema, row_count


# ---- unit tests (§293; code-repositories.md §8, p.13-14) ---------------------
TEST_TIMEOUT_S = 300

#: pytest's own discovery rule, and deliberately not a new one. A repository's
#: authors already know it, `--junitxml` reports against it, and a second rule
#: here would mean a file this platform called a test and pytest did not - or
#: the reverse, which is worse, because it runs.
TEST_FILE_PREFIX = "test_"
TEST_FILE_SUFFIX = "_test.py"


def is_test_file(path: str) -> bool:
    """Whether pytest would collect this file, by pytest's rule."""
    if not path.endswith(".py"):
        return False
    name = path.rsplit("/", 1)[-1]
    return name.startswith(TEST_FILE_PREFIX) or name.endswith(TEST_FILE_SUFFIX)


def run_python_tests(
    files: dict[str, str],
    timeout_s: int = TEST_TIMEOUT_S,
) -> "unit_test_report.TestReport":
    """Run a repository's unit tests over the files it was given.

    **The working set, not a commit** - the same choice §286's Problems panel
    made, and for the same reason: the question an author asks is "does what I
    just typed pass", and a runner that could only answer for committed code
    would be answering a different one.

    The directory holds the repository's files, `anchor.py`, and nothing else.
    `PYTHONPATH` is that directory, so a test imports the transform under test
    by the path it has in the repository - `from src.daily import build` - which
    is what the author would write and what a checkout would do.

    Failures of the *tests* come back in the report. Failures of the *run* -
    pytest missing, a timeout, an unreadable report - are raised, because a
    caller that showed them as "your tests failed" would send the wrong person
    looking. That is `transform_runner.py`'s result-file distinction, in the
    shape this function has.
    """
    from . import unit_test_report

    with tempfile.TemporaryDirectory() as tmp:
        user_api.write_into(tmp)
        for path, content in files.items():
            target = os.path.join(tmp, path)
            os.makedirs(os.path.dirname(target) or tmp, exist_ok=True)
            with open(target, "w") as handle:
                handle.write(content)

        report_path = os.path.join(tmp, "_report.xml")
        # **No `PYTHONPATH`, and a mutant is why.** It used to be set to `tmp`
        # so that a test could import the transform under test by its
        # repository path, and deleting it changed nothing: `python -m pytest`
        # already puts the invocation directory first on `sys.path`, and the
        # invocation directory is `cwd` below. Two mechanisms for one promise
        # is how they come to disagree (§213), so the one that is load-bearing
        # is named where it lives - see `cwd`.
        env = {"PATH": "/usr/bin:/bin", "HOME": tmp,
               "PYTHONDONTWRITEBYTECODE": "1"}
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "--no-header",
                 "-p", "no:cacheprovider",
                 # **`xunit1`, for `file` and `line`.** pytest 8's default
                 # family writes a dotted `classname` and nothing else, so the
                 # only way back to a path is to guess that dots are slashes -
                 # which is wrong the moment a test lives in a class. A panel
                 # whose job is to open the failing test needs the file it is
                 # in, so ask for the format that says.
                 "-o", "junit_family=xunit1",
                 # **Rooted here, so nothing of ours is collected.** Without it
                 # pytest walks upwards looking for a config file and can find
                 # this repository's own - which would run our suite inside a
                 # customer's, an outcome no message would explain.
                 "--rootdir", tmp, f"--junitxml={report_path}", tmp],
                # **Load-bearing, not tidiness.** `python -m pytest` prepends
                # the invocation directory to `sys.path`, so this is what makes
                # `from src.daily import build` resolve to the repository's own
                # file. A change here breaks every test that imports the
                # transform it is testing.
                cwd=tmp,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                preexec_fn=_limit_resources if os.name == "posix" else None,
            )
        except subprocess.TimeoutExpired as exc:
            raise DatasetEngineError(
                f"the tests exceeded the {timeout_s}s time limit"
            ) from exc

        if not os.path.exists(report_path):
            # pytest itself could not run, or died before writing. Its own
            # stderr is the useful sentence - "No module named pytest" names
            # the problem and "your tests failed" does not.
            tail = (result.stderr or result.stdout or "").strip().splitlines()
            raise DatasetEngineError(
                "the test run produced no report: " + (tail[-1] if tail else "no output")
            )
        with open(report_path) as handle:
            return unit_test_report.parse_junit(handle.read())
