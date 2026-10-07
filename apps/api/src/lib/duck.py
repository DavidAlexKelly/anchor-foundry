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
import threading
from typing import Any

import duckdb


class Busy(RuntimeError):
    """Every DuckDB slot stayed taken for as long as a caller would wait. The
    message is user-safe: the platform is busy, not broken."""


# **How many operations may hold DuckDB at once in this process** (§911).
# The memory limit above bounds one connection; nothing bounded how many ran.
# The API runs each through a worker thread, and anyio allows forty, so a
# burst of profiles and previews could hold forty times the limit on a task
# sized for two. `DUCKDB_SLOTS` is that count, and an operation past it waits
# `DUCKDB_SLOT_WAIT` seconds for one before it is told the platform is busy.
# Unset, as on a laptop, nothing waits.
#
# A slot belongs to a thread, not a connection: an operation that opens two
# connections (a sandbox and a writer) holds one slot, so two such operations
# cannot each hold one and wait forever for a second.
_slots_lock = threading.Lock()
_slots: threading.BoundedSemaphore | None = None
_slots_size = 0
_local = threading.local()


def _semaphore() -> threading.BoundedSemaphore | None:
    global _slots, _slots_size
    raw = os.environ.get("DUCKDB_SLOTS", "")
    size = int(raw) if raw.isdigit() and int(raw) > 0 else 0
    with _slots_lock:
        if size != _slots_size:
            _slots, _slots_size = (threading.BoundedSemaphore(size) if size else None), size
        return _slots


class _ThreadSlot:
    """One thread's hold on a slot: how many of its connections are open, and
    the semaphore to give back when the last one closes."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.depth = 0
        self.semaphore: threading.BoundedSemaphore | None = None

    def take(self) -> None:
        with self.lock:
            if self.depth:
                self.depth += 1
                return
        semaphore = _semaphore()
        if semaphore is not None:
            wait = float(os.environ.get("DUCKDB_SLOT_WAIT", "60"))
            if not semaphore.acquire(timeout=wait):
                raise Busy("the platform is busy with other work; try again in a moment")
        with self.lock:
            self.depth, self.semaphore = 1, semaphore

    def give(self) -> None:
        with self.lock:
            self.depth -= 1
            if self.depth == 0 and self.semaphore is not None:
                self.semaphore.release()
                self.semaphore = None


def _thread_slot() -> _ThreadSlot:
    slot = getattr(_local, "slot", None)
    if slot is None:
        slot = _local.slot = _ThreadSlot()
    return slot


class _Slotted:
    """A connection that gives its thread's slot back when it is closed, or,
    should a caller never close it, when it is collected."""

    def __init__(self, con: duckdb.DuckDBPyConnection, slot: _ThreadSlot) -> None:
        self._con = con
        self._slot = slot
        self._open = True

    def __getattr__(self, name: str) -> Any:
        return getattr(self._con, name)

    def close(self) -> None:
        if self._open:
            self._open = False
            try:
                self._con.close()
            finally:
                self._slot.give()

    def __del__(self) -> None:
        if getattr(self, "_open", False):
            self.close()

    def __enter__(self) -> "_Slotted":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def spill_directory() -> str:
    return os.path.join(tempfile.gettempdir(), "duckdb-spill")


def connect() -> duckdb.DuckDBPyConnection:
    slot = _thread_slot()
    slot.take()
    try:
        con = duckdb.connect()
    except BaseException:
        slot.give()
        raise
    held = _Slotted(con, slot)
    try:
        limit = os.environ.get("DUCKDB_MEMORY_LIMIT")
        if limit:
            con.execute("SET memory_limit = ?", [limit])
        threads = os.environ.get("DUCKDB_THREADS")
        if threads:
            con.execute(f"SET threads = {int(threads)}")
        con.execute("SET temp_directory = ?", [spill_directory()])
    except Exception:
        held.close()
        raise
    return held  # type: ignore[return-value]


def seal(con: duckdb.DuckDBPyConnection) -> None:
    """Close a connection to everything but its own tables, before it runs a
    person's SQL, and lock its settings (§891).

    `enable_external_access` has been how a sandbox shuts the filesystem and
    the network since the first query route. But the SQL is placed inside a
    statement of ours, and DuckDB runs every statement in what it is given:
    `SELECT 1); SET memory_limit='100GB'; SELECT (1` raised the limit of
    §875 and the query's own 512 MB, so one query could take the task.
    Locking the configuration makes every later `SET` an error, the
    sandbox's own included, so this is the last thing done before the SQL.
    """
    con.execute("SET enable_external_access=false")
    con.execute("SET lock_configuration=true")
