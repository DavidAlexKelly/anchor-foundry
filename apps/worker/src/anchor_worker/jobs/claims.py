"""Claiming a scheduled row for one pass (§854).

A schedule-driven job discovers the rows that are due, does each one's work,
then moves the row's next run on. The work can take minutes - a sync, an
export - and the schedules fire every minute or five, with Dagster launching
each tick as its own run. A pass still working when the next tick came found
the row still due, because nothing had moved it yet, and did the same work
again alongside: a second sync of the same source, a second copy of an export.
During a deploy the old and new worker both pass, which is the same thing.

So the next run moves *first*, under a lock, and only for a row that is still
due. That is the claim: a pass that finds the row locked, or already moved on,
leaves it to the pass that claimed it. The lock lasts only until the caller's
transaction commits, not for the whole of the work, so an edit to the row from
the platform never waits on a sync. The job still moves the next run on again
when the work ends, as before, measured from when it finished.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from croniter import croniter
from psycopg import sql


def claim_due(
    cur,
    table: str,
    row_id,
    *,
    schedule: str,
    next_run: str,
    warn: Callable[[str], None] | None = None,
) -> bool:
    """Whether this pass now owns the row's due run. Call inside the scoped
    transaction that reads the row, before committing it."""
    names = {
        "table": sql.Identifier(table),
        "schedule": sql.Identifier(schedule),
        "next_run": sql.Identifier(next_run),
    }
    cur.execute(
        sql.SQL(
            "SELECT {schedule} FROM {table}"
            " WHERE id = %s AND {schedule} IS NOT NULL"
            "   AND ({next_run} IS NULL OR {next_run} <= now())"
            " FOR UPDATE SKIP LOCKED"
        ).format(**names),
        (str(row_id),),
    )
    row = cur.fetchone()
    if row is None:
        return False  # claimed by another pass, unscheduled, or no longer due
    try:
        following = croniter(row[0], datetime.now(timezone.utc)).get_next(datetime)
    except (ValueError, KeyError):
        # Not run: with no next time to move to, it would be due again at once
        # and run on every pass. The platform validates a schedule when it is
        # saved, so this is a row written some other way.
        if warn is not None:
            warn(f"{table} {row_id} has an invalid schedule {row[0]!r}")
        return False
    cur.execute(
        sql.SQL("UPDATE {table} SET {next_run} = %s WHERE id = %s").format(**names),
        (following, str(row_id)),
    )
    return True
