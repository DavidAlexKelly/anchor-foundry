"""A person's SQL runs no longer than a request can wait (§971).

DuckDB has no statement timeout. A query that joins on the wrong key ran
until memory gave out or for good, holding one of the task's DuckDB slots
(§911) and a core the whole time; a few and every dataset operation on the
task answered "busy". These run a query that would take hours and hold that
it is stopped at its deadline, says why in a sentence, and gives its slot
back.
"""
from __future__ import annotations

import os
import sys
import threading
import time

import duckdb
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.lib import duck  # noqa: E402
from src.services import dataset_engine as engine  # noqa: E402
from src.services.dataset_engine import DatasetEngineError  # noqa: E402

#: Ten billion pairs: hours, so only the deadline ends it.
FOREVER = "SELECT count(*) FROM range(100000) a, range(100000) b WHERE a.range + b.range = 7"
SAID = "ran longer than a query may here"


@pytest.fixture()
def parquet(tmp_path) -> str:
    path = str(tmp_path / "data.parquet")
    duckdb.connect().execute(f"COPY (SELECT range AS i FROM range(10)) TO '{path}' (FORMAT parquet)")
    return path


@pytest.fixture()
def one_second(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(duck, "QUERY_DEADLINE_S", 1.0)
    monkeypatch.setattr(duck, "TRANSFORM_DEADLINE_S", 1.0)


def test_a_query_past_its_deadline_is_stopped_and_says_so(parquet, one_second) -> None:
    started = time.monotonic()
    with pytest.raises(DatasetEngineError, match=SAID):
        engine.query(parquet, FOREVER)
    assert time.monotonic() - started < 10


def test_a_preview_and_a_run_are_stopped_too(parquet, one_second, tmp_path) -> None:
    sql = "SELECT count(*) AS n FROM orders a, range(100000) b, range(100000) c WHERE b.range + c.range = 7"
    with pytest.raises(DatasetEngineError, match=SAID):
        engine.preview_transform({"orders": parquet}, sql)
    with pytest.raises(DatasetEngineError, match=SAID):
        engine.run_transform({"orders": parquet}, sql, str(tmp_path / "out" / "o.parquet"))


def test_a_stopped_query_gives_its_slot_back(parquet, one_second,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DUCKDB_SLOTS", "1")
    monkeypatch.setenv("DUCKDB_SLOT_WAIT", "2")
    with pytest.raises(DatasetEngineError, match=SAID):
        engine.query(parquet, FOREVER)
    # From another thread, as the next request's would be.
    answers: list[object] = []
    worker = threading.Thread(target=lambda: answers.append(
        engine.query(parquet, "SELECT count(*) AS n FROM dataset").rows))
    worker.start()
    worker.join(10)
    assert answers == [[[10]]]


def test_a_query_that_finishes_in_time_is_left_alone(parquet, monkeypatch) -> None:
    monkeypatch.setattr(duck, "QUERY_DEADLINE_S", 0.3)
    assert engine.query(parquet, "SELECT sum(i) AS s FROM dataset").rows == [[45]]
    # Its timer went with it, rather than waiting out the deadline in a thread.
    assert not [t for t in threading.enumerate() if isinstance(t, threading.Timer) and t.is_alive()]
    # The timer went with the connection: nothing fires on what comes next.
    time.sleep(0.5)
    assert engine.query(parquet, "SELECT count(*) AS n FROM dataset").rows == [[10]]


def test_a_mistake_still_reads_as_the_mistake(parquet, one_second) -> None:
    with pytest.raises(DatasetEngineError) as raised:
        engine.query(parquet, "SELECT no_such_column FROM dataset")
    assert "no_such_column" in str(raised.value) and SAID not in str(raised.value)


def test_the_deadlines_fit_what_waits_for_them() -> None:
    # Inside CloudFront's sixty seconds for a request; a run may outlast one.
    assert duck.QUERY_DEADLINE_S < 60 <= duck.TRANSFORM_DEADLINE_S
    assert duck.stopped_message(50).startswith("stopped after 50 seconds")
    assert duck.stopped_message(600).startswith("stopped after 10 minutes")
