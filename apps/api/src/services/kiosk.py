"""Kiosk mode (§684; Foundry `workshop` p.610-612).

> "Kiosk mode gives builders the ability to enable long-lived, restricted
> sessions for Workshop applications, allowing them to be safely displayed for
> extended periods of time. Kiosk mode sessions are read-only, meaning that
> Ontology write backs such as object edits and creations may not be
> triggered, and have scoped down permissions limiting the content viewable
> within a session." (p.610)

A session is a credential of its own: `kiosk_<secret>`, shown once, stored as
its hash (db 0134). The API accepts it as a bearer token (`middleware/auth`),
runs the request as the builder who launched it, and narrows that in two ways
the browser cannot talk its way past:

* **read-only**, by request (`refusal`): reads and the handful of POSTs that
  only compute an answer, in the session's own workspace, and nothing else;
* **scoped**, by the database: the session's object types, link types, action
  types and modules go into transaction-local settings, and db 0134's
  RESTRICTIVE policies hide everything else (p.611's "scoped down").

**The scope is what the module references** (`module_access.referenced`, the
same walk p.92's Check access panel uses), over the *published* version (p.610:
"the contents of the currently published version of the module"), plus the
modules it embeds (p.611: "nested entities from embedded Workshop modules will
be automatically included").
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import ConflictError, NotFoundError
from . import module_access
from .canvas import get_published

PREFIX = "kiosk_"

#: p.610's "long-lived": a working week, so a screen put up on Monday is still
#: up on Friday. p.612 adds that sessions "follow the platform's session
#: timeout policies" - this is that policy for a kiosk, and an administrator
#: ends one sooner from the launch history.
LIFETIME = timedelta(days=7)

#: The kinds a scope holds, as db 0134's settings name them.
KINDS = ("object_types", "link_types", "action_types", "apps")

#: POSTs a kiosk may make: each computes an answer from what the module shows
#: and writes nothing. Anything else that is not a read is refused, which is
#: p.610's "read-only" - an action, an edit, a saved state, a recorded view.
READ_POSTS = tuple(re.compile(p) for p in (
    r"/object-sets/(evaluate|tracks|group|distribution|cross-tab|time-series)$",
    r"/object-types/freshness$",
    r"/object-types/[^/]+/derived-values$",
    r"/interfaces/[^/]+/evaluate$",
    r"/action-types/[^/]+/(visible-sections|parameter-choices|effective-parameters)$",
    r"/published-canvas-apps/[^/]+/variables/evaluate$",
))

READS = ("GET", "HEAD")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return PREFIX + secrets.token_urlsafe(32)


def _embedded(definition: Any) -> list[str]:
    """Modules this one embeds (the Embedded module widget's `moduleId`)."""
    found: set[str] = set()
    layout = definition.get("layout") if isinstance(definition, dict) else None
    for node in (layout or {}).values() if isinstance(layout, dict) else []:
        props = node.get("props") if isinstance(node, dict) else None
        module = props.get("moduleId") if isinstance(props, dict) else None
        if isinstance(module, str) and module:
            found.add(module)
    return sorted(found)


def scope_of(app_id: UUID, definition: Any) -> dict[str, list[str]]:
    """p.611's "Content in scope": what the published module references, and
    the module itself with the ones it embeds."""
    named = module_access.referenced(definition)
    return {
        "object_types": named["object_types"],
        "link_types": named["link_types"],
        "action_types": named["action_types"],
        "apps": sorted({str(app_id), *_embedded(definition)}),
    }


def settings_for(scope: dict[str, Any]) -> dict[str, str]:
    """The transaction-local settings db 0134's policies read."""
    out = {"app.kiosk": "on"}
    for kind in KINDS:
        ids = [str(i) for i in scope.get(kind) or []]
        out[f"app.kiosk_{kind}"] = "{" + ",".join(ids) + "}" if ids else ""
    return out


def refusal(method: str, path: str, workspace_id: str) -> str | None:
    """Why a kiosk session may not make this request, or None if it may.

    **Its own workspace only**, and there only reads: p.610's sessions are
    "read-only", and a credential left on a public screen should not open the
    rest of the platform the builder can see.
    """
    if path in ("/api/auth/me", "/api/kiosk/current", "/api/kiosk/end"):
        return None
    base = f"/api/workspaces/{workspace_id}"
    if not (path == base or path.startswith(base + "/")):
        return "a kiosk session reads only its own module's workspace"
    if method in READS:
        return None
    tail = path[len(base):]
    if method == "POST" and any(p.search(tail) for p in READ_POSTS):
        return None
    return "kiosk sessions are read-only (workshop p.610)"


# ---- the allowlist (p.610's Control Panel setting) ---------------------------
async def allowlist(conn: AsyncConnection, organisation_id: UUID) -> list[dict[str, Any]]:
    return await fetch_all(
        conn,
        """
        SELECT k.app_id, a.name, a.project_id, k.added_at
          FROM kiosk_modules k
          LEFT JOIN canvas_apps a ON a.id = k.app_id
         WHERE k.organisation_id = :oid
         ORDER BY a.name NULLS LAST
        """,
        {"oid": str(organisation_id)},
    )


#: Modules offered at once in the allowlist's Add (§819).
CANDIDATE_PAGE = 50


async def candidates(conn: AsyncConnection, search: str = "") -> tuple[list[dict[str, Any]], int]:
    """A page of the modules matching `search`, and how many match in all.

    This was the first 500 by name, with nothing to say there were more: an
    organisation past 500 modules could not add the rest, and the picker gave
    no sign they existed. A dropdown that silently truncates is worse than a
    slow one, so it is searched and says what it is not showing.
    """
    term = search.strip()
    params: dict[str, Any] = {"q": f"%{_escape_like(term)}%" if term else None,
                              "page": CANDIDATE_PAGE}
    where = """
          FROM canvas_apps a
          JOIN projects p ON p.id = a.project_id
          JOIN workspaces w ON w.id = p.workspace_id
         WHERE CAST(:q AS text) IS NULL OR a.name ILIKE :q OR w.name ILIKE :q
    """
    rows = await fetch_all(
        conn,
        f"SELECT a.id AS app_id, a.name, w.name AS workspace_name {where} "
        "ORDER BY w.name, a.name, a.id LIMIT :page",
        params,
    )
    total = await fetch_one(conn, f"SELECT count(*) AS n {where}", params)
    return rows, int(total["n"]) if total else 0


def _escape_like(term: str) -> str:
    """A search for "a_b" means "a_b", not "a<anything>b"."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def allow(conn: AsyncConnection, organisation_id: UUID, app_id: UUID, *, by: UUID) -> None:
    app = await fetch_one(conn, "SELECT id FROM canvas_apps WHERE id = :aid", {"aid": str(app_id)})
    if app is None:
        raise NotFoundError("canvas app")
    await conn.execute(
        text(
            "INSERT INTO kiosk_modules (organisation_id, app_id, added_by)"
            " VALUES (:oid, :aid, :by) ON CONFLICT DO NOTHING"
        ),
        {"oid": str(organisation_id), "aid": str(app_id), "by": str(by)},
    )


async def disallow(conn: AsyncConnection, organisation_id: UUID, app_id: UUID) -> None:
    await conn.execute(
        text("DELETE FROM kiosk_modules WHERE organisation_id = :oid AND app_id = :aid"),
        {"oid": str(organisation_id), "aid": str(app_id)},
    )


# ---- launching (p.610's modal) ------------------------------------------------
async def availability(
    conn: AsyncConnection, *, organisation_id: UUID, workspace_id: UUID, app_id: UUID,
    project_role: str | None,
) -> dict[str, Any]:
    """Whether this module can be launched in kiosk mode by this person, why
    not if not, and p.610's "contents of the currently published version of
    the module that will be visible for the duration of the session"."""
    app = await get_published(conn, workspace_id, app_id)
    definition = _parse(app["definition"])
    reason = None
    listed = await fetch_one(
        conn,
        "SELECT 1 AS x FROM kiosk_modules WHERE organisation_id = :oid AND app_id = :aid",
        {"oid": str(organisation_id), "aid": str(app_id)},
    )
    if not (isinstance(definition, dict) and (definition.get("kiosk") or {}).get("enabled")):
        reason = "Kiosk mode is not turned on in this module's settings."
    elif listed is None:
        reason = "An administrator has not added this module to the organisation's kiosk allowlist."
    elif project_role not in ("editor", "admin", "owner"):
        reason = "Launching a kiosk session is for the module's builders."
    scope = scope_of(app_id, definition)
    return {
        "available": reason is None,
        "reason": reason,
        "version_number": app.get("published_version"),
        "scope": await _named(conn, scope),
    }


async def _named(conn: AsyncConnection, scope: dict[str, list[str]]) -> dict[str, list[dict[str, str]]]:
    """Each id with its name, for the modal's "Content in scope"."""
    tables = {"object_types": "object_types", "link_types": "link_types",
              "action_types": "action_types", "apps": "canvas_apps"}
    columns = {"canvas_apps": "name"}
    out: dict[str, list[dict[str, str]]] = {}
    for kind, table in tables.items():
        ids = scope.get(kind) or []
        rows = await fetch_all(
            conn,
            f"SELECT id, {columns.get(table, 'display_name')} AS name FROM {table}"
            " WHERE id = ANY(CAST(:ids AS uuid[]))",
            {"ids": "{" + ",".join(ids) + "}"},
        ) if ids else []
        named = {str(r["id"]): str(r["name"]) for r in rows}
        # A reference to something this person cannot see is still in scope,
        # and still missing on screen; it is listed without a name.
        out[kind] = [{"id": i, "name": named.get(i, "")} for i in ids]
    return out


async def launch(
    conn: AsyncConnection, *, organisation_id: UUID, workspace_id: UUID, app_id: UUID,
    project_role: str | None, by: UUID,
) -> dict[str, Any]:
    """p.610's "Launch session": the credential, returned once."""
    state = await availability(
        conn, organisation_id=organisation_id, workspace_id=workspace_id, app_id=app_id,
        project_role=project_role,
    )
    if not state["available"]:
        raise ConflictError(state["reason"])
    app = await get_published(conn, workspace_id, app_id)
    scope = scope_of(app_id, _parse(app["definition"]))
    token = new_token()
    now = datetime.now(timezone.utc)
    row = await fetch_one(
        conn,
        """
        INSERT INTO kiosk_sessions (organisation_id, workspace_id, project_id, app_id,
                                    version_number, launched_by, token_hash, scope,
                                    created_at, expires_at)
        VALUES (:oid, :wid, :pid, :aid, :ver, :by, :hash, CAST(:scope AS jsonb), :now, :exp)
        RETURNING id, expires_at
        """,
        {
            "oid": str(organisation_id), "wid": str(workspace_id),
            "pid": str(app["project_id"]), "aid": str(app_id),
            "ver": int(app.get("published_version") or 0), "by": str(by),
            "hash": hash_token(token), "scope": json.dumps(scope),
            "now": now, "exp": now + LIFETIME,
        },
    )
    assert row is not None
    return {"session_id": row["id"], "token": token, "expires_at": row["expires_at"],
            "app_id": app_id, "project_id": app["project_id"]}


# ---- the launch history (p.611) ------------------------------------------------
#: Sessions the launch history shows at once.
SESSION_PAGE = 200


async def sessions(conn: AsyncConnection, organisation_id: UUID) -> list[dict[str, Any]]:
    """The launch history, **active sessions first** (§820).

    p.610: active sessions "can also be ended by Administrators from the
    Session Launch History table", and that table is the only place to end
    one. It was the newest 200, and a session lasts a week, so one launched
    before 200 others dropped off the table while still running, and could
    no longer be ended. Every active session now comes before the ended ones,
    so the page cuts only from history.
    """
    return await fetch_all(
        conn,
        """
        SELECT s.id, s.app_id, a.name AS app_name, s.workspace_id, s.version_number,
               s.launched_by, coalesce(u.display_name, u.email) AS launched_by_name,
               s.created_at, s.expires_at, s.ended_at,
               (s.ended_at IS NULL AND s.expires_at > now()) AS active
          FROM kiosk_sessions s
          LEFT JOIN canvas_apps a ON a.id = s.app_id
          LEFT JOIN users u ON u.id = s.launched_by
         WHERE s.organisation_id = :oid
         ORDER BY (s.ended_at IS NULL AND s.expires_at > now()) DESC, s.created_at DESC
         LIMIT :page
        """,
        {"oid": str(organisation_id), "page": SESSION_PAGE},
    )


async def end(conn: AsyncConnection, session_id: UUID, *, by: UUID) -> bool:
    """End a session; True if it was running. p.610's "Exit kiosk mode" and
    p.611's administrator ending one from the launch history are this."""
    row = await fetch_one(
        conn,
        """
        UPDATE kiosk_sessions SET ended_at = now(), ended_by = :by
         WHERE id = :sid AND ended_at IS NULL
        RETURNING id
        """,
        {"sid": str(session_id), "by": str(by)},
    )
    return row is not None


def _parse(raw: Any) -> Any:
    return json.loads(raw) if isinstance(raw, str) else raw
