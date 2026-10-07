"""§911: how many operations hold DuckDB at once.

Each connection was held to its memory limit (§875), but nothing bounded how
many there were: the API runs each operation through a worker thread and
anyio allows forty. `DUCKDB_SLOTS` is the number the task is sized for.
"""
from __future__ import annotations

import gc
import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.lib import duck  # noqa: E402


@pytest.fixture()
def slots(monkeypatch: pytest.MonkeyPatch):
    def set_slots(n: int | None, wait: float = 0.2) -> None:
        if n is None:
            monkeypatch.delenv("DUCKDB_SLOTS", raising=False)
        else:
            monkeypatch.setenv("DUCKDB_SLOTS", str(n))
        monkeypatch.setenv("DUCKDB_SLOT_WAIT", str(wait))
    yield set_slots
    monkeypatch.delenv("DUCKDB_SLOTS", raising=False)
    duck._semaphore()  # back to unlimited for the tests after these


def _hold(ready: threading.Event, release: threading.Event, errors: list) -> None:
    try:
        con = duck.connect()
    except Exception as exc:  # noqa: BLE001 - reported to the test
        errors.append(exc)
        ready.set()
        return
    ready.set()
    release.wait(5)
    con.close()


def _holders(n: int) -> tuple[list[threading.Thread], threading.Event, list]:
    release, errors, threads = threading.Event(), [], []
    for _ in range(n):
        ready = threading.Event()
        t = threading.Thread(target=_hold, args=(ready, release, errors))
        t.start()
        ready.wait(5)
        threads.append(t)
    return threads, release, errors


def test_an_operation_past_the_slots_is_told_the_platform_is_busy(slots) -> None:
    slots(2)
    threads, release, errors = _holders(2)
    try:
        assert errors == []
        started = time.monotonic()
        with pytest.raises(duck.Busy, match="busy"):
            duck.connect()
        assert time.monotonic() - started >= 0.15, "it waited for a slot first"
    finally:
        release.set()
        for t in threads:
            t.join()
    # Given back, the slots are there again.
    duck.connect().close()


def test_a_waiting_operation_gets_the_slot_that_is_given_back(slots) -> None:
    slots(1, wait=5)
    threads, release, errors = _holders(1)
    threading.Timer(0.2, release.set).start()
    con = duck.connect()  # waits for the holder, then proceeds
    assert con.execute("SELECT 1").fetchone() == (1,)
    con.close()
    for t in threads:
        t.join()


def test_one_operation_holds_one_slot_however_many_connections_it_opens(slots) -> None:
    """A sandbox and a writer together: with one slot, two such operations
    would otherwise each hold one connection and wait forever for a second."""
    slots(1)
    sandbox = duck.connect()
    writer = duck.connect()
    writer.close()
    sandbox.close()
    duck.connect().close()  # and the slot was given back


def test_a_connection_nobody_closed_gives_its_slot_back(slots) -> None:
    """Leaked on another thread, so this one's own hold cannot stand in for
    the slot coming back."""
    slots(1)

    def leak() -> None:
        con = duck.connect()
        del con

    t = threading.Thread(target=leak)
    t.start()
    t.join()
    gc.collect()
    duck.connect().close()


def test_unset_nothing_waits(slots) -> None:
    slots(None)
    held = [duck.connect() for _ in range(8)]
    for con in held:
        con.close()


def test_a_busy_platform_is_a_503_that_says_to_retry() -> None:
    from fastapi.testclient import TestClient

    from src.main import create_app

    app = create_app()

    @app.get("/api/zz-duck-busy")
    async def busy() -> None:
        raise duck.Busy("the platform is busy with other work; try again in a moment")

    with TestClient(app) as client:
        r = client.get("/api/zz-duck-busy")
    assert r.status_code == 503
    assert r.headers["retry-after"] == "5"
    assert "busy" in r.json()["detail"]
