"""A deployed worker runs its schedules (§883).

Dagster starts a schedule stopped until somebody turns it on in its web UI.
That UI was never reachable on a deployed stack, and whatever it turned on
lived on the task's disk, which a deploy replaces. So no deployed worker ran a
scheduled sync, model run, export, test or preview run, listener archive or
cleanup. §883 ran `dagster-daemon` locally for two minutes either side of the
change: no runs before, and a run of each every-minute poll per minute after.

And the runs it does start are forgotten once old, so their record cannot
fill the task's disk.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
import yaml
from dagster import DagsterInstance, DefaultScheduleStatus, execute_job, job, op, reconstructable

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from anchor_worker.jobs import dagster_runs  # noqa: E402

WORKER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAGSTER_YAML = os.path.join(WORKER, "dagster.yaml")
DOCKERFILE = os.path.join(WORKER, "Dockerfile")


def test_every_schedule_starts_running(monkeypatch) -> None:
    monkeypatch.setenv("WORKER_DATABASE_URL", "postgresql://unused@localhost/unused")
    from anchor_worker.definitions import defs

    stopped = [s.name for s in defs.schedules if s.default_status != DefaultScheduleStatus.RUNNING]
    assert defs.schedules and not stopped, f"stopped until somebody turns them on: {stopped}"


def test_the_image_runs_the_daemon_with_the_instance_settings() -> None:
    dockerfile = open(DOCKERFILE).read()
    assert "COPY dagster.yaml /opt/dagster/home/dagster.yaml" in dockerfile
    assert "DAGSTER_HOME=/opt/dagster/home" in dockerfile
    assert 'CMD ["dagster-daemon", "run", "-m", "anchor_worker.definitions"]' in dockerfile


@pytest.fixture()
def instance(tmp_path, monkeypatch) -> DagsterInstance:
    """The image's instance settings, in a directory of the test's own."""
    home = tmp_path / "dagster"
    home.mkdir()
    settings = open(DAGSTER_YAML).read().replace("/opt/dagster/home", str(home))
    (home / "dagster.yaml").write_text(settings)
    monkeypatch.setenv("DAGSTER_HOME", str(home))
    with DagsterInstance.get() as made:
        yield made


@op
def _works() -> int:
    return 1


@op
def _fails() -> int:
    raise RuntimeError("as intended")


@job
def _succeeding():
    _works()


@job
def _failing():
    _fails()


def _succeeding_job():
    return _succeeding


def _failing_job():
    return _failing


def test_the_settings_load_and_keep_one_event_log(instance: DagsterInstance) -> None:
    settings = yaml.safe_load(open(DAGSTER_YAML))
    assert settings["event_log_storage"]["class"] == "ConsolidatedSqliteEventLogStorage"
    assert settings["compute_logs"]["class"] == "NoOpComputeLogManager"
    execute_job(reconstructable(_succeeding_job), instance=instance)
    history = os.path.join(os.environ["DAGSTER_HOME"], "history")
    assert sorted(os.listdir(history)) == ["event_log.db", "runs.db"]


def _prune(instance: DagsterInstance, now: datetime) -> int:
    from dagster import build_op_context

    original = dagster_runs._now
    dagster_runs._now = lambda: now
    try:
        return dagster_runs.prune_dagster_runs(build_op_context(instance=instance))
    finally:
        dagster_runs._now = original


def test_finished_runs_are_forgotten_once_old_and_failures_kept_longer(
    instance: DagsterInstance,
) -> None:
    ok = execute_job(reconstructable(_succeeding_job), instance=instance).run_id
    bad = execute_job(reconstructable(_failing_job), instance=instance, raise_on_error=False).run_id
    outputs = os.path.join(instance.storage_directory(), ok)
    assert os.path.isdir(outputs)
    now = datetime.now(timezone.utc)

    # Fresh: nothing goes.
    assert _prune(instance, now) == 0
    # Two days on: the success goes, with its outputs; the failure stays.
    assert _prune(instance, now + timedelta(days=2)) == 1
    assert instance.get_run_by_id(ok) is None and not os.path.exists(outputs)
    assert instance.get_run_by_id(bad) is not None
    # Past a week, the failure goes too.
    assert _prune(instance, now + timedelta(days=8)) == 1
    assert instance.get_run_by_id(bad) is None
