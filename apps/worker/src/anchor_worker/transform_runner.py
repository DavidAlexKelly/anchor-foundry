"""The container entrypoint for customer transform code (decision 0004).

`python -m anchor_worker.transform_runner` is what the transform runner task
definition runs, in a container with **no egress and a task role that grants
nothing**. Everything this module can reach is in its working directory,
because that is all there is: no S3 client, no database connection, no AWS
credentials worth having. It imports neither boto3 nor psycopg, and a test
asserts that.

The contract, both directions, is files in one directory:

    job.json        what to run, written by the caller before the task starts
    <inputs>.parquet
    <code>          the transform source
    output.parquet  written here on success
    result.json     written here always, and it is the *only* thing the caller
                    reads to find out what happened

**`result.json` existing is how the caller tells a failed transform from failed
infrastructure**, and that distinction is the reason this module writes it even
when the transform raises. A task that never started, ran out of memory, or was
killed leaves no result file - which is a different problem with a different
owner from "your SQL has a typo", and a caller that could not tell them apart
would report the wrong one to the wrong person.

Reuses the execution contract `python_sandbox.py` already established: each
input is a pandas DataFrame bound to its alias, and the script assigns its
result to `output`.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from dataclasses import dataclass
from typing import Any

WORK_DIR_ENV = "ANCHOR_TRANSFORM_WORKDIR"
DEFAULT_WORK_DIR = "/work"
JOB_FILE = "job.json"
RESULT_FILE = "result.json"

# Matches the SQL transform's cap. A transform that produces more than this has
# almost always lost a join condition, and finding out at write time is kinder
# than finding out when the dataset is queried.
MAX_OUTPUT_ROWS = 5_000_000


class TransformError(Exception):
    """The transform is wrong. Distinct from anything that goes wrong *around*
    the transform, which does not produce a result file at all."""


@dataclass(frozen=True)
class Job:
    code_path: str
    output_path: str
    inputs: dict[str, str]
    language: str = "python"


def read_job(work_dir: str) -> Job:
    path = os.path.join(work_dir, JOB_FILE)
    try:
        with open(path) as handle:
            raw = json.load(handle)
    except FileNotFoundError as exc:
        # Not a TransformError: nobody wrote the job, so there is no transform
        # to blame. Left to crash the container loudly.
        raise RuntimeError(f"no {JOB_FILE} in {work_dir} - the caller did not stage this run") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{path} is not valid JSON: {exc}") from exc

    inputs = raw.get("inputs") or {}
    if not isinstance(inputs, dict):
        raise RuntimeError("job.inputs must be an object of alias -> file name")
    for alias, name in inputs.items():
        # The caller writes these names, but a path that escapes the working
        # directory would defeat the point of there being one.
        if os.path.isabs(name) or ".." in name.split("/"):
            raise RuntimeError(f"input {alias!r} points outside the working directory")
    return Job(
        code_path=str(raw["code_path"]),
        output_path=str(raw.get("output_path", "output.parquet")),
        inputs={str(a): str(n) for a, n in inputs.items()},
        language=str(raw.get("language", "python")),
    )


def execute(work_dir: str, job: Job) -> dict[str, Any]:
    """Run the transform and write its output. Returns the result payload."""
    import duckdb  # imported here so `read_job` failures do not depend on it

    connection = duckdb.connect()
    namespace: dict[str, Any] = {}
    for alias, name in job.inputs.items():
        path = os.path.join(work_dir, name)
        if not os.path.exists(path):
            raise TransformError(f"input {alias!r} was not staged ({name} is missing)")
        namespace[alias] = connection.execute(
            "SELECT * FROM read_parquet(?)", [path]
        ).df()

    source_path = os.path.join(work_dir, job.code_path)
    try:
        with open(source_path) as handle:
            source = handle.read()
    except FileNotFoundError as exc:
        raise RuntimeError(f"the transform source {job.code_path} was not staged") from exc

    try:
        exec(compile(source, "<transform>", "exec"), namespace)
    except Exception as exc:
        # The author's own error. Carry the traceback but not this module's
        # frames - they are noise to whoever wrote the transform.
        raise TransformError(f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=-3)}") from exc

    output = namespace.get("output")
    if output is None:
        raise TransformError(
            "the transform finished without setting `output` - assign the table it "
            "produces to a variable of that name"
        )

    connection.register("_output", output)
    try:
        row_count = int(connection.execute("SELECT count(*) FROM _output").fetchone()[0])
        if row_count > MAX_OUTPUT_ROWS:
            raise TransformError(
                f"the transform produced {row_count:,} rows, over the {MAX_OUTPUT_ROWS:,} limit"
            )
        destination = os.path.join(work_dir, job.output_path)
        connection.execute(f"COPY _output TO '{destination}' (FORMAT parquet)")
        schema = connection.execute("DESCRIBE _output").fetchall()
    except TransformError:
        raise
    except Exception as exc:
        raise TransformError(f"`output` is not a table this can write: {exc}") from exc

    return {
        "status": "ok",
        "row_count": row_count,
        "schema": [{"name": row[0], "data_type": row[1]} for row in schema],
        "output_path": job.output_path,
    }


def write_result(work_dir: str, payload: dict[str, Any]) -> None:
    with open(os.path.join(work_dir, RESULT_FILE), "w") as handle:
        json.dump(payload, handle)


def main(argv: list[str] | None = None) -> int:
    work_dir = os.environ.get(WORK_DIR_ENV, DEFAULT_WORK_DIR)
    job = read_job(work_dir)  # deliberately outside the try: see the docstring
    try:
        payload = execute(work_dir, job)
    except TransformError as exc:
        write_result(work_dir, {"status": "failed", "error": str(exc)})
        # Non-zero so the task shows as failed in ECS as well as in the result
        # file - two places, because whoever is looking at one is often not
        # looking at the other.
        print(str(exc), file=sys.stderr)
        return 1
    write_result(work_dir, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
