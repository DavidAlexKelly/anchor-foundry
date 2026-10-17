"""A scheduled SQL model's own SQL runs no longer than its deadline (§982).

DuckDB has no statement timeout, so a join on the wrong key ran until
Dagster's six-hour limit holding one of the worker's run slots, and was said
to have failed by the abandoned-run sweep after an hour while it still ran.
"""
from __future__ import annotations

import os
import sys
import time

import duckdb
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from anchor_worker import dataset_engine  # noqa: E402
from anchor_worker.dataset_engine import DatasetEngineError  # noqa: E402
from anchor_worker.jobs import model_runs  # noqa: E402


@pytest.fixture()
def parquet(tmp_path) -> str:
    path = str(tmp_path / "in.parquet")
    duckdb.connect().execute(f"COPY (SELECT range AS i FROM range(10)) TO '{path}' (FORMAT parquet)")
    return path


def test_a_scheduled_run_past_its_deadline_is_stopped_and_says_so(
    parquet, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dataset_engine, "SCHEDULED_TRANSFORM_DEADLINE_S", 1.0)
    forever = ("SELECT count(*) AS n FROM orders a, range(100000) b, range(100000) c"
               " WHERE b.range + c.range = 7")
    started = time.monotonic()
    with pytest.raises(DatasetEngineError, match="ran longer than a query may here"):
        dataset_engine.run_sql_transform({"orders": parquet}, forever, str(tmp_path / "o" / "x.parquet"))
    assert time.monotonic() - started < 10


def test_one_in_time_is_left_alone(parquet, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(dataset_engine, "SCHEDULED_TRANSFORM_DEADLINE_S", 5.0)
    schema, rows = dataset_engine.run_sql_transform(
        {"orders": parquet}, "SELECT i * 2 AS d FROM orders", str(tmp_path / "o" / "x.parquet"))
    assert rows == 10


def test_the_deadline_ends_before_the_sweep_would_call_the_run_failed() -> None:
    hours = {"1 hour": 3600}[model_runs.ABANDONED_MODEL_RUN]
    assert dataset_engine.SCHEDULED_TRANSFORM_DEADLINE_S < hours
