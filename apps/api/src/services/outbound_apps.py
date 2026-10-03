"""Outbound applications: a source called as the person using it (decision 0022;
`data-connection` p.39-40, p.243; §752).

> "When a source is configured with an outbound application, authentication is
>  delegated to an external OAuth 2.0 provider on behalf of the calling user."
>  (p.39)

A REST source whose `auth_type` is `oauth2_authorization_code` is one. Each
person authorizes it once (`start`, the provider, `finish`), which stores their
**grant**: tokens in the secrets gateway, and a row saying the grant exists.
`token_for` is what a call made as that person sends (§753).
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets as _secrets
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text as _text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_one
from ..lib.errors import ConflictError
from .connectors import ConnectorOperationError, RestConnector
from .secrets import SecretsGateway

#: How long a person has at the provider before the state is no good.
STATE_TTL = timedelta(minutes=10)

#: The cookie that binds a state to the browser that started it (decision
#: 0022 §3), scoped to the callback.
STATE_COOKIE = "anchor_oauth_state"
CALLBACK_PATH = "/api/oauth/callback"

#: Refresh this long before the provider says the token expires, so a call
#: made at the edge does not arrive with a token that lapsed in flight.
EXPIRY_MARGIN = timedelta(seconds=60)


class AuthorizationNeeded(ConnectorOperationError):
    """The caller has no usable grant: p.40's "has not completed the
    interactive authorization flow", or "Credentials expired". A connector
    failure, so every path that reports one reports this."""


def redirect_uri() -> str | None:
    """Where the provider sends the person back: the platform's public address
    (`PLATFORM_PUBLIC_URL`) and the callback. None when the deployment has not
    said, which refuses the auth type when a source is saved."""
    base = os.environ.get("PLATFORM_PUBLIC_URL", "").strip().rstrip("/")
    return f"{base}{CALLBACK_PATH}" if base else None


def is_outbound(config: dict[str, Any]) -> bool:
    return str(config.get("auth_type") or "") == "oauth2_authorization_code"


def _challenge(verifier: str) -> str:
    """RFC 7636's S256 code challenge."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def safe_return(path: str | None) -> str:
    """A path on this platform to send the person back to, never another site:
    one leading slash, not two (which a browser reads as a host)."""
    path = (path or "/").strip()
    if not path.startswith("/") or path.startswith("//") or "\\" in path:
        return "/"
    return path[:500]


async def start(
    conn: AsyncConnection, *, connection: dict[str, Any], secret: dict[str, str],
    user_id: UUID, return_to: str | None,
) -> tuple[str, str]:
    """Begin one person's authorization: keep a state and a PKCE verifier, and
    return the provider's authorize URL and the state (for the cookie)."""
    config = connection["config"]
    if not is_outbound(config):
        raise ConflictError("this source does not authenticate through an outbound application")
    callback = redirect_uri()
    if callback is None:
        raise ConflictError(
            "an outbound application needs the platform's public address, and this "
            "deployment has not set PLATFORM_PUBLIC_URL")
    if not secret.get("client_id"):
        raise ConflictError("this source's outbound application has no client_id stored")
    # The user's id leads the state, so the callback - which no session reaches
    # - can read the state as that user, under their own row-level security.
    state = f"{user_id}.{_secrets.token_urlsafe(24)}"
    verifier = _secrets.token_urlsafe(48)
    await conn.execute(_text("""
        INSERT INTO oauth_states (state, connection_id, user_id, code_verifier, return_to)
        VALUES (:state, :cid, :uid, :verifier, :back)
    """), {"state": state, "cid": str(connection["id"]), "uid": str(user_id),
           "verifier": verifier, "back": safe_return(return_to)})
    query = {"response_type": "code", "client_id": secret["client_id"],
             "redirect_uri": callback, "state": state,
             "code_challenge": _challenge(verifier), "code_challenge_method": "S256"}
    if config.get("oauth_scope"):
        query["scope"] = str(config["oauth_scope"])
    url = str(config["authorize_url"])
    joiner = "&" if urllib.parse.urlparse(url).query else "?"
    return f"{url}{joiner}{urllib.parse.urlencode(query)}", state


def user_of(state: str) -> UUID | None:
    """The user a state was made for, read off its front, or None for one
    that is not a state at all."""
    head, _, _rest = state.partition(".")
    try:
        return UUID(head)
    except ValueError:
        return None


async def take_state(conn: AsyncConnection, state: str) -> dict[str, Any] | None:
    """The state, once: it is deleted as it is read, and one older than ten
    minutes is gone however it is asked for."""
    row = await fetch_one(conn, """
        DELETE FROM oauth_states WHERE state = :state
        RETURNING connection_id, user_id, code_verifier, return_to, created_at
    """, {"state": state})
    if row is None or datetime.now(timezone.utc) - row["created_at"] > STATE_TTL:
        return None
    return row


def _grant_values(payload: dict[str, Any], previous: dict[str, str] | None = None) -> dict[str, str]:
    """A token endpoint's answer as a grant's secret. A refresh answer may
    leave the refresh token out, meaning "keep the one you have" (RFC 6749
    §6), so the previous one carries over."""
    token = payload.get("access_token")
    if not token:
        raise ConnectorOperationError("the token endpoint returned no access_token")
    values = {"access_token": str(token)}
    refresh = payload.get("refresh_token") or (previous or {}).get("refresh_token")
    if refresh:
        values["refresh_token"] = str(refresh)
    expires_in = payload.get("expires_in")
    if isinstance(expires_in, (int, float)) or (isinstance(expires_in, str) and expires_in.isdigit()):
        values["expires_at"] = str(int(time.time()) + int(expires_in))
    if payload.get("scope"):
        values["scope"] = str(payload["scope"])
    return values


async def _store(
    conn: AsyncConnection, gateway: SecretsGateway, *, connection_id: UUID, user_id: UUID,
    values: dict[str, str],
) -> dict[str, Any]:
    arn = gateway.put_secret(f"{connection_id}/grants/{user_id}", values)
    expires = (datetime.fromtimestamp(int(values["expires_at"]), timezone.utc)
               if values.get("expires_at") else None)
    row = await fetch_one(conn, """
        INSERT INTO outbound_grants (connection_id, user_id, secret_arn, scope, expires_at)
        VALUES (:cid, :uid, :arn, :scope, :expires)
        ON CONFLICT (connection_id, user_id) DO UPDATE
            SET secret_arn = EXCLUDED.secret_arn, scope = EXCLUDED.scope,
                expires_at = EXCLUDED.expires_at, granted_at = now()
        RETURNING connection_id, user_id, scope, expires_at, granted_at
    """, {"cid": str(connection_id), "uid": str(user_id), "arn": arn,
          "scope": values.get("scope"), "expires": expires})
    assert row is not None
    return dict(row)


def exchange(config: dict[str, Any], secret: dict[str, str], *, code: str,
             verifier: str) -> dict[str, str]:
    """The code and verifier, traded at the token endpoint (blocking; the
    caller runs it in a thread, inside the source's egress policies)."""
    callback = redirect_uri()
    if callback is None:
        raise ConnectorOperationError("PLATFORM_PUBLIC_URL is not set")
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": callback,
            "client_id": secret.get("client_id", ""), "code_verifier": verifier}
    if secret.get("client_secret"):
        form["client_secret"] = secret["client_secret"]
    return _grant_values(RestConnector().token_request(config, form))


async def save_grant(
    conn: AsyncConnection, gateway: SecretsGateway, *, connection_id: UUID, user_id: UUID,
    values: dict[str, str],
) -> dict[str, Any]:
    return await _store(conn, gateway, connection_id=connection_id, user_id=user_id,
                        values=values)


async def status(conn: AsyncConnection, connection_id: UUID) -> dict[str, Any] | None:
    """The caller's own grant on this source, without its tokens. Own by row
    security (db 0147): the table holds only the caller's rows for them."""
    row = await fetch_one(conn, """
        SELECT scope, expires_at, granted_at FROM outbound_grants WHERE connection_id = :cid
    """, {"cid": str(connection_id)})
    return dict(row) if row else None


async def revoke(conn: AsyncConnection, gateway: SecretsGateway, connection_id: UUID) -> bool:
    """Forget the caller's grant: the row and the tokens."""
    row = await fetch_one(conn, """
        DELETE FROM outbound_grants WHERE connection_id = :cid
        RETURNING secret_arn
    """, {"cid": str(connection_id)})
    if row is None:
        return False
    gateway.delete_secret(str(row["secret_arn"]))
    return True
