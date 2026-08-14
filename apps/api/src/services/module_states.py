"""Saved module states (parity `docs/parity/workshop.md` §7; Foundry
`workshop` p.200-206).

> "State saving is a powerful Workshop feature that allows module consumers to
> store the current state of their work within a module and then either return
> to that saved state or share the saved state with other users." (p.200)

**Keyed by external ID, not by variable id** (p.203, quoted in migration
0048). That is what lets a state outlive the module being rebuilt around it -
p.203's own example is an Object Dropdown replaced by an Object Selection,
where the state keeps working because the output keeps its external ID.

**Only what the viewer chose is stored.** Derived variables are refused at
document-save time (`workshop_variables._parse_state_saving`) and dropped
again here if one somehow arrives: a state holding a computed value would
restore an answer while its inputs restore the question, and the two disagree
the moment the data behind them moves. Everything derived is recomputed on
open, by the evaluator that computes it on any other viewing.

**Unknown keys are dropped, not refused.** A state written before a variable
was renamed, retyped or removed is the ordinary consequence p.203 describes -
"previously configured states to reload unsuccessfully" - and the useful
behaviour is to restore what still applies rather than to refuse the whole
state over one stale key. What is dropped is *reported*, so a reader is told
their saved view came back incomplete instead of quietly getting a different
one.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import ConflictError, ForbiddenError, NotFoundError
from . import workshop_variables

#: A module with hundreds of saved states is a list nobody reads and a table
#: nothing prunes. Refused rather than paginated: the answer to "I have 200
#: saved views" is to delete some, and a limit that says so is more use than a
#: second page.
MAX_STATES_PER_MODULE = 200

_FIELDS = ("id", "canvas_app_id", "name", "values", "page_id", "created_by",
           "created_at", "updated_at")
_COLUMNS = ", ".join(f"s.{f}" for f in _FIELDS)


def _row(row: Any) -> dict[str, Any]:
    out = dict(row)
    values = out.get("values")
    out["values"] = json.loads(values) if isinstance(values, str) else (values or {})
    return out


async def list_states(conn: AsyncConnection, canvas_app_id: UUID) -> list[dict[str, Any]]:
    """Every saved state of one module, newest first, with its author's name."""
    rows = await fetch_all(
        conn,
        f"""
        SELECT {_COLUMNS}, u.display_name AS created_by_name
          FROM module_states s
          LEFT JOIN users u ON u.id = s.created_by
         WHERE s.canvas_app_id = :aid
         ORDER BY s.created_at DESC
        """,
        {"aid": str(canvas_app_id)},
    )
    return [_row(r) for r in rows]


async def get_state(conn: AsyncConnection, state_id: UUID) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        f"""
        SELECT {_COLUMNS}, u.display_name AS created_by_name
          FROM module_states s
          LEFT JOIN users u ON u.id = s.created_by
         WHERE s.id = :sid
        """,
        {"sid": str(state_id)},
    )
    if row is None:
        raise NotFoundError("module state")
    return _row(row)


def savable_values(
    variables: dict[str, workshop_variables.Variable], values: dict[str, Any]
) -> dict[str, Any]:
    """What a state should store, out of everything the viewer has set.

    `values` arrives keyed by **variable id** (that is what the running module
    holds) and comes back keyed by **external ID** (that is what a state is
    stored under, p.203). The translation is the whole function, and doing it
    here rather than in the browser means one implementation rather than two
    that drift - the same argument that keeps variable evaluation on the
    server.

    A variable that is enabled but that the viewer has not set is **absent**
    rather than stored as null. Restoring it would otherwise clear a default
    that was never touched, which is a change the person saving never made.
    """
    savable = workshop_variables.savable_variables(variables)
    out: dict[str, Any] = {}
    for external_id, variable in savable.items():
        value = values.get(variable.id)
        if value is None or value == "":
            continue
        out[external_id] = value
    return out


def restore(
    variables: dict[str, workshop_variables.Variable], stored: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """A saved state, translated back into values keyed by variable id.

    Returns the values and **the external IDs that no longer apply**, because
    a state that came back incomplete has to say so. p.203 warns that changing
    an external ID "may cause previously configured states to reload
    unsuccessfully"; being told which part failed is the difference between a
    known gap and a view that is quietly wrong.

    A key that still names a savable variable is restored whatever it holds.
    Type-checking it here would be a second opinion about a value this module
    stored itself, and the evaluator downstream already refuses what it cannot
    use - `cast` and `filter_set` both say so in their own words.
    """
    savable = workshop_variables.savable_variables(variables)
    values: dict[str, Any] = {}
    missing: list[str] = []
    for external_id, value in stored.items():
        variable = savable.get(external_id)
        if variable is None:
            missing.append(external_id)
            continue
        values[variable.id] = value
    return values, sorted(missing)


async def save_state(
    conn: AsyncConnection,
    *,
    canvas_app_id: UUID,
    name: str,
    values: dict[str, Any],
    page_id: str | None,
    user_id: UUID,
) -> dict[str, Any]:
    """Write a state, or overwrite the one with this name.

    **Overwrite rather than refuse a duplicate name**, and only for the person
    who created it. Saving over your own state under the same name is what
    "update my saved view" means and there is no other way to express it; doing
    it to *somebody else's* state would silently replace a view they shared,
    which is why that is a refusal instead.
    """
    name = name.strip()
    if not name:
        raise ConflictError("a saved state needs a name")

    existing = await fetch_one(
        conn,
        "SELECT id, created_by FROM module_states WHERE canvas_app_id = :aid AND name = :n",
        {"aid": str(canvas_app_id), "n": name},
    )
    if existing is not None:
        if str(existing["created_by"]) != str(user_id):
            raise ForbiddenError(
                f"{name!r} is somebody else's saved state - saving over it would "
                "replace a view they shared. Use a different name"
            )
        row = await fetch_one(
            conn,
            f"""
            UPDATE module_states AS s
               SET values = CAST(:v AS jsonb), page_id = :p
             WHERE s.id = :sid
            RETURNING {_COLUMNS}
            """,
            {"sid": str(existing["id"]), "v": json.dumps(values), "p": page_id},
        )
        assert row is not None
        return _row(row)

    count = await fetch_one(
        conn,
        "SELECT count(*) AS n FROM module_states WHERE canvas_app_id = :aid",
        {"aid": str(canvas_app_id)},
    )
    if count is not None and int(count["n"]) >= MAX_STATES_PER_MODULE:
        raise ConflictError(
            f"this module already has {MAX_STATES_PER_MODULE} saved states, which is "
            "the limit - delete one before saving another"
        )

    row = await fetch_one(
        conn,
        f"""
        INSERT INTO module_states AS s (canvas_app_id, name, values, page_id, created_by)
        VALUES (:aid, :n, CAST(:v AS jsonb), :p, :uid)
        RETURNING {_COLUMNS}
        """,
        {
            "aid": str(canvas_app_id), "n": name, "v": json.dumps(values),
            "p": page_id, "uid": str(user_id),
        },
    )
    assert row is not None
    return _row(row)


async def delete_state(conn: AsyncConnection, state_id: UUID, user_id: UUID) -> None:
    """Delete a state, if it is yours.

    Shared states are the point of the feature (p.200), so "I can see it"
    cannot mean "I can delete it" - a view somebody else built and circulated
    must not disappear because a reader tidied up.
    """
    row = await fetch_one(
        conn, "SELECT created_by FROM module_states WHERE id = :sid", {"sid": str(state_id)}
    )
    if row is None:
        raise NotFoundError("module state")
    if str(row["created_by"]) != str(user_id):
        raise ForbiddenError(
            "this saved state belongs to somebody else - they may have shared it, "
            "so deleting it is theirs to do"
        )
    await conn.execute(
        text("DELETE FROM module_states WHERE id = :sid"), {"sid": str(state_id)}
    )
