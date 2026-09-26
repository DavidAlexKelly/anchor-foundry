"""A webhook's concurrency and rate limits, applied (§522; db 0111;
`data-connection` p.240).

    "A concurrency limit specifies the maximum number of Webhook executions
     that run at a single time. … A rate limit restricts how many times a
     Webhook can be executed within a time window that you specify." (p.240)

**Asked on a connection of its own**, never the caller's. The answer has to
be committed before the call starts, so another API task asking a moment
later sees this execution's slot and count. A slot taken inside the action's
transaction would be invisible until that transaction ended, and an action
refused by its writeback would take the record of the call with it.

A refusal is an outcome, not an exception, for `webhook_calls`' reason: a
side effect's failure must not fail the action, and a writeback's must. So
a refused execution is a result with no status, which p.237 reads as "the
far end did not change", because nothing was sent.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from sqlalchemy import text

from ..lib.db import fetch_one, get_engine


def refusal_text(refused: str, webhook: dict[str, Any]) -> str:
    """What a refused execution says, in the history and to a writeback's caller."""
    if refused == "concurrency":
        n = webhook["max_concurrent"]
        return (f"this webhook runs at most {n} execution{'' if n == 1 else 's'} at a time, "
                "and that many are running")
    n = webhook["rate_limit"]
    return f"this webhook runs at most {n} time{'' if n == 1 else 's'} per {webhook['rate_window']}"


@asynccontextmanager
async def limited(webhook: dict[str, Any]) -> AsyncIterator[str | None]:
    """Hold a place for one execution of `webhook` for the length of the
    block. Yields None when it may run, or what to say when it may not.

    A webhook with neither limit asks nothing of the database."""
    if webhook.get("max_concurrent") is None and webhook.get("rate_limit") is None:
        yield None
        return
    async with get_engine().begin() as conn:
        row = await fetch_one(conn, "SELECT slot, refused FROM admit_webhook_call(:id)",
                              {"id": str(webhook["id"])})
    assert row is not None
    if row["refused"]:
        yield refusal_text(row["refused"], webhook)
        return
    try:
        yield None
    finally:
        if row["slot"] is not None:
            async with get_engine().begin() as conn:
                await conn.execute(text("SELECT release_webhook_slot(:slot)"),
                                   {"slot": str(row["slot"])})
