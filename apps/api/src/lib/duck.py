"""One way to open DuckDB, held to the task it runs on (§875; E.27).

Every dataset operation opens its own in-memory DuckDB, and DuckDB's default
is to use 80% of the memory it can see. On a Fargate task that is about the
task's own size, so each connection was allowed most of the task, and two
large operations at once - two people profiling, an export beside an upload -
were enough for the kernel to kill the process and every request on it.

So a deployed task says how much one connection may hold
(`DUCKDB_MEMORY_LIMIT`) and how many threads it may use (`DUCKDB_THREADS`),
and everything past the limit spills to local disk rather than failing: the
spill directory is set here because an in-memory database's default is a
directory under the working directory, which a container may not be able to
write. Unset, as on a laptop, DuckDB keeps its defaults.

The limit governs DuckDB's buffers, not the process: §875 measured resident
memory at about one and a half times the limit at its peak. The task sizes in
`infra/cdk/src/constructs/services.ts` are chosen from that.

`apps/worker/src/anchor_worker/duck.py` is the same file for the worker.
"""
from __future__ import annotations

import os
import tempfile

import duckdb


def spill_directory() -> str:
    return os.path.join(tempfile.gettempdir(), "duckdb-spill")


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    try:
        limit = os.environ.get("DUCKDB_MEMORY_LIMIT")
        if limit:
            con.execute("SET memory_limit = ?", [limit])
        threads = os.environ.get("DUCKDB_THREADS")
        if threads:
            con.execute(f"SET threads = {int(threads)}")
        con.execute("SET temp_directory = ?", [spill_directory()])
    except Exception:
        con.close()
        raise
    return con
