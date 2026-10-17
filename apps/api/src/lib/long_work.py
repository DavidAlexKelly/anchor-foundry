"""Work a request starts that may outlast the request (§967).

CloudFront waits sixty seconds for an answer (E.31), and a sync started from
the API reads its source for up to five minutes (`connectors.SOURCE_DEADLINE_S`).
So a large table's sync answered the person who started it with a 504 while it
carried on and finished: the error said it had failed, the history later said
it had not, and the obvious next move - press Sync again - started a second one.

`answer_within` runs the work as its own task and waits for it, as long as an
answer can still reach the browser. Work that finishes in that time answers
exactly as before; work that does not is left running, and the caller answers
that it is still running and names the run it can be followed by. Nothing that
was waiting for it can stop it any more, a client that went away included.

What a restart does to work still running: `settle` gives it the time ECS
gives the process to stop, and what remains is ended with the process. Its run
is then still marked running, which is what the abandoned-run sweep (§870,
§950) exists for: it fails the run, in words, within half an hour.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")

#: How long a request waits for its work before answering that it is still
#: running: inside CloudFront's sixty seconds, with room for the answer.
ANSWER_WITHIN_S = 45.0

#: How long a stopping task waits for work still running: inside the thirty
#: seconds ECS gives a container between SIGTERM and SIGKILL.
SETTLE_S = 25.0

log = logging.getLogger("anchor.long_work")

# Held so a task nobody awaits any more is not collected while it runs.
_running: set[asyncio.Task[Any]] = set()


async def answer_within(work: Coroutine[Any, Any, T], within: float | None = None) -> T | None:
    """`work`'s result if it finishes within `within` seconds; None if it is
    still running, in which case it carries on. An error it raises in time is
    raised here, as if it had been awaited directly."""
    task = asyncio.ensure_future(work)
    _running.add(task)
    task.add_done_callback(_running.discard)
    try:
        return await asyncio.wait_for(asyncio.shield(task),
                                      ANSWER_WITHIN_S if within is None else within)
    except TimeoutError:
        # Nobody will see what it raises now, so it is logged instead.
        task.add_done_callback(_report_failure)
        return None


def _report_failure(task: asyncio.Task[Any]) -> None:
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        log.error("work that outlasted its request failed", exc_info=error)


def running() -> int:
    """How many pieces of work are still running."""
    return len(_running)


async def settle(timeout: float = SETTLE_S) -> int:
    """Wait up to `timeout` seconds for work still running; how many pieces
    of it were left."""
    if _running:
        await asyncio.wait(set(_running), timeout=timeout)
    left = len(_running)
    if left:
        log.warning("%d piece(s) of work still running at shutdown; their runs are "
                    "failed by the abandoned-run sweep", left)
    return left
