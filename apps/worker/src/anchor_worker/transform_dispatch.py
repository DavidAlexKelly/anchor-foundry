"""Dispatching a transform to the runner task (decision 0004, `STATUS.md` §66).

This is the worker's half of the contract `transform_runner.py` describes from
inside the container. The runner can reach nothing and holds no credentials;
everything it needs arrives as files, and everything it produces leaves as
files. This module is what puts them there and takes them away.

**One filesystem, two paths.** The worker and the runner mount the *same* EFS
access point at different places - `/transform-scratch` in the worker,
`/work` in the runner. So a run directory is one directory with two names, and
every path written into `job.json` must be the runner's. Getting this backwards
would produce a container that starts, finds nothing, and reports a missing
input - which reads like a caller bug and is in fact a mount bug.

**The result file is the answer; the exit code is not consulted.** A run that
wrote `result.json` has an answer in it, failure included. A run that wrote
none did not get far enough to have one, and *that* is an infrastructure
problem with a different owner - reported here as `DispatchError` carrying
whatever ECS said about why the task stopped, because "OutOfMemoryError" is
the useful sentence and "your transform failed" would be a lie. §65 built that
distinction inside the container; it only pays off if the caller honours it,
and this is the caller.

Deliberately split into `stage` / `start` / `wait` / `collect` rather than one
call: the pieces are the same pieces ECS has, and a caller that wants to record
a task ARN against a run row - or stop waiting and come back - can. Use
`run_transform` when none of that matters.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

SCRATCH_ROOT_ENV = "ANCHOR_TRANSFORM_SCRATCH"
DEFAULT_SCRATCH_ROOT = "/transform-scratch"
CLUSTER_ENV = "ANCHOR_TRANSFORM_CLUSTER"
TASK_DEFINITION_ENV = "ANCHOR_TRANSFORM_TASK_DEFINITION"
SUBNETS_ENV = "ANCHOR_TRANSFORM_SUBNETS"
SECURITY_GROUPS_ENV = "ANCHOR_TRANSFORM_SECURITY_GROUPS"

# Must match the container name in the runner task definition (infra/cdk
# services.ts) - `containerOverrides` are matched by name, and ECS rejects an
# override naming a container the task definition does not have.
CONTAINER_NAME = "runner"
# Where the runner mounts the scratch filesystem. Matches the mount point in
# the runner task definition, and is the reason `runner_work_dir` exists.
RUNNER_MOUNT = "/work"

JOB_FILE = "job.json"
RESULT_FILE = "result.json"

# Generous, because it covers ECS's own start-up: pulling the image and
# attaching an ENI is often a minute before a line of the transform runs. The
# transform's own share of this is closer to python_sandbox's 300s.
DEFAULT_TIMEOUT_S = 900
DEFAULT_POLL_INTERVAL_S = 5.0

# ECS lifecycle: the only state that means "there is nothing more to wait for".
STOPPED = "STOPPED"

_SAFE_ALIAS = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class DispatchError(Exception):
    """The platform did not manage to run the transform. Not the author's
    fault, and not to be reported as though it were."""


class TransformFailed(Exception):
    """The transform ran and was wrong. `error` is the runner's own message,
    written by whoever's code raised."""

    def __init__(self, error: str) -> None:
        super().__init__(error)
        self.error = error


@dataclass(frozen=True)
class TransformJob:
    code: str
    """The transform source, as committed."""
    inputs: dict[str, str] = field(default_factory=dict)
    """alias -> path to a Parquet file *on the worker*. Copied into the run
    directory; the runner only ever sees the copy."""
    code_filename: str = "transform.py"
    output_filename: str = "output.parquet"


@dataclass(frozen=True)
class RunHandle:
    run_id: str
    work_dir: str
    """The run directory as the worker sees it."""
    runner_work_dir: str
    """The same directory as the runner sees it. Not derivable from
    `work_dir` - they are two mounts of one filesystem."""
    output_filename: str
    task_arn: str | None = None

    def with_task(self, task_arn: str) -> "RunHandle":
        return RunHandle(
            run_id=self.run_id,
            work_dir=self.work_dir,
            runner_work_dir=self.runner_work_dir,
            output_filename=self.output_filename,
            task_arn=task_arn,
        )


def scratch_root() -> str:
    return os.environ.get(SCRATCH_ROOT_ENV, DEFAULT_SCRATCH_ROOT)


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise DispatchError(
            f"{name} is not set - this worker has no transform runner configured, "
            "so it cannot run Python transforms"
        )
    return value


def _ecs_client():
    import boto3  # imported here so staging and collecting work without it

    return boto3.client("ecs")


# ---- staging -----------------------------------------------------------------
def stage(job: TransformJob, *, root: str | None = None, run_id: str | None = None) -> RunHandle:
    """Write a run's directory. The runner reads nothing else, ever."""
    base = root or scratch_root()
    run_id = run_id or uuid.uuid4().hex
    work_dir = os.path.join(base, run_id)
    os.makedirs(work_dir, exist_ok=False)

    staged: dict[str, str] = {}
    for alias, source in job.inputs.items():
        if not _SAFE_ALIAS.match(alias):
            # The alias becomes a file name and a Python name inside the
            # transform. Refused rather than sanitised: a silently renamed
            # input would bind to a name the author's code does not use.
            raise DispatchError(
                f"input alias {alias!r} is not a plain identifier - rename it in the "
                "transform's declaration"
            )
        if not os.path.exists(source):
            raise DispatchError(f"input {alias!r} was not found at {source}")
        name = f"{alias}.parquet"
        shutil.copyfile(source, os.path.join(work_dir, name))
        staged[alias] = name

    with open(os.path.join(work_dir, job.code_filename), "w") as handle:
        handle.write(job.code)
    with open(os.path.join(work_dir, JOB_FILE), "w") as handle:
        json.dump(
            {
                "code_path": job.code_filename,
                "output_path": job.output_filename,
                "inputs": staged,
            },
            handle,
        )
    return RunHandle(
        run_id=run_id,
        work_dir=work_dir,
        # The runner's view of the same directory. See the module docstring.
        runner_work_dir=f"{RUNNER_MOUNT}/{run_id}",
        output_filename=job.output_filename,
    )


# ---- running -----------------------------------------------------------------
def start(handle: RunHandle, *, client: Any = None) -> RunHandle:
    """RunTask against the runner task definition, and return a handle that
    knows the task's ARN."""
    client = client or _ecs_client()
    cluster = _required(CLUSTER_ENV)
    response = client.run_task(
        cluster=cluster,
        taskDefinition=_required(TASK_DEFINITION_ENV),
        launchType="FARGATE",
        count=1,
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": _required(SUBNETS_ENV).split(","),
                "securityGroups": _required(SECURITY_GROUPS_ENV).split(","),
                # Private subnets, and a security group with no route out. Both
                # would be undone by a public IP.
                "assignPublicIp": "DISABLED",
            }
        },
        overrides={
            "containerOverrides": [
                {
                    "name": CONTAINER_NAME,
                    # The only per-run instruction the runner receives. Not the
                    # job itself: a command line is visible in the ECS console
                    # and in CloudTrail, and a transform's inputs are the
                    # customer's data.
                    "environment": [
                        {"name": "ANCHOR_TRANSFORM_WORKDIR", "value": handle.runner_work_dir}
                    ],
                }
            ]
        },
    )
    failures = response.get("failures") or []
    tasks = response.get("tasks") or []
    if not tasks:
        # RunTask returns 200 with an empty task list when placement fails, so
        # a caller that only checked for an exception would carry on waiting
        # for a task that was never created.
        reason = "; ".join(
            f"{f.get('reason', 'unknown')} ({f.get('arn', 'no arn')})" for f in failures
        ) or "ECS accepted the request but started no task, and gave no reason"
        raise DispatchError(f"the transform runner task did not start: {reason}")
    return handle.with_task(tasks[0]["taskArn"])


def wait(
    handle: RunHandle,
    *,
    client: Any = None,
    timeout_s: float | None = None,
    poll_interval_s: float | None = None,
) -> str:
    """Block until the task stops. Returns ECS's `stoppedReason`, which is the
    only diagnosis available when the run left no result file.

    The two limits default to the module constants *at call time*, not in the
    signature: a default argument binds when the function is defined, so a
    caller or a test that changed the constant would have changed nothing and
    not been told.
    """
    if handle.task_arn is None:
        raise DispatchError("this run was never started")
    timeout_s = DEFAULT_TIMEOUT_S if timeout_s is None else timeout_s
    poll_interval_s = DEFAULT_POLL_INTERVAL_S if poll_interval_s is None else poll_interval_s
    client = client or _ecs_client()
    cluster = _required(CLUSTER_ENV)
    deadline = time.monotonic() + timeout_s
    while True:
        described = client.describe_tasks(cluster=cluster, tasks=[handle.task_arn])
        tasks = described.get("tasks") or []
        if not tasks:
            # ECS forgets stopped tasks after about an hour. Nothing to read,
            # but the result file may well be there - so this is not fatal on
            # its own and `collect` gets the final word.
            return "the task is no longer known to ECS"
        task = tasks[0]
        if task.get("lastStatus") == STOPPED:
            return str(task.get("stoppedReason") or "the task stopped without a reason")
        if time.monotonic() >= deadline:
            # Stop it rather than leaving it running: a transform in an
            # infinite loop would otherwise burn a Fargate task until somebody
            # noticed the bill.
            try:
                client.stop_task(
                    cluster=cluster, task=handle.task_arn, reason="transform exceeded its time limit"
                )
            except Exception:  # noqa: BLE001 - the timeout is the news, not this
                pass
            raise DispatchError(
                f"the transform did not finish within {timeout_s:.0f}s and was stopped"
            )
        time.sleep(poll_interval_s)


# ---- reading the answer ------------------------------------------------------
def collect(handle: RunHandle, *, output_path: str | None = None, stopped_reason: str = "") -> dict:
    """Read `result.json` and, on success, move the output where the caller
    asked. Raises `TransformFailed` if the transform was wrong and
    `DispatchError` if it never got far enough to say."""
    result_file = os.path.join(handle.work_dir, RESULT_FILE)
    if not os.path.exists(result_file):
        detail = f": {stopped_reason}" if stopped_reason else ""
        raise DispatchError(
            f"the transform run produced no result file, so it never reported an outcome{detail}"
        )
    with open(result_file) as handle_in:
        payload = json.load(handle_in)

    if payload.get("status") == "failed":
        raise TransformFailed(str(payload.get("error") or "the transform failed without a message"))
    if payload.get("status") != "ok":
        raise DispatchError(f"the result file has an unrecognised status: {payload.get('status')!r}")

    produced = os.path.join(handle.work_dir, handle.output_filename)
    if not os.path.exists(produced):
        # The result says ok and the output is not there. Refusing beats
        # recording a successful run against a dataset version with no bytes.
        raise DispatchError(
            f"the result file says the run succeeded but {handle.output_filename} is not there"
        )
    if output_path is not None:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        shutil.move(produced, output_path)
    return payload


def cleanup(handle: RunHandle) -> None:
    """Remove the run directory. Scratch is shared and a run that leaves its
    inputs behind leaves the customer's data behind."""
    shutil.rmtree(handle.work_dir, ignore_errors=True)


# ---- the whole thing ---------------------------------------------------------
def run_transform(
    job: TransformJob,
    *,
    output_path: str,
    client: Any = None,
    root: str | None = None,
    timeout_s: float | None = None,
    poll_interval_s: float | None = None,
) -> dict:
    handle = stage(job, root=root)
    try:
        handle = start(handle, client=client)
        reason = wait(
            handle, client=client, timeout_s=timeout_s, poll_interval_s=poll_interval_s
        )
        return collect(handle, output_path=output_path, stopped_reason=reason)
    finally:
        cleanup(handle)


# ---- which of the two Python paths a deployment uses -------------------------
_CONFIG_ENV = (CLUSTER_ENV, TASK_DEFINITION_ENV, SUBNETS_ENV, SECURITY_GROUPS_ENV)


def isolation_mode() -> str:
    """`"runner"` or `"subprocess"` - where this worker's Python transforms run.

    All four settings or none. **A half-configured worker is refused rather
    than quietly downgraded**: somebody who set three of these meant to use the
    runner, and falling back to `python_sandbox` would silently run customer
    code under process isolation that §63 is explicit is not a security
    boundary. A deployment that thought it had the isolation and did not is a
    worse outcome than a worker that will not start a transform.
    """
    present = [name for name in _CONFIG_ENV if os.environ.get(name)]
    if len(present) == len(_CONFIG_ENV):
        return "runner"
    if not present:
        return "subprocess"
    missing = [name for name in _CONFIG_ENV if not os.environ.get(name)]
    raise DispatchError(
        "this worker is half-configured for the transform runner - "
        f"set {', '.join(missing)} or unset {', '.join(present)}, because running "
        "customer Python in the worker's own process is not the isolation the "
        "other setting asks for"
    )


def run_python_transform(input_paths: dict[str, str], code: str, dest_parquet: str):
    """The single place that decides where customer Python runs, with the
    signature `python_sandbox.run_python_transform` already had so the model
    run path does not care which it got.

    Errors are normalised to `DatasetEngineError` - the model run records one
    message either way - but an infrastructure failure is prefixed so the
    sentence says whose problem it is. That is weaker than §67's exception
    types, and deliberately: `model_runs.status` has no value between
    'succeeded' and 'failed', so today the distinction survives in the text and
    nowhere else.
    """
    from .dataset_engine import ColumnSchema, DatasetEngineError

    if isolation_mode() == "subprocess":
        from .python_sandbox import run_python_transform as in_process

        return in_process(input_paths, code, dest_parquet)

    try:
        payload = run_transform(
            TransformJob(code=code, inputs=dict(input_paths)), output_path=dest_parquet
        )
    except TransformFailed as exc:
        raise DatasetEngineError(exc.error[:500]) from exc
    except DispatchError as exc:
        raise DatasetEngineError(f"the platform could not run this transform: {exc}") from exc
    schema = [
        ColumnSchema(name=c["name"], data_type=c["data_type"]) for c in payload.get("schema", [])
    ]
    return schema, int(payload.get("row_count", 0))
