"""Sections on an action form (§328; db 0081; `action-types` p.122-124).

    "The action form can be customized with sections. These sections provide a
     logical grouping of parameters to organize an action form. Sections also
     support columns, descriptions, and conditional overrides." (p.122)

    "Sections are also collapsible, can be hidden entirely, and can make use of
     conditional overrides… A section can be hidden at first and only shown
     based on a prior parameter." (p.123)

    "Parameters and sections display in the form based on their order in this
     Form Content section." (p.124)

**A section changes what a form looks like and nothing else.** An action with
every section deleted submits exactly the same values from exactly the same
parameters — which is why `visibility` below returns what to *draw* and never
touches what is bound, checked or written. A hidden section's parameters are
still declared, still defaulted and still validated; p.123 is about a form, not
about a contract.

That distinction is the one thing a reader of this module has to hold on to,
because the alternative is inviting: if a section is hidden, why send its
parameters at all? Because `check_criteria` and `bind_parameters` are what
decides a submission, and a form that quietly dropped values would mean the
same action did different things depending on which boxes were on screen.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from .actions import _passes  # the condition grammar decision 0007 already has

# **p.123's "one or two columns" is not checked here, and the first draft
# checked it.** `SectionIn.columns` is `Literal[1, 2]` and `action_sections`
# carries `CHECK (columns IN (1, 2))` — two layers that both refuse three,
# either side of this one. The check was unreachable: a mutation sweep deleted
# it and every test stayed green, because nothing can call this with a number
# the request model let through. §213's rule, and the reasoning stands in its
# place rather than the line.


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def visibility(
    section: dict[str, Any],
    *,
    bound: dict[str, Any],
    user: dict[str, Any],
) -> bool:
    """Whether this section is drawn, given what has been filled in so far.

    p.123's three states, in the order they override each other:

    * `hidden` — "can be hidden entirely". Always off, whatever else says.
    * `visible_when` — "hidden at first and only shown based on a prior
      parameter". Evaluated against the values in hand.
    * neither — always on, which is every section anybody made before
      configuring one of the above.

    **A condition that cannot be decided means hidden**, which is the opposite
    of `check_criteria`'s unevaluable-fails-closed only in appearance: both
    refuse to guess. A section shown because its condition was unreadable would
    put parameters in front of somebody on the strength of a broken rule, and
    p.123's whole point is that the form asks for things "under the appropriate
    circumstances".
    """
    if section.get("hidden"):
        return False
    condition = _json(section.get("visible_when"))
    if not condition:
        return True
    try:
        return _passes(condition, bound=bound, user=user)
    except Exception:  # noqa: BLE001 - `_Unevaluable` and anything a bad
        # document can throw. Named broadly on purpose: this is a *display*
        # decision reading a JSON blob somebody typed, and a form that raised
        # a 500 because a section's condition was malformed would take the
        # whole action down for a cosmetic rule.
        return False


async def list_sections(
    conn: AsyncConnection, action_type_id: UUID
) -> list[dict[str, Any]]:
    """p.124's Form Content order, with each section's parameters inside it.

    One statement per kind rather than one per section: a form with six
    sections is six round trips otherwise, and this is read every time an
    action's definition is opened.
    """
    sections = await fetch_all(
        conn,
        """
        SELECT id, title, description, columns, collapsible, collapsed,
               hidden, visible_when, sort_order
          FROM action_sections
         WHERE action_type_id = :atid
         ORDER BY sort_order, title
        """,
        {"atid": str(action_type_id)},
    )
    members = await fetch_all(
        conn,
        """
        SELECT section_id, api_name
          FROM action_parameters
         WHERE action_type_id = :atid AND section_id IS NOT NULL
         ORDER BY sort_order, api_name
        """,
        {"atid": str(action_type_id)},
    )
    inside: dict[str, list[str]] = {}
    for row in members:
        inside.setdefault(str(row["section_id"]), []).append(str(row["api_name"]))
    return [
        {**dict(s), "visible_when": _json(s["visible_when"]),
         "parameters": inside.get(str(s["id"]), [])}
        for s in sections
    ]


async def replace_sections(
    conn: AsyncConnection,
    action_type_id: UUID,
    sections: list[dict[str, Any]],
) -> None:
    """Write the whole Form tab at once.

    **A whole-document write, like `set_definition` beside it** (decision
    0007). p.124 describes dragging parameters between sections and reordering
    both — a set of granular operations would make the browser send a sequence
    whose intermediate states are forms that do not make sense, and every one
    of them would have to be legal.

    Parameters not named in any section come back to the form body, because
    that is what "moved out of a section" means and there is nowhere else for
    them to go.
    """
    known = {
        str(row["api_name"])
        for row in await fetch_all(
            conn,
            "SELECT api_name FROM action_parameters WHERE action_type_id = :atid",
            {"atid": str(action_type_id)},
        )
    }
    titles: set[str] = set()
    for index, section in enumerate(sections):
        title = str(section.get("title", "")).strip()
        if not title:
            raise ValueError("every section needs a title")
        if title in titles:
            raise ValueError(f"two sections are both called {title!r}")
        titles.add(title)
        for name in section.get("parameters") or []:
            if str(name) not in known:
                raise ValueError(
                    f"{title!r} contains {name!r}, which is not a parameter of "
                    "this action"
                )

    claimed: dict[str, str] = {}
    for section in sections:
        for name in section.get("parameters") or []:
            if str(name) in claimed:
                # p.124 offers two ways to put a parameter in a section and
                # neither is "in both" — a parameter drawn twice would be one
                # box overwriting the other's value as the reader typed.
                raise ValueError(
                    f"{name!r} is in two sections: "
                    f"{claimed[str(name)]!r} and {section.get('title')!r}"
                )
            claimed[str(name)] = str(section.get("title"))

    # **Cleared first, then rebuilt.** `ON DELETE SET NULL` returns every
    # parameter to the form body as the old sections go, so a parameter left
    # out of the new document ends up unsectioned rather than pointing at a row
    # that no longer exists.
    #
    # Everything above runs before this, which reads like the guarantee that a
    # refused form leaves the old one alone — **and is not**. `user_connection`
    # is one transaction per request, so the delete is rolled back whatever
    # order it happened in; a sweep that moved this to the top of the function
    # killed nothing. The order is how the function reads, not what keeps the
    # promise, and the test that checks the promise names the transaction.
    await conn.exec_driver_sql(
        "DELETE FROM action_sections WHERE action_type_id = %s",
        (str(action_type_id),),
    )
    for index, section in enumerate(sections):
        row = await fetch_one(
            conn,
            """
            INSERT INTO action_sections
                   (action_type_id, title, description, columns, collapsible,
                    collapsed, hidden, visible_when, sort_order)
            VALUES (:atid, :title, :description, :columns, :collapsible,
                    :collapsed, :hidden, CAST(:visible AS jsonb), :ord)
            RETURNING id
            """,
            {
                "atid": str(action_type_id),
                "title": str(section["title"]).strip(),
                "description": str(section.get("description") or ""),
                "columns": int(section.get("columns", 1)),
                "collapsible": bool(section.get("collapsible", False)),
                "collapsed": bool(section.get("collapsed", False)),
                "hidden": bool(section.get("hidden", False)),
                "visible": json.dumps(section["visible_when"])
                if section.get("visible_when") else None,
                "ord": index,
            },
        )
        assert row is not None
        names = [str(n) for n in (section.get("parameters") or [])]
        if names:
            await conn.exec_driver_sql(
                "UPDATE action_parameters SET section_id = %s "
                " WHERE action_type_id = %s AND api_name = ANY(%s)",
                (str(row["id"]), str(action_type_id), names),
            )
