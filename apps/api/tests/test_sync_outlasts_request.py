"""A sync that outlasts its request carries on and says so (§967).

CloudFront gives an origin sixty seconds and a source may be read for five
minutes, so a sync past the first answered with a 504 while it went on and
finished. These hold the two halves of the remedy: what the person is told at
once (a 202 naming the run), and that the run then ends as it would have.
The wait is set to nothing rather than the sync made slow, so every sync here
outlasts its request.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, hdr  # noqa: E402
from test_sync import (  # noqa: E402,F401 (fixtures)
    cbase, client, connection_id, fx, seeded_source, source_database,
)
from src.lib import long_work  # noqa: E402
from src.main import create_app  # noqa: E402


@pytest.fixture()
def no_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(long_work, "ANSWER_WITHIN_S", 0)


def settled(client: TestClient, fx: Fixture, connection_id: str, run_id: str) -> dict:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        runs = client.get(f"{cbase(fx)}/{connection_id}/sync-runs",
                          headers=hdr(fx.viewer_sub)).json()
        run = next(r for r in runs if r["id"] == run_id)
        if run["status"] != "running":
            return run
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} still running")


def test_a_sync_that_outlasts_its_request_answers_with_its_run(
    client: TestClient, fx: Fixture, connection_id: str, no_wait
) -> None:
    r = client.post(f"{cbase(fx)}/{connection_id}/sync", headers=hdr(fx.editor_sub),
                    json={"source_table": "orders", "dataset_name": f"Long {fx.tag}"})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["running"] is True and body["ok"] is None and body["dataset"] is None
    # And it went on to finish, as the run it named says.
    run = settled(client, fx, connection_id, body["run_id"])
    assert (run["status"], run["rows_synced"], run["dataset_name"]) == (
        "succeeded", 3, f"Long {fx.tag}")


def test_one_that_fails_after_answering_says_so_in_its_run(
    client: TestClient, fx: Fixture, connection_id: str, no_wait
) -> None:
    r = client.post(f"{cbase(fx)}/{connection_id}/sync", headers=hdr(fx.editor_sub),
                    json={"source_table": "no_such_table"})
    assert r.status_code == 202, r.text
    run = settled(client, fx, connection_id, r.json()["run_id"])
    assert run["status"] == "failed" and run["error"]


def test_a_scheduled_sync_run_now_carries_on_too(
    client: TestClient, fx: Fixture, connection_id: str, no_wait
) -> None:
    r = client.put(f"{cbase(fx)}/{connection_id}/scheduled-sync", headers=hdr(fx.editor_sub),
                   json={"mode": "full", "source_table": "orders",
                         "dataset_name": f"Scheduled {fx.tag}"})
    assert r.status_code == 200, r.text
    r = client.post(f"{cbase(fx)}/{connection_id}/scheduled-sync/run",
                    headers=hdr(fx.editor_sub))
    assert r.status_code == 202, r.text
    run = settled(client, fx, connection_id, r.json()["run_id"])
    assert (run["status"], run["dataset_name"]) == ("succeeded", f"Scheduled {fx.tag}")


def test_a_sync_that_finishes_in_time_answers_as_it_always_did(
    client: TestClient, fx: Fixture, connection_id: str
) -> None:
    r = client.post(f"{cbase(fx)}/{connection_id}/sync", headers=hdr(fx.editor_sub),
                    json={"source_table": "orders", "dataset_name": f"Quick {fx.tag}"})
    assert r.status_code == 200, r.text
    assert r.json()["running"] is False and r.json()["ok"] is True


def test_a_stopping_api_lets_a_running_sync_finish(
    client: TestClient, fx: Fixture, connection_id: str, no_wait
) -> None:
    """A deploy stops the task; the sync it was running is given the time
    the task has, and is not left for the abandoned-run sweep."""
    with TestClient(create_app()) as stopping:
        r = stopping.post(f"{cbase(fx)}/{connection_id}/sync", headers=hdr(fx.editor_sub),
                          json={"source_table": "orders", "dataset_name": f"Stopping {fx.tag}"})
        assert r.status_code == 202, r.text
    # Stopped, and asked once: no waiting here, the stop did it.
    runs = client.get(f"{cbase(fx)}/{connection_id}/sync-runs", headers=hdr(fx.viewer_sub)).json()
    assert next(x for x in runs if x["id"] == r.json()["run_id"])["status"] == "succeeded"


# ---- the helper itself ------------------------------------------------------

def test_work_that_finishes_in_time_is_its_own_answer() -> None:
    async def work() -> int:
        return 7

    assert asyncio.run(long_work.answer_within(work(), within=1)) == 7


def test_an_error_raised_in_time_is_raised_to_the_caller() -> None:
    async def work() -> None:
        raise ValueError("refused")

    with pytest.raises(ValueError, match="refused"):
        asyncio.run(long_work.answer_within(work(), within=1))


def test_work_past_its_time_carries_on_and_is_waited_for_at_shutdown() -> None:
    done: list[str] = []

    async def work() -> None:
        await asyncio.sleep(0.2)
        done.append("finished")

    async def request_then_shutdown() -> tuple[object, int, int]:
        answer = await long_work.answer_within(work(), within=0.01)
        running = long_work.running()
        return answer, running, await long_work.settle(timeout=5)

    assert asyncio.run(request_then_shutdown()) == (None, 1, 0)
    assert done == ["finished"]


def test_shutdown_waits_only_as_long_as_it_is_given(caplog: pytest.LogCaptureFixture) -> None:
    async def work() -> None:
        await asyncio.sleep(5)

    async def request_then_shutdown() -> int:
        await long_work.answer_within(work(), within=0.01)
        started = time.monotonic()
        left = await long_work.settle(timeout=0.1)
        assert time.monotonic() - started < 2
        for task in list(long_work._running):
            task.cancel()
        return left

    assert asyncio.run(request_then_shutdown()) == 1
    assert "still running at shutdown" in caplog.text


def test_a_failure_nobody_is_waiting_for_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    async def work() -> None:
        await asyncio.sleep(0.05)
        raise RuntimeError("the source went away")

    async def request_then_shutdown() -> None:
        assert await long_work.answer_within(work(), within=0.01) is None
        await long_work.settle(timeout=5)

    asyncio.run(request_then_shutdown())
    assert "outlasted its request failed" in caplog.text
    assert "the source went away" in caplog.text


# ---- a run completed whatever stops it (§976) -------------------------------
def latest_run(client: TestClient, fx: Fixture, connection_id: str) -> dict:
    return client.get(f"{cbase(fx)}/{connection_id}/sync-runs", headers=hdr(fx.viewer_sub)).json()[0]


def test_a_sync_the_platform_is_too_busy_for_says_so_and_ends(
    client: TestClient, fx: Fixture, connection_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.lib import duck
    from src.services import sync as sync_service

    def busy(*args, **kwargs):
        raise duck.Busy("the platform is busy with other work; try again in a moment")

    monkeypatch.setattr(sync_service, "snapshot_source_table", busy)
    r = client.post(f"{cbase(fx)}/{connection_id}/sync", headers=hdr(fx.editor_sub),
                    json={"source_table": "orders"})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is False and "busy" in r.json()["error"]
    run = latest_run(client, fx, connection_id)
    assert (run["id"], run["status"]) == (r.json()["run_id"], "failed")
    assert "busy" in run["error"]


def test_a_sync_something_unexpected_stopped_is_not_left_running(
    client: TestClient, fx: Fixture, connection_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.services import sync as sync_service

    def broken(*args, **kwargs):
        raise RuntimeError("a bug in the sync")

    monkeypatch.setattr(sync_service, "snapshot_source_table", broken)
    with pytest.raises(RuntimeError, match="a bug in the sync"):
        client.post(f"{cbase(fx)}/{connection_id}/sync", headers=hdr(fx.editor_sub),
                    json={"source_table": "orders"})
    run = latest_run(client, fx, connection_id)
    assert (run["status"], run["error"]) == ("failed", "the sync stopped unexpectedly; run it again")
