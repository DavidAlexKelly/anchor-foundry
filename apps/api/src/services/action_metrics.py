"""Action metrics (§323; db 0079; `action-types` p.164-166).

    "Action metrics display the near real-time usage of an action type over the
     last 30 days… Success/failure metrics: Monitor the current status of your
     actions with success and failure counts… P95 duration metric: Track the
     95th percentile (P95) execution duration for each action type." (p.164)

    "You are also able to access run history, which provides a complete view of
     a given action's executions over the past seven days." (p.164)

    "Action metrics do not require action logs to be displayed. **Unlike action
     logs, action metrics track failures.**" (p.165)

**Two windows, and they are not a typo.** p.164 gives the metrics thirty days
and the run history seven. The numbers answer different questions — "is this
action healthy" is a trend, "what happened" is a list somebody reads row by row
— and a seven-day list is one that can be read.

**P95 rather than an average, and p.164 says why**: "highlights the upper range
of execution times, helping you detect performance bottlenecks". An average
over a thousand fast runs hides the twenty that time out, which are the only
ones anybody is looking for.

The failure categories are p.165-166's own, less the two that are documented as
"only possible for function-backed actions" — Functions are ○ here, so those
are absent rather than offered and never produced (db 0079 says so at more
length).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one, user_connection

#: p.164's window for the metrics.
METRICS_DAYS = 30

#: p.164's window for the run history: "a complete view of a given action's
#: executions over the past seven days". Deliberately its own constant rather
#: than a fraction of the one above — they are two decisions, and a reader
#: checking one against the page should find the page's number.
HISTORY_DAYS = 7

#: How many runs the history returns at most. p.164 says "complete", and seven
#: days of a busy action is not a list anybody reads — so the window is the
#: promise and this is the page.
HISTORY_LIMIT = 200

#: p.165-166's categories, less the two that need Functions. Ordered as p.165
#: introduces them, so a screen listing them matches the page.
FAILURE_CATEGORIES = (
    "invalid_parameter",
    "authentication",
    "scale_limit",
    "side_effect",
    "conflict",
    "unclassified",
)

#: What a dataset engine failure is, when this platform cannot say more.
#:
#: **Matched on the message, and only here.** db 0079 stores the category at
#: write time precisely so nothing reads error text later — but the engine's
#: errors are the one failure this platform does not raise itself, so the
#: classification has to happen somewhere, and the honest place is the moment
#: the error is caught rather than every time a metric is drawn.
_ENGINE_CONFLICTS = ("already exists", "duplicate key", "concurrent")


def classify_engine_error(message: str) -> str:
    """Which of p.166's categories a dataset engine failure belongs to.

    **Conflict or unclassified, and nothing else.** p.166's conflict failure is
    "a conflict, such as a concurrent modification", and a primary key
    collision is exactly that — an action creating a row somebody else's action
    already created. Everything else the engine says (a binder error, a
    conversion error, a file that could not be written) is a fault in the
    mapping or the storage rather than in the submission, and p.166 has a name
    for that: unclassified.

    Guessing more finely would be worse than not guessing. "Conversion Error:
    could not convert string" *looks* like an invalid parameter, and is not:
    the parameter passed this platform's own type check on the way in, so the
    disagreement is between the ontology's declared type and the dataset's
    column — a configuration problem that would send somebody to re-read a form
    they filled in correctly.
    """
    said = (message or "").casefold()
    if any(mark in said for mark in _ENGINE_CONFLICTS):
        return "conflict"
    return "unclassified"


async def summary(
    conn: AsyncConnection, action_type_id: UUID
) -> dict[str, Any]:
    """p.164's success and failure counts, and the P95, over p.164's window.

    **`running` is counted and reported separately.** A run that has not
    finished is neither a success nor a failure, and folding it into either
    would make the two numbers disagree with the total — which is the number
    somebody checks first when they think a metric is lying.

    The P95 is over **finished** runs only, for the same reason: a run still
    going has no duration yet, and treating its elapsed time as one would make
    the percentile fall as soon as anybody looked at it.
    """
    since = datetime.now(timezone.utc) - timedelta(days=METRICS_DAYS)
    row = await fetch_one(
        conn,
        """
        SELECT
            count(*) FILTER (WHERE status = 'succeeded') AS succeeded,
            count(*) FILTER (WHERE status = 'failed')    AS failed,
            count(*) FILTER (WHERE status = 'running')   AS running,
            -- **`percentile_disc`, not `percentile_cont`.** A P95 that
            -- interpolates reports a duration no run ever took; p.164 wants
            -- "the upper range of execution times", and the honest answer to
            -- that is a time something actually took.
            percentile_disc(0.95) WITHIN GROUP (
                ORDER BY EXTRACT(EPOCH FROM (finished_at - started_at))
            ) FILTER (WHERE finished_at IS NOT NULL) AS p95_seconds
          FROM action_runs
         WHERE action_type_id = :atid AND started_at >= :since
        """,
        {"atid": str(action_type_id), "since": since},
    )
    assert row is not None
    succeeded, failed = int(row["succeeded"]), int(row["failed"])
    p95 = row["p95_seconds"]
    return {
        "succeeded": succeeded,
        "failed": failed,
        "running": int(row["running"]),
        "total": succeeded + failed + int(row["running"]),
        # `None` when nothing has finished in the window — which is not zero.
        # A P95 of 0 would say every run was instant.
        "p95_seconds": float(p95) if p95 is not None else None,
        "window_days": METRICS_DAYS,
    }


async def failures_by_category(
    conn: AsyncConnection, action_type_id: UUID
) -> list[dict[str, Any]]:
    """p.165-166's categories, counted, biggest first.

    Only categories that happened are returned. A row of zeroes for every
    category p.166 names would be six lines of nothing above the one line that
    matters — and two of those six can never be non-zero here, which would make
    the list read as a broken feature rather than a healthy action.
    """
    since = datetime.now(timezone.utc) - timedelta(days=METRICS_DAYS)
    rows = await fetch_all(
        conn,
        """
        SELECT COALESCE(failure_category, 'unclassified') AS category,
               count(*) AS failures
          FROM action_runs
         WHERE action_type_id = :atid AND started_at >= :since
           AND status = 'failed'
         GROUP BY 1
         ORDER BY count(*) DESC, 1
        """,
        {"atid": str(action_type_id), "since": since},
    )
    return [
        {"category": r["category"], "failures": int(r["failures"])} for r in rows
    ]


async def history(
    conn: AsyncConnection, action_type_id: UUID
) -> list[dict[str, Any]]:
    """p.164's run history: "a complete view of a given action's executions over
    the past seven days".

    Newest first — this is a list somebody reads to find out what just went
    wrong, which is the opposite of §322's conversation and the same as every
    other "what happened" list here.
    """
    since = datetime.now(timezone.utc) - timedelta(days=HISTORY_DAYS)
    rows = await fetch_all(
        conn,
        """
        SELECT r.id, r.status, r.error, r.failure_category, r.instance_id,
               r.started_at, r.finished_at,
               EXTRACT(EPOCH FROM (r.finished_at - r.started_at)) AS seconds,
               u.display_name AS requested_by_name
          FROM action_runs r
          LEFT JOIN users u ON u.id = r.requested_by
         WHERE r.action_type_id = :atid AND r.started_at >= :since
         ORDER BY r.started_at DESC
         LIMIT :limit
        """,
        {"atid": str(action_type_id), "since": since, "limit": HISTORY_LIMIT},
    )
    return [
        {
            **dict(r),
            "seconds": float(r["seconds"]) if r["seconds"] is not None else None,
        }
        for r in rows
    ]


async def record_refusal(
    *,
    action_type_id: UUID,
    instance_id: UUID | None,
    dataset_id: UUID | None,
    requested_by: UUID,
    submitted_values: dict[str, Any],
    category: str,
    message: str,
) -> None:
    """Record a submission that was refused before it could write anything.

    **This is what makes p.165's sentence true here.** "Unlike action logs,
    action metrics track failures" — and until this existed, a failure was only
    countable if it happened *after* the run was opened, which meant only
    dataset engine errors. An invalid parameter or a failed submission
    criterion, the two things a person actually does wrong, produced a 422 and
    no trace at all.

    Written as a run that opened and closed in the same breath, rather than as
    a row in some other table, because it is the same event: somebody submitted
    this action and it did not happen. A separate store would mean two things
    to add up whenever anybody asked how often this action fails.

    **It opens its own connection, and that is the entire point.** A refusal is
    raised, and a raise unwinds the request — `user_connection` wraps the whole
    handler in one `engine.begin()`, so a row written on the caller's
    connection would be rolled back by the very exception it exists to
    describe. Recording it here on a connection that commits by itself is the
    difference between a metric and a check that passes over a dead feature:
    the insert and the refusal have opposite fates on purpose.

    The new connection carries the same user, so the RLS policy on
    `action_runs` decides this write exactly as it decides a real run's — a
    refusal is not a reason to write as somebody with more access.
    """
    import json

    if category not in FAILURE_CATEGORIES:
        raise ValueError(
            f"unknown failure category {category!r}; expected one of "
            + ", ".join(FAILURE_CATEGORIES)
        )
    async with user_connection(requested_by) as own:
        await fetch_one(
            own,
            """
            INSERT INTO action_runs
                   (action_type_id, instance_id, dataset_id, requested_by,
                    submitted_values, status, error, failure_category,
                    started_at, finished_at)
            VALUES (:atid, :iid, :did, :by, CAST(:vals AS jsonb),
                    'failed', :error, :category, now(), now())
            RETURNING id
            """,
            {
                "atid": str(action_type_id),
                "iid": str(instance_id) if instance_id else None,
                "did": str(dataset_id) if dataset_id else None,
                "by": str(requested_by),
                "vals": json.dumps(submitted_values),
                "error": message[:2000],
                "category": category,
            },
        )
