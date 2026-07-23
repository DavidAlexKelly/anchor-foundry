"""Cron scheduling helper — the API's half of scheduling (spec: cron-
triggered models, scheduled connection syncs). This computes only the
*initial* next_run_at guess when a schedule is first set or changed; the
worker (apps/worker/src/anchor_worker/jobs/{model_runs,sync_configs}.py) is
the one that recomputes it after every firing, since it's the process that
actually observes "this just fired, what's next." Keeping cron parsing to
these two call sites (API write-time seed, worker post-fire recompute)
means the expression is only ever interpreted in trusted, server-side code.
"""
from __future__ import annotations

from datetime import datetime, timezone

from croniter import croniter


class InvalidCronError(ValueError):
    """User-safe: the cron expression the caller supplied doesn't parse."""


def next_run_after(cron_expression: str, after: datetime | None = None) -> datetime:
    base = after or datetime.now(timezone.utc)
    try:
        return croniter(cron_expression, base).get_next(datetime)
    except (ValueError, KeyError) as exc:
        raise InvalidCronError(f"invalid cron expression {cron_expression!r}") from exc
