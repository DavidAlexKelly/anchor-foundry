"""The OAuth 2.0 callback an outbound application's provider sends the person
back to (decision 0022 §3; `data-connection` p.39, p.243; §752).

**No session reaches this route.** It is a top-level navigation from another
site, which carries the session cookie and not the header the cookie path
requires (STATUS §55), so the person is who the state says: its front is their
id, and it is read under their own row-level security. A state alone would
let one person's flow, completed in another's browser, store the second's
tokens as the first's grant - so the state must also match the cookie the
browser that started it was given.
"""
from __future__ import annotations

import html
import urllib.parse
from typing import Any
from uuid import UUID

import anyio
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ..lib.db import fetch_one, user_connection
from ..services import audit, egress, egress_store, outbound_apps
from ..services import connections as conn_service
from ..services.connectors import ConnectorOperationError
from . import connections as connection_routes

router = APIRouter(prefix="/oauth", tags=["oauth"])


def _refused(message: str) -> HTMLResponse:
    """A page, because a person's browser arrives here and an API error body
    would be all they saw."""
    body = (
        "<!doctype html><meta charset=utf-8><title>Authorization</title>"
        f"<p>{html.escape(message)}</p><p><a href=\"/\">Back to the platform</a></p>"
    )
    return HTMLResponse(body, status_code=400)


def _back(path: str, outcome: str, reason: str | None = None) -> RedirectResponse:
    query = {"authorization": outcome}
    if reason:
        query["reason"] = reason[:300]
    joiner = "&" if "?" in path else "?"
    response = RedirectResponse(f"{path}{joiner}{urllib.parse.urlencode(query)}",
                                status_code=303)
    response.delete_cookie(outbound_apps.STATE_COOKIE, path="/api/oauth")
    return response


@router.get("/callback", response_model=None)
async def callback(
    request: Request,
    state: str = Query(default="", max_length=200),
    code: str | None = Query(default=None, max_length=4096),
    error: str | None = Query(default=None, max_length=200),
) -> Response:
    if not state or request.cookies.get(outbound_apps.STATE_COOKIE) != state:
        return _refused(
            "This authorization was not started in this browser, or it has already "
            "finished. Start it again from the source.")
    user_id = outbound_apps.user_of(state)
    if user_id is None:
        return _refused("This is not an authorization this platform started.")
    async with user_connection(user_id) as conn:
        found = await outbound_apps.take_state(conn, state)
    if found is None:
        return _refused(
            "This authorization took longer than ten minutes, or has already been used. "
            "Start it again from the source.")
    back = str(found["return_to"])
    if error:
        # p.40: the person may have declined at the provider, which is theirs
        # to do and not a fault here.
        return _back(back, "denied", error)
    if not code:
        return _back(back, "failed", "the provider sent no code")

    connection_id = UUID(str(found["connection_id"]))
    async with user_connection(user_id) as conn:
        row = await fetch_one(conn, """
            SELECT id, config, secret_arn, resource_id, workspace_id, project_id
              FROM connections WHERE id = :id
        """, {"id": str(connection_id)})
        if row is None:
            return _back(back, "failed", "the source is gone")
        policies = await egress_store.for_connection(conn, connection_id)
    config: Any = row["config"]
    if isinstance(config, str):
        import json

        config = json.loads(config)
    secret = conn_service.secret_values_for(connection_routes.secrets_gateway(), dict(row))

    def trade() -> dict[str, str]:
        # §263: the token endpoint is the source's destination, inside its own
        # allowlist like every other call to it.
        with egress.restricted_to(policies):
            return outbound_apps.exchange(config, secret, code=code,
                                          verifier=str(found["code_verifier"]))

    try:
        values = await anyio.to_thread.run_sync(trade)
    except (ConnectorOperationError, egress.EgressRefused) as exc:
        return _back(back, "failed", str(exc))

    async with user_connection(user_id) as conn:
        await outbound_apps.save_grant(conn, connection_routes.secrets_gateway(),
                                       connection_id=connection_id, user_id=user_id,
                                       values=values)
        person = await fetch_one(conn, "SELECT organisation_id FROM users WHERE id = :id",
                                 {"id": str(user_id)})
        if person is not None:
            await audit.record(
                conn, organisation_id=UUID(str(person["organisation_id"])), user_id=user_id,
                action="connection.authorization.grant", resource_type="connection",
                resource_id=connection_id, workspace_id=UUID(str(row["workspace_id"])),
                project_id=UUID(str(row["project_id"])) if row["project_id"] else None,
                metadata={"scope": values.get("scope")},
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
            )
    return _back(back, "granted")
