"""DuckDB held to the task it runs on (§875; E.27).

Every dataset operation opens its own DuckDB, and by default each may take 80%
of the memory it can see - on a Fargate task, most of the task. A deployed
task now says what one connection may hold, and a profile no longer needs
every column's values in memory at once.
"""
from __future__ import annotations

import os
import sys

import duckdb
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.lib import duck  # noqa: E402
from src.services.dataset_engine import profile_columns  # noqa: E402

COLUMNS = ["a", "b", "c"]


def _setting(con, name: str):
    return con.execute("SELECT current_setting(?)", [name]).fetchone()[0]


def test_a_connection_takes_the_tasks_limits(monkeypatch) -> None:
    monkeypatch.setenv("DUCKDB_MEMORY_LIMIT", "64MB")
    monkeypatch.setenv("DUCKDB_THREADS", "2")
    con = duck.connect()
    try:
        assert _setting(con, "memory_limit") == "61.0 MiB"  # 64 MB, in MiB
        assert _setting(con, "threads") == 2
        # Past the limit it spills here rather than failing.
        assert _setting(con, "temp_directory") == duck.spill_directory()
    finally:
        con.close()


def test_without_limits_a_connection_keeps_duckdbs_own(monkeypatch) -> None:
    monkeypatch.delenv("DUCKDB_MEMORY_LIMIT", raising=False)
    monkeypatch.delenv("DUCKDB_THREADS", raising=False)
    con, plain = duck.connect(), duckdb.connect()
    try:
        assert _setting(con, "memory_limit") == _setting(plain, "memory_limit")
        assert _setting(con, "threads") == _setting(plain, "threads")
    finally:
        con.close()
        plain.close()


@pytest.fixture(scope="module")
def wide(tmp_path_factory) -> str:
    """A million rows of three columns, every value distinct."""
    path = str(tmp_path_factory.mktemp("wide") / "wide.parquet")
    picks = ", ".join(f"md5((i + {n})::varchar) AS {c}" for n, c in enumerate(COLUMNS))
    con = duckdb.connect()
    try:
        con.execute(f"COPY (SELECT {picks} FROM range(1000000) t(i)) TO '{path}' (FORMAT parquet)")
    finally:
        con.close()
    return path


def test_a_profile_fits_in_a_connection_that_all_its_counts_at_once_would_not(
    wide: str, monkeypatch
) -> None:
    """The three exact counts in one aggregate need every column's values at
    once; under this limit DuckDB refuses that. Counted one column at a time,
    the same profile fits. (§875 swept the limit: the counts at once failed up
    to 256 MB here, and the profile passed from 128.)"""
    monkeypatch.setenv("DUCKDB_MEMORY_LIMIT", "128MB")
    monkeypatch.setenv("DUCKDB_THREADS", "2")
    con = duck.connect()
    try:
        with pytest.raises(duckdb.OutOfMemoryException):
            con.execute(
                "SELECT " + ", ".join(f"count(DISTINCT {c})" for c in COLUMNS)
                + f" FROM read_parquet('{wide}')"
            ).fetchone()
    finally:
        con.close()

    profile = profile_columns(wide)
    assert [p["distinct_count"] for p in profile] == [1000000] * len(COLUMNS)
    assert [p["null_count"] for p in profile] == [0] * len(COLUMNS)


# ---- a person's SQL cannot change the sandbox it runs in (§891) ---------------
RAISE_LIMIT = "SET memory_limit='100GB'"


@pytest.fixture(scope="module")
def small(tmp_path_factory) -> str:
    path = str(tmp_path_factory.mktemp("small") / "small.parquet")
    con = duckdb.connect()
    try:
        con.execute(f"COPY (SELECT range AS id FROM range(10)) TO '{path}' (FORMAT parquet)")
    finally:
        con.close()
    return path


def test_a_query_cannot_raise_its_own_memory_limit(small: str) -> None:
    """DuckDB runs every statement in what it is given, so a query could
    carry a SET of its own past the sandbox's."""
    from src.services.dataset_engine import DatasetEngineError, query

    with pytest.raises(DatasetEngineError, match="locked"):
        query(small, f"{RAISE_LIMIT}; SELECT * FROM dataset")
    # And reading still works.
    assert query(small, "SELECT count(*) AS n FROM dataset").rows == [[10]]


def test_a_transform_cannot_break_out_of_its_statement_to_raise_it(small: str, tmp_path) -> None:
    """The SQL is placed inside `CREATE TABLE ... AS (...)`: closing the
    bracket ends that statement and starts the caller's own."""
    from src.services.dataset_engine import DatasetEngineError, preview_transform, run_transform

    escape = f"SELECT 1 AS x); {RAISE_LIMIT}; CREATE TABLE junk AS (SELECT 1"
    with pytest.raises(DatasetEngineError, match="locked"):
        run_transform({"t": small}, escape, str(tmp_path / "out.parquet"))
    with pytest.raises(DatasetEngineError, match="locked"):
        preview_transform({"t": small}, escape)


def test_both_copies_seal_the_same_way() -> None:
    con = duckdb.connect()
    try:
        duck.seal(con)
        with pytest.raises(duckdb.Error, match="locked"):
            con.execute(RAISE_LIMIT)
        with pytest.raises(duckdb.Error):
            con.execute("SELECT * FROM read_csv('/etc/passwd')")
    finally:
        con.close()
