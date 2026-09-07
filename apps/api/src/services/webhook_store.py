"""Webhooks and their history in the database (db 0067; decision 0012).

Separate from `services/webhooks.py`, which is what a definition *means*: the
split every service pair here uses, where a wrong answer in the other file is a
line and a wrong answer in this one needs a row to see.

Two things are worth reading before changing anything here.

**A run belongs to the person who made it.** db 0067's read policy is
`called_by = rls_current_user_id()`, which is `data-connection` p.242's rule
put where it cannot be forgotten: "inputs passed to the webhook and the full
response will only be visible to the user who called the webhook. This protects
any sensitive data passed in or returned from the webhook call." So none of the
read functions here take a user id — a parameter would be a second answer to a
question the connection has already settled, and the kind that is wrong
silently. §257's inbox made the same choice for the same reason.

**A webhook points at a connection, and the connection is where the secret
is.** Nothing in this file resolves a credential; `record` stores what was sent
only when the webhook says to, and what was sent has already had the
connection's auth headers left out of it (`webhook_calls.perform`).
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import ConflictError, NotFoundError

#: One page of a webhook's history. §256's number and its reason: a list that
#: grows without bound eventually takes seconds to draw, and this one grows
#: every time anybody runs an action.
PAGE = 50

_COLUMNS = """
    w.id, w.workspace_id, w.project_id, w.connection_id, w.api_name,
    w.display_name, w.description, w.method, w.path, w.query, w.headers,
    w.body, w.inputs, w.outputs, w.store_responses, w.retry_statuses,
    w.timeout_seconds, w.created_by, w.created_at, w.updated_at,
    c.name AS connection_name, c.source_type AS connection_source_type
"""


async def list_for_project(
    conn: AsyncConnection, project_id: UUID
) -> list[dict[str, Any]]:
    return await fetch_all(
        conn,
        f"""
        SELECT {_COLUMNS}
          FROM webhooks w
          JOIN connections c ON c.id = w.connection_id
         WHERE w.project_id = :pid
         ORDER BY w.display_name
        """,
        {"pid": str(project_id)},
    )


async def get(conn: AsyncConnection, webhook_id: UUID) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        f"""
        SELECT {_COLUMNS}
          FROM webhooks w
          JOIN connections c ON c.id = w.connection_id
         WHERE w.id = :wid
        """,
        {"wid": str(webhook_id)},
    )
    if row is None:
        # NotFoundError rather than a bare LookupError, which §254 had to fix
        # one service over: a lookup that raises the wrong class turns every
        # read of a missing row into a 500.
        raise NotFoundError("webhook")
    return row


async def connection_for(
    conn: AsyncConnection, project_id: UUID, connection_id: UUID
) -> dict[str, Any]:
    """The connection a webhook may be built on, or a refusal saying why not.

    **Read through RLS rather than checked against a list**, so a connection in
    another project is "does not exist" rather than "forbidden" — the same
    answer db 0006 gives everywhere else, and the one that does not tell a
    caller what they cannot see.

    A workspace-scoped connection is usable from any project in the workspace,
    which is what that scope means (db 0003); the policy already resolves that,
    so the only extra check here is the source type.
    """
    row = await fetch_one(
        conn,
        """
        SELECT c.id, c.name, c.source_type, c.config, c.secret_arn, c.scope,
               c.workspace_id, c.project_id
          FROM connections c
         WHERE c.id = :cid
           AND (c.scope = 'workspace'
                OR c.project_id = :pid)
        """,
        {"cid": str(connection_id), "pid": str(project_id)},
    )
    if row is None:
        raise NotFoundError("connection")
    if row["source_type"] != "rest":
        # p.220: "Some other source types also support webhooks." Ours support
        # one, and saying which is better than a request that fails at call
        # time against a Postgres connection.
        raise ConflictError(
            f"webhooks need a REST connection; {row['name']!r} is "
            f"a {row['source_type']} source"
        )
    return row


async def create(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    project_id: UUID,
    connection_id: UUID,
    api_name: str,
    display_name: str,
    description: str,
    definition: dict[str, Any],
    created_by: UUID,
) -> dict[str, Any]:
    existing = await fetch_one(
        conn,
        "SELECT 1 AS x FROM webhooks WHERE workspace_id = :wid AND api_name = :name",
        {"wid": str(workspace_id), "name": api_name},
    )
    if existing is not None:
        raise ConflictError(f"a webhook called {api_name!r} already exists")
    row = await fetch_one(
        conn,
        """
        INSERT INTO webhooks (workspace_id, project_id, connection_id, api_name,
                              display_name, description, method, path, query,
                              headers, body, inputs, outputs, store_responses,
                              retry_statuses, timeout_seconds, created_by)
        VALUES (:wid, :pid, :cid, :name, :label, :descr, :method, :path,
                CAST(:query AS jsonb), CAST(:headers AS jsonb),
                CAST(:body AS jsonb), CAST(:inputs AS jsonb),
                CAST(:outputs AS jsonb), :store, :retries, :timeout, :by)
        RETURNING id
        """,
        {
            "wid": str(workspace_id), "pid": str(project_id),
            "cid": str(connection_id), "name": api_name,
            "label": display_name, "descr": description,
            **_definition_params(definition),
            "by": str(created_by),
        },
    )
    assert row is not None
    return await get(conn, UUID(str(row["id"])))


async def update(
    conn: AsyncConnection,
    webhook_id: UUID,
    *,
    display_name: str,
    description: str,
    connection_id: UUID,
    definition: dict[str, Any],
) -> dict[str, Any]:
    """Everything but `api_name`, which is a reference other things hold.

    The same reasoning §129 made for an action parameter: a rename is a
    different operation from an edit, and one that has to check who is pointing
    at the old name. There is nothing pointing at a webhook yet — the action
    rule is §260 — so the rename is *absent* rather than unchecked, which is
    the order §252's implements column argues for.
    """
    row = await fetch_one(
        conn,
        """
        UPDATE webhooks
           SET display_name = :label, description = :descr,
               connection_id = :cid, method = :method, path = :path,
               query = CAST(:query AS jsonb), headers = CAST(:headers AS jsonb),
               body = CAST(:body AS jsonb), inputs = CAST(:inputs AS jsonb),
               outputs = CAST(:outputs AS jsonb), store_responses = :store,
               retry_statuses = :retries, timeout_seconds = :timeout
         WHERE id = :wid
        RETURNING id
        """,
        {
            "wid": str(webhook_id), "label": display_name, "descr": description,
            "cid": str(connection_id), **_definition_params(definition),
        },
    )
    if row is None:
        raise NotFoundError("webhook")
    return await get(conn, webhook_id)


async def delete(conn: AsyncConnection, webhook_id: UUID) -> None:
    row = await fetch_one(
        conn, "DELETE FROM webhooks WHERE id = :wid RETURNING id",
        {"wid": str(webhook_id)},
    )
    if row is None:
        raise NotFoundError("webhook")


def _definition_params(definition: dict[str, Any]) -> dict[str, Any]:
    """The parsed definition as bind parameters.

    One function rather than the same twelve keys written out in `create` and
    `update`: a field added to `webhooks.parse` and to one of the two would be
    a field that saves on create and vanishes on the next edit, which is the
    kind of asymmetry no test looks for unless somebody thinks to write it.
    """
    return {
        "method": definition["method"],
        "path": definition["path"],
        "query": json.dumps(definition["query"]),
        "headers": json.dumps(definition["headers"]),
        "body": json.dumps(definition["body"]) if definition["body"] is not None else None,
        "inputs": json.dumps(definition["inputs"]),
        "outputs": json.dumps(definition["outputs"]),
        "store": definition["store_responses"],
        "retries": definition["retry_statuses"],
        "timeout": definition["timeout_seconds"],
    }


# ---- history (p.242) -------------------------------------------------------------
async def record(
    conn: AsyncConnection,
    *,
    webhook_id: UUID,
    workspace_id: UUID,
    action_run_id: UUID | None,
    called_by: UUID,
    mode: str,
    result: dict[str, Any],
    store_responses: bool,
) -> UUID:
    """One execution, whether or not it worked.

    **`store_responses` decides the two body columns and nothing else.** p.242:
    "This option may be disabled entirely for a webhook that is known to return
    sensitive information that should not be stored in the webhook history."
    The status, the timing and whether the far end may have changed are kept
    either way, because those are what a person debugging needs and none of
    them is the sensitive part. p.247 gives the concrete case — a bearer token
    in a response — and the answer there is this flag rather than a redaction
    pass that has to be right about every shape.

    NULL is "deliberately not kept" and an empty object is a stored empty body.
    Anything reading these back has to keep the two apart.
    """
    row = await fetch_one(
        conn,
        """
        INSERT INTO webhook_runs (webhook_id, workspace_id, action_run_id,
                                  called_by, mode, ok, status_code,
                                  system_changed, error, duration_ms,
                                  request_body, response_body, outputs)
        VALUES (:hid, :wid, :run, :by, :mode, :ok, :status, :changed, :error,
                :ms, CAST(:req AS jsonb), CAST(:resp AS jsonb),
                CAST(:outputs AS jsonb))
        RETURNING id
        """,
        {
            "hid": str(webhook_id), "wid": str(workspace_id),
            "run": str(action_run_id) if action_run_id else None,
            "by": str(called_by), "mode": mode,
            "ok": bool(result.get("ok")),
            "status": result.get("status"),
            "changed": result.get("system_changed"),
            "error": result.get("error"),
            "ms": result.get("duration_ms"),
            "req": json.dumps(result.get("request")) if store_responses else None,
            "resp": json.dumps(result.get("response")) if store_responses else None,
            "outputs": json.dumps(result.get("outputs") or {}),
        },
    )
    assert row is not None
    return UUID(str(row["id"]))


async def history(
    conn: AsyncConnection, webhook_id: UUID, *, limit: int = PAGE, offset: int = 0
) -> tuple[list[dict[str, Any]], int]:
    """This connection's user's runs of this webhook, newest first, and how many.

    **No user id argument**, for `notification_store.list_for_user`'s reason:
    db 0067's policy answers "whose" from the connection, and a parameter here
    would be a second answer to a settled question.
    """
    rows = await fetch_all(
        conn,
        """
        SELECT count(*) OVER () AS match_count,
               r.id, r.mode, r.ok, r.status_code, r.system_changed, r.error,
               r.duration_ms, r.request_body, r.response_body, r.outputs,
               r.action_run_id, r.created_at
          FROM webhook_runs r
         WHERE r.webhook_id = :hid
         ORDER BY r.created_at DESC, r.id
         LIMIT :limit OFFSET :offset
        """,
        {"hid": str(webhook_id), "limit": max(1, min(limit, PAGE)),
         "offset": max(0, offset)},
    )
    out = [dict(r) for r in rows]
    total = int(out[0]["match_count"]) if out else 0
    for row in out:
        row.pop("match_count", None)
    return out, total


async def uses_connection(conn: AsyncConnection, connection_id: UUID) -> list[str]:
    """Which webhooks are built on this connection, by name.

    db 0067 makes the foreign key `ON DELETE RESTRICT`, so the database already
    refuses. This is what turns that refusal into a sentence naming what is in
    the way — the same reasoning `actions.parameter_usages` makes about a
    Workshop module, and the reason it returns names rather than a count: the
    person who has to fix it is usually not the person who typed the delete.
    """
    rows = await fetch_all(
        conn,
        "SELECT display_name FROM webhooks WHERE connection_id = :cid"
        " ORDER BY display_name",
        {"cid": str(connection_id)},
    )
    return [str(r["display_name"]) for r in rows]
