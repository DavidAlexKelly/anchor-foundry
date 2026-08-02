"""Dispatching a transform to the runner task (decision 0004, `STATUS.md` §66).

Runs against a real `moto.server` process over HTTP - a real boto3 ECS client,
a real VPC and subnet, real RunTask/DescribeTasks/StopTask calls - and a real
directory standing in for the EFS mount. Skips if moto is absent.

**What stands in for the container.** Nothing here runs a Fargate task, so
where ECS would start the runner, these tests call `transform_runner.main()`
against the staged directory. That is the actual entrypoint, not a stub: the
files it reads and the `result.json` it writes are the same ones the container
would produce, which is the whole of the contract this module is on the other
end of.

The load-bearing test is `test_a_run_that_left_no_result_file_...`. Everything
else here would still work if the dispatcher confused a failed transform with
failed infrastructure; that one would not, and telling them apart is what §65
built and this module exists to honour.

**One branch is deliberately unproven**: `RunTask` returning HTTP 200 with an
empty `tasks` list and a `failures` entry (capacity, a subnet with no
addresses). moto always places the task, so nothing here can produce that
shape. The handling stays because the alternative - a caller that waits for a
task ARN it never received - is the failure this whole module is written to
avoid.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

pytest.importorskip("moto", reason="moto not installed")
import boto3  # noqa: E402

from anchor_worker import transform_dispatch as dispatch  # noqa: E402
from anchor_worker import transform_runner as runner  # noqa: E402

REGION = "eu-west-2"
CLUSTER = "platform"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def aws_endpoint():
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "moto.server", "-p", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.25)
    else:  # pragma: no cover - environment guard
        proc.terminate()
        pytest.skip("moto server did not start")
    yield f"http://127.0.0.1:{port}"
    proc.terminate()
    proc.wait(timeout=10)


def _client(service: str, endpoint: str):
    return boto3.client(
        service,
        endpoint_url=endpoint,
        region_name=REGION,
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )


@pytest.fixture(scope="module")
def ecs(aws_endpoint: str):
    """A cluster, a network and a runner task definition, shaped like the ones
    infra/cdk builds."""
    ec2 = _client("ec2", aws_endpoint)
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    subnet = ec2.create_subnet(VpcId=vpc, CidrBlock="10.0.1.0/24")["Subnet"]["SubnetId"]
    group = ec2.create_security_group(
        GroupName="transform-runner", Description="runner", VpcId=vpc
    )["GroupId"]

    client = _client("ecs", aws_endpoint)
    client.create_cluster(clusterName=CLUSTER)
    task_def = client.register_task_definition(
        family="transform-runner",
        requiresCompatibilities=["FARGATE"],
        networkMode="awsvpc",
        cpu="1024",
        memory="2048",
        containerDefinitions=[
            {
                "name": dispatch.CONTAINER_NAME,
                "image": "runner:test",
                "essential": True,
                # moto computes placement from the container's own reservation
                # and cannot read the task-level one; real Fargate takes the
                # task-level values. Set here only so RunTask succeeds.
                "cpu": 1024,
                "memory": 2048,
            }
        ],
    )["taskDefinition"]["taskDefinitionArn"]

    os.environ[dispatch.CLUSTER_ENV] = CLUSTER
    os.environ[dispatch.TASK_DEFINITION_ENV] = task_def
    os.environ[dispatch.SUBNETS_ENV] = subnet
    os.environ[dispatch.SECURITY_GROUPS_ENV] = group
    yield client
    for name in (
        dispatch.CLUSTER_ENV,
        dispatch.TASK_DEFINITION_ENV,
        dispatch.SUBNETS_ENV,
        dispatch.SECURITY_GROUPS_ENV,
    ):
        os.environ.pop(name, None)


@pytest.fixture()
def scratch(tmp_path):
    """The EFS mount, as the worker sees it."""
    root = tmp_path / "transform-scratch"
    root.mkdir()
    return str(root)


def make_parquet(path: str, rows: list[tuple[int, str]]) -> str:
    import duckdb

    con = duckdb.connect()
    con.execute(
        "CREATE TABLE t AS SELECT * FROM (VALUES "
        + ", ".join(f"({i}, '{r}')" for i, r in rows)
        + ") AS v(id, region)"
    )
    con.execute(f"COPY t TO '{path}' (FORMAT parquet)")
    return path


def run_the_container(handle: dispatch.RunHandle) -> int:
    """What ECS would do. The real entrypoint, against the staged directory."""
    previous = os.environ.get(runner.WORK_DIR_ENV)
    os.environ[runner.WORK_DIR_ENV] = handle.work_dir
    try:
        return runner.main()
    finally:
        if previous is None:
            os.environ.pop(runner.WORK_DIR_ENV, None)
        else:
            os.environ[runner.WORK_DIR_ENV] = previous


def stop(ecs_client, handle: dispatch.RunHandle, reason: str = "Essential container in task exited") -> None:
    ecs_client.stop_task(cluster=CLUSTER, task=handle.task_arn, reason=reason)


# ---- the happy path ----------------------------------------------------------
def test_a_transform_runs_and_its_output_arrives_where_the_caller_asked(
    ecs, scratch, tmp_path
) -> None:
    orders = make_parquet(str(tmp_path / "orders.parquet"), [(1, "north"), (2, "south"), (3, "north")])
    job = dispatch.TransformJob(
        code='output = orders[orders["region"] == "north"]\n',
        inputs={"orders": orders},
    )

    handle = dispatch.start(dispatch.stage(job, root=scratch), client=ecs)
    run_the_container(handle)
    stop(ecs, handle)

    reason = dispatch.wait(handle, client=ecs, poll_interval_s=0)
    destination = str(tmp_path / "out" / "result.parquet")
    payload = dispatch.collect(handle, output_path=destination, stopped_reason=reason)

    assert payload["row_count"] == 2
    assert [c["name"] for c in payload["schema"]] == ["id", "region"]
    assert os.path.exists(destination)


# ---- the distinction that matters --------------------------------------------
def test_a_failing_transform_is_the_author_s_problem_and_says_so(ecs, scratch, tmp_path) -> None:
    handle = dispatch.start(
        dispatch.stage(dispatch.TransformJob(code="output = 1 / 0\n"), root=scratch), client=ecs
    )
    run_the_container(handle)
    stop(ecs, handle)
    reason = dispatch.wait(handle, client=ecs, poll_interval_s=0)

    with pytest.raises(dispatch.TransformFailed) as raised:
        dispatch.collect(handle, stopped_reason=reason)
    assert "ZeroDivisionError" in raised.value.error


def test_a_run_that_left_no_result_file_is_an_infrastructure_failure(ecs, scratch) -> None:
    """The container never got far enough to have an opinion. Reporting this as
    a failed transform would send somebody to read code that is fine, so the
    refusal says what actually happened and carries what ECS said."""
    handle = dispatch.start(
        dispatch.stage(dispatch.TransformJob(code="output = 1\n"), root=scratch), client=ecs
    )
    # No container runs. The task stops the way an out-of-memory kill does.
    stop(ecs, handle, reason="OutOfMemoryError: Container killed due to memory usage")
    reason = dispatch.wait(handle, client=ecs, poll_interval_s=0)

    with pytest.raises(dispatch.DispatchError) as raised:
        dispatch.collect(handle, stopped_reason=reason)
    message = str(raised.value)
    assert "no result file" in message
    assert "OutOfMemoryError" in message, "the only diagnosis available must survive"


# ---- the mount mapping -------------------------------------------------------
def test_the_runner_is_told_its_own_path_not_the_worker_s(ecs, scratch) -> None:
    """One filesystem, two mounts. The worker's path would be a directory the
    runner does not have, and the symptom - a container reporting a missing
    job file - reads like a caller bug rather than a mount bug."""
    handle = dispatch.stage(dispatch.TransformJob(code="output = 1\n"), root=scratch)
    assert handle.work_dir.startswith(scratch)
    assert handle.runner_work_dir == f"{dispatch.RUNNER_MOUNT}/{handle.run_id}"

    started = dispatch.start(handle, client=ecs)
    task = ecs.describe_tasks(cluster=CLUSTER, tasks=[started.task_arn])["tasks"][0]
    overrides = task["overrides"]["containerOverrides"][0]
    assert overrides["name"] == dispatch.CONTAINER_NAME
    environment = {e["name"]: e["value"] for e in overrides["environment"]}
    assert environment["ANCHOR_TRANSFORM_WORKDIR"] == handle.runner_work_dir
    assert scratch not in environment["ANCHOR_TRANSFORM_WORKDIR"]


def test_the_job_file_names_the_files_the_runner_will_find(scratch, tmp_path) -> None:
    """The runner refuses absolute paths and `..` (its own tests). The job file
    must therefore carry bare names, and the inputs must actually be there."""
    import json

    orders = make_parquet(str(tmp_path / "src.parquet"), [(1, "north")])
    handle = dispatch.stage(
        dispatch.TransformJob(code="output = orders\n", inputs={"orders": orders}), root=scratch
    )
    with open(os.path.join(handle.work_dir, dispatch.JOB_FILE)) as f:
        job = json.load(f)
    assert job["inputs"] == {"orders": "orders.parquet"}
    assert os.path.exists(os.path.join(handle.work_dir, "orders.parquet"))
    assert os.path.exists(os.path.join(handle.work_dir, "transform.py"))


# ---- refusals ----------------------------------------------------------------
def test_an_input_alias_that_is_not_a_plain_name_is_refused(scratch, tmp_path) -> None:
    """The alias becomes both a file name and the name the transform's code
    binds. Sanitising it silently would bind a name the author never wrote."""
    orders = make_parquet(str(tmp_path / "src.parquet"), [(1, "north")])
    with pytest.raises(dispatch.DispatchError, match="plain identifier"):
        dispatch.stage(
            dispatch.TransformJob(code="output = 1\n", inputs={"../escape": orders}), root=scratch
        )


def test_a_missing_input_is_refused_before_a_task_is_started(scratch, tmp_path) -> None:
    with pytest.raises(dispatch.DispatchError, match="was not found"):
        dispatch.stage(
            dispatch.TransformJob(code="output = 1\n", inputs={"orders": str(tmp_path / "gone.parquet")}),
            root=scratch,
        )


def test_a_result_claiming_success_with_no_output_is_refused(ecs, scratch) -> None:
    """Recording a successful run against a dataset version with no bytes is
    the quietly-wrong outcome; refusing is the loud one."""
    import json

    handle = dispatch.stage(dispatch.TransformJob(code="output = 1\n"), root=scratch)
    with open(os.path.join(handle.work_dir, dispatch.RESULT_FILE), "w") as f:
        json.dump({"status": "ok", "row_count": 1, "schema": []}, f)

    with pytest.raises(dispatch.DispatchError, match="is not there"):
        dispatch.collect(handle)


def test_a_worker_with_no_runner_configured_says_so(scratch, monkeypatch) -> None:
    monkeypatch.delenv(dispatch.CLUSTER_ENV, raising=False)
    handle = dispatch.stage(dispatch.TransformJob(code="output = 1\n"), root=scratch)
    with pytest.raises(dispatch.DispatchError, match="no transform runner configured"):
        dispatch.start(handle, client=object())


# ---- not waiting forever -----------------------------------------------------
def test_a_transform_that_overruns_is_stopped_rather_than_left_running(ecs, scratch) -> None:
    """An infinite loop would otherwise burn a Fargate task until somebody
    noticed the bill."""
    handle = dispatch.start(
        dispatch.stage(dispatch.TransformJob(code="output = 1\n"), root=scratch), client=ecs
    )
    with pytest.raises(dispatch.DispatchError, match="did not finish within"):
        dispatch.wait(handle, client=ecs, timeout_s=0, poll_interval_s=0)

    task = ecs.describe_tasks(cluster=CLUSTER, tasks=[handle.task_arn])["tasks"][0]
    assert task["lastStatus"] == dispatch.STOPPED
    assert "time limit" in task.get("stoppedReason", "")


def test_waiting_on_a_run_that_was_never_started_is_refused(scratch) -> None:
    handle = dispatch.stage(dispatch.TransformJob(code="output = 1\n"), root=scratch)
    with pytest.raises(dispatch.DispatchError, match="never started"):
        dispatch.wait(handle, client=object())


# ---- the scratch share is shared ---------------------------------------------
def test_a_run_does_not_leave_the_customer_s_data_on_the_share(ecs, scratch, tmp_path) -> None:
    """Scratch is one filesystem every run shares. A run that leaves its inputs
    behind leaves the customer's data behind, and `run_transform` is the path
    that has to get this right even when the transform failed."""
    orders = make_parquet(str(tmp_path / "orders.parquet"), [(1, "north")])
    job = dispatch.TransformJob(code="output = 1 / 0\n", inputs={"orders": orders})

    staged: list[dispatch.RunHandle] = []
    real_stage = dispatch.stage

    def capture(*args, **kwargs):
        handle = real_stage(*args, **kwargs)
        staged.append(handle)
        # ECS's turn, at the only moment the directory is fully staged.
        run_the_container(handle)
        return handle

    dispatch.stage = capture  # type: ignore[assignment]
    try:
        with pytest.raises(dispatch.TransformFailed):
            dispatch.run_transform(
                job,
                output_path=str(tmp_path / "out.parquet"),
                client=ecs,
                root=scratch,
                poll_interval_s=0,
            )
    finally:
        dispatch.stage = real_stage  # type: ignore[assignment]

    assert staged, "run_transform did not stage anything"
    assert not os.path.exists(staged[0].work_dir)
    assert os.listdir(scratch) == []
