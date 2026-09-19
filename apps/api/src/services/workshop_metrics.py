"""A module's usage metrics (§396; `workshop` p.185-188).

    "Workshop's usage metrics give module builders visibility into how their
     applications are being used. From the Metrics tab in the Workshop
     editor's left sidebar, you can view action submission counts and layout
     view counts… All metrics are aggregate counts and are not attributable to
     any specific user." (p.185)

**What "each action in the module" counts, which the pages leave open and this
answers.** p.185 says "how many times each action in the module has been
successfully submitted", and that is two readings: submissions *of the actions
this module uses*, or submissions *made from this module*. They are different
numbers and only one of them is free.

p.186 settles it: *"Action metrics are available by default for all modules and
do not require any additional configuration."* Set against layout views on the
next page, which need a toggle, a daily aggregation and 24 hours before
anything appears, that sentence is doing real work. A per-module attribution
would need a column on every submission and a writer on every submit path, and
it could never answer for a module that existed before the column did — so it
is not what "by default for all modules" can mean. **The module scopes which
actions are listed; it does not scope which submissions are counted.**

That reading has a cost and the panel has to carry it rather than hide it: a
builder can misread the number as "submissions made here". The wording is
`apps/web/src/lib/workshop-metrics.ts`'s problem and it is written down there.

**Only successful submissions**, which p.185 says outright. `action-types`
p.165 puts failures on the *action type's* own metrics screen (§323), where
somebody is debugging the action rather than reading how a module is used.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all

#: p.188's "7 days, 30 days, or 90 days. The default is 30."
PERIODS = (7, 30, 90)
DEFAULT_PERIOD = 30

#: The widget prop that names an action. One spelling, shared with the builder
#: - a second would make a widget's action invisible to this panel while the
#: widget went on running it.
ACTION_PROP = "actionTypeId"


def module_actions(document: Any) -> dict[str, list[dict[str, str]]]:
    """Which actions a module uses, and where.

    p.185: *"Select an action to view which widgets in the module use that
    action."* So the answer is a map rather than a set, and it is read off the
    document rather than stored - an index would be a second copy of a fact
    that changes every time somebody edits a widget.

    **Two places name an action and both count.** A widget carries one in its
    `actionTypeId` prop; an event carries one in a `run_action` effect. A
    module whose only submit button is an event would otherwise report no
    actions at all, which reads as "nobody uses this" rather than "we looked in
    one place".
    """
    found: dict[str, list[dict[str, str]]] = {}

    def note(action: Any, node: str, via: str) -> None:
        if isinstance(action, str) and action:
            found.setdefault(action, []).append({"node": node, "via": via})

    layout = document.get("layout") if isinstance(document, dict) else None
    if isinstance(layout, dict):
        for node_id, node in layout.items():
            props = node.get("props") if isinstance(node, dict) else None
            if isinstance(props, dict):
                note(props.get(ACTION_PROP), str(node_id), "widget")

    events = document.get("events") if isinstance(document, dict) else None
    if isinstance(events, dict):
        for event in events.values():
            if not isinstance(event, dict):
                continue
            trigger = event.get("trigger")
            on = str(trigger.get("node")) if isinstance(trigger, dict) else ""
            for effect in event.get("effects") or []:
                if not isinstance(effect, dict) or effect.get("type") != "run_action":
                    continue
                config = effect.get("config")
                if isinstance(config, dict):
                    note(config.get("action"), on, "event")
    return found


async def action_counts(
    conn: AsyncConnection, action_ids: "list[str]", *, days: int = DEFAULT_PERIOD
) -> list[dict[str, Any]]:
    """Successful submissions per action, this period and the one before it.

    p.188: *"Each overview card shows the percentage change compared to the
    previous equivalent period. For example, when viewing the last 30 days, the
    percentage change compares against the 30 days before that."* So the prior
    window is the same length and immediately before - computed in one query
    over one scan rather than two round trips, because the two numbers are
    always read together.

    Returns a row per action *asked about*, including ones with no submissions
    at all. An action a module runs and nobody has used is the most interesting
    row on the panel, and an absent row reads as an action the module does not
    have.
    """
    if not action_ids:
        return []
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    before = since - timedelta(days=days)
    rows = await fetch_all(
        conn,
        """
        SELECT a.id::text AS action_type_id,
               a.display_name,
               a.api_name,
               count(r.id) FILTER (
                   WHERE r.status = 'succeeded' AND r.started_at >= :since
               ) AS submissions,
               count(r.id) FILTER (
                   WHERE r.status = 'succeeded'
                     AND r.started_at >= :before AND r.started_at < :since
               ) AS previous
          FROM action_types a
          -- LEFT, so an action nobody has submitted is a row of zeroes rather
          -- than a row that is not there.
          LEFT JOIN action_runs r ON r.action_type_id = a.id
         WHERE a.id = ANY(CAST(:ids AS uuid[]))
         GROUP BY a.id, a.display_name, a.api_name
         ORDER BY submissions DESC, a.display_name
        """,
        {"ids": list(action_ids), "since": since, "before": before},
    )
    return [dict(r) for r in rows]


# ---- layout views (§397; db 0093; p.186-188) ---------------------------------
async def record_view(
    conn: AsyncConnection, *, app_id: UUID, node_id: str
) -> bool:
    """Count one view of one layout. Returns whether it was counted.

    **Refused silently when the module has not opted in** (p.187), and `False`
    rather than an exception: the caller is a browser reporting what somebody
    looked at, and a module with tracking off is the ordinary case rather than
    an error. The check is here rather than in the route because it is a fact
    about the row being written, and a route that forgot it would write counts
    nobody asked to collect.

    **Aggregated on write.** One row per module, layout and day, incremented -
    so a busy module costs a row a day per page rather than a row per view, and
    the panel reads in real time. db 0093's header argues that against p.187's
    daily pipeline.
    """
    rows = await fetch_all(
        conn,
        """
        INSERT INTO canvas_layout_views (canvas_app_id, node_id, day, views)
        SELECT a.id, :node, (now() AT TIME ZONE 'utc')::date, 1
          FROM canvas_apps a
          -- The opt-in, enforced by the statement rather than by a branch
          -- above it: one round trip, and no window in which a concurrent
          -- toggle-off lets a view through a check that already passed.
         WHERE a.id = :aid AND a.track_usage
            ON CONFLICT (canvas_app_id, node_id, day)
            DO UPDATE SET views = canvas_layout_views.views + 1
         RETURNING canvas_app_id
        """,
        {"aid": str(app_id), "node": node_id},
    )
    return bool(rows)


async def layout_views(
    conn: AsyncConnection, *, app_id: UUID, days: int = DEFAULT_PERIOD
) -> list[dict[str, Any]]:
    """Views per layout over the window, busiest first (p.186).

    The prior period comes back on the same row for p.188's percentage, the
    same way `action_counts` does - the two numbers are always read together
    and a second query would scan the same rows again.

    **A layout with views in *either* window appears**, which is not the same
    as "layouts viewed this period" and is deliberately the wider set. A page
    with nine views last month and none this one is the most useful row a usage
    panel has - "this stopped being used" is the finding somebody opened the
    tab for, and filtering it out would leave them looking at a shorter list
    with no idea anything was missing.

    A layout with no views in either window has no row at all. Unlike an
    action, which is listed because the module *runs* it, there is nothing here
    to report - and the panel knows what the document currently contains, so it
    is the one that could say "this page has never been viewed" if that were
    ever wanted.
    """
    return [
        dict(r)
        for r in await fetch_all(
            conn,
            """
            SELECT node_id,
                   coalesce(sum(views) FILTER (
                       WHERE day > (now() AT TIME ZONE 'utc')::date - CAST(:days AS int)
                   ), 0) AS views,
                   coalesce(sum(views) FILTER (
                       WHERE day <= (now() AT TIME ZONE 'utc')::date - CAST(:days AS int)
                   ), 0) AS previous
              FROM canvas_layout_views
             WHERE canvas_app_id = :aid
               AND day > (now() AT TIME ZONE 'utc')::date - CAST(:span AS int)
             GROUP BY node_id
            HAVING coalesce(sum(views), 0) > 0
             ORDER BY views DESC, node_id
            """,
            {"aid": str(app_id), "days": days, "span": days * 2},
        )
    ]
