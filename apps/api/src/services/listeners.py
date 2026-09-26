"""HTTPS listeners (§516; db 0106; `data-connection` p.249-266).

    "data connection listeners provision a URL endpoint, implement the
     specific message signing or other verification schemes for specific
     external systems, and allow a simple and low-latency mechanism to receive
     data feeds" (p.249)

Two halves. The **management** half is ordinary project-scoped reads and
writes under the caller's RLS. The **request** half runs with no user at
all: `accept` is everything an outside sender can make happen, and it goes
through db 0106's two SECURITY DEFINER functions and nothing else.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets as token_source
from typing import Any, AsyncIterator, Mapping
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import NotFoundError
from .secrets import SecretsGateway

#: p.262: "Individual event and request payloads are limited to 1 MB in size
#: … Foundry rejects events that exceed this limit."
MAX_BODY = 1_048_576

#: The generic schemes (p.265's "security protocols laid out by those external
#: systems"). `none` is p.262's "custom, basic authentication listener" with
#: nothing to check, for a sender that signs nothing: the endpoint's random
#: path is then the only secret, and the screen says so.
VERIFICATIONS = ("none", "basic", "header_secret", "hmac_sha256")

#: Headers never stored, because they are how a sender authenticates. p.265:
#: "A minimal set of redactions is sometimes performed on incoming data".
ALWAYS_REDACTED = frozenset({"authorization", "proxy-authorization", "cookie"})

#: How much of a body the event list shows. The whole body is kept.
PREVIEW_CHARS = 2000


class ListenerError(ValueError):
    """Refusal of a listener's configuration, phrased for its author."""


def new_token() -> str:
    """An endpoint's path segment: 43 URL-safe characters from 32 random bytes."""
    return token_source.token_urlsafe(32)


def check_configuration(verification: str, header: str | None, secret: str | None) -> None:
    if verification not in VERIFICATIONS:
        raise ListenerError(
            f"verification must be one of {', '.join(VERIFICATIONS)}, not {verification!r}")
    if verification == "none":
        if header or secret:
            raise ListenerError("a listener that verifies nothing has no header or secret")
        return
    if not secret:
        raise ListenerError(f"{verification} verification needs a secret")
    needs_header = verification in ("header_secret", "hmac_sha256")
    if needs_header and not header:
        raise ListenerError(f"{verification} verification needs the header it arrives in")
    if not needs_header and header:
        raise ListenerError("basic verification reads the Authorization header, so it takes no other")
    if verification == "basic" and ":" not in secret:
        raise ListenerError("basic verification's secret is username:password")


def verify(verification: str, header: str | None, secret: str | None,
           headers: Mapping[str, str], body: bytes) -> bool:
    """Whether a request passes its listener's scheme.

    Every comparison is `hmac.compare_digest`, so how long a refusal takes says
    nothing about how much of a guess was right.
    """
    if verification == "none":
        return True
    assert secret is not None
    if verification == "basic":
        given = headers.get("authorization", "")
        if not given.lower().startswith("basic "):
            return False
        try:
            decoded = base64.b64decode(given[6:].strip(), validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            return False
        return hmac.compare_digest(decoded.encode(), secret.encode())
    assert header is not None
    given = headers.get(header.lower(), "")
    if verification == "header_secret":
        return hmac.compare_digest(given.encode(), secret.encode())
    # hmac_sha256: a hex digest of the body, with or without GitHub's
    # `sha256=` prefix.
    if given.lower().startswith("sha256="):
        given = given[7:]
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(given.lower().encode(), expected.encode())


def stored_headers(headers: Mapping[str, str], verification_header: str | None) -> dict[str, str]:
    """The request's headers as kept with the event, credentials removed:
    the standard ones, and the header this listener's own secret or signature
    arrives in."""
    hidden = set(ALWAYS_REDACTED)
    if verification_header:
        hidden.add(verification_header.lower())
    return {k.lower(): ("[redacted]" if k.lower() in hidden else v) for k, v in headers.items()}


# ---- the request path --------------------------------------------------------
async def read_capped(chunks: AsyncIterator[bytes], limit: int) -> bytes:
    """A request body, read only until it is past `limit`.

    Enough to know a body is too big, and no more: `accept` refuses anything
    longer than the limit, so what is past the first extra chunk would be read
    only to be thrown away, and a sender could make that as much as it liked.
    """
    body = b""
    async for chunk in chunks:
        body += chunk
        if len(body) > limit:
            break
    return body



class Refusal(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


async def accept(conn: AsyncConnection, gateway: SecretsGateway, token: str,
                 headers: Mapping[str, str], body: bytes) -> int:
    """Take one request, or refuse it with the status that says why."""
    found = await fetch_one(conn, "SELECT * FROM listener_for_token(:t)", {"t": token})
    # An expired endpoint is as gone as one that never existed (p.259: "When
    # an endpoint expires, it will no longer be able to process events").
    if found is None or found["expired"]:
        raise Refusal(404, "no listener answers here")
    if not found["running"]:
        raise Refusal(503, "this listener is stopped")
    if len(body) > MAX_BODY:
        raise Refusal(413, f"a request is at most {MAX_BODY} bytes")
    secret = (gateway.get_secret(found["secret_arn"])["secret"]
              if found["secret_arn"] else None)
    if not verify(found["verification"], found["verification_header"], secret, headers, body):
        raise Refusal(401, "the request did not verify")
    row = await fetch_one(conn, """
        SELECT record_listener_event(:lid, :eid, :ct, :body, CAST(:headers AS jsonb)) AS id
    """, {"lid": str(found["listener_id"]), "eid": str(found["endpoint_id"]),
          "ct": headers.get("content-type"), "body": body,
          "headers": json.dumps(stored_headers(headers, found["verification_header"]))})
    assert row is not None
    return int(row["id"])


# ---- management --------------------------------------------------------------
_COLUMNS = """l.id, l.display_name, l.verification, l.verification_header, l.running,
              l.created_at, l.updated_at,
              (SELECT count(*) FROM listener_events e WHERE e.listener_id = l.id)::int AS events,
              (SELECT max(received_at) FROM listener_events e WHERE e.listener_id = l.id)
                  AS last_event_at"""


async def _endpoints(conn: AsyncConnection, listener_id: Any) -> list[dict[str, Any]]:
    return await fetch_all(conn, """
        SELECT id, token, expires_at, created_at, (expires_at IS NULL) AS active,
               (expires_at IS NOT NULL AND expires_at <= now()) AS expired
          FROM listener_endpoints WHERE listener_id = :lid
         ORDER BY expires_at IS NULL DESC, created_at DESC
    """, {"lid": str(listener_id)})


async def list_listeners(conn: AsyncConnection, project_id: UUID) -> list[dict[str, Any]]:
    rows = await fetch_all(conn, f"""
        SELECT {_COLUMNS} FROM listeners l WHERE l.project_id = :pid ORDER BY lower(l.display_name)
    """, {"pid": str(project_id)})
    return [{**r, "endpoints": await _endpoints(conn, r["id"])} for r in rows]


async def get(conn: AsyncConnection, project_id: UUID, listener_id: UUID) -> dict[str, Any]:
    row = await fetch_one(conn, f"""
        SELECT {_COLUMNS}, l.secret_arn FROM listeners l WHERE l.id = :id AND l.project_id = :pid
    """, {"id": str(listener_id), "pid": str(project_id)})
    if row is None:
        raise NotFoundError("listener")
    return {**row, "endpoints": await _endpoints(conn, row["id"])}


async def create(conn: AsyncConnection, gateway: SecretsGateway, *, workspace_id: UUID,
                 project_id: UUID, display_name: str, verification: str,
                 header: str | None, secret: str | None, by: UUID) -> dict[str, Any]:
    """A listener with its first endpoint, stopped (db 0106: one that took
    traffic from the moment it existed would take it before it was set up)."""
    check_configuration(verification, header, secret)
    lid = uuid4()
    arn = gateway.put_secret(f"listener-{lid}", {"secret": secret}) if secret else None
    await conn.execute(text("""
        INSERT INTO listeners (id, workspace_id, project_id, display_name, verification,
                               verification_header, secret_arn, created_by)
        VALUES (:id, :wid, :pid, :name, :v, :h, :arn, :by)
    """), {"id": str(lid), "wid": str(workspace_id), "pid": str(project_id),
           "name": display_name.strip(), "v": verification, "h": header, "arn": arn,
           "by": str(by)})
    await conn.execute(text(
        "INSERT INTO listener_endpoints (listener_id, token) VALUES (:lid, :token)"),
        {"lid": str(lid), "token": new_token()})
    return await get(conn, project_id, lid)


async def configure(conn: AsyncConnection, gateway: SecretsGateway, project_id: UUID,
                    listener_id: UUID, *, verification: str, header: str | None,
                    secret: str | None) -> dict[str, Any]:
    """Change how requests are verified. The secret is replaced whole, and a
    listener moved to `none` forgets it."""
    check_configuration(verification, header, secret)
    current = await get(conn, project_id, listener_id)
    arn = (gateway.put_secret(f"listener-{listener_id}", {"secret": secret})
           if secret else None)
    await conn.execute(text("""
        UPDATE listeners SET verification = :v, verification_header = :h, secret_arn = :arn
         WHERE id = :id
    """), {"id": str(listener_id), "v": verification, "h": header, "arn": arn})
    if arn is None and current["secret_arn"]:
        gateway.delete_secret(current["secret_arn"])
    return await get(conn, project_id, listener_id)


async def rename(conn: AsyncConnection, project_id: UUID, listener_id: UUID,
                 display_name: str) -> dict[str, Any]:
    await get(conn, project_id, listener_id)
    await conn.execute(text("UPDATE listeners SET display_name = :n WHERE id = :id"),
                       {"id": str(listener_id), "n": display_name.strip()})
    return await get(conn, project_id, listener_id)


async def set_running(conn: AsyncConnection, project_id: UUID, listener_id: UUID,
                      running: bool) -> dict[str, Any]:
    await get(conn, project_id, listener_id)
    await conn.execute(text("UPDATE listeners SET running = :r WHERE id = :id"),
                       {"id": str(listener_id), "r": running})
    return await get(conn, project_id, listener_id)


async def delete(conn: AsyncConnection, gateway: SecretsGateway, project_id: UUID,
                 listener_id: UUID) -> None:
    current = await get(conn, project_id, listener_id)
    await conn.execute(text("DELETE FROM listeners WHERE id = :id"), {"id": str(listener_id)})
    if current["secret_arn"]:
        gateway.delete_secret(current["secret_arn"])


def _preview(body: bytes) -> tuple[str | None, bool]:
    """A body as text for the list, or None when it is not text."""
    try:
        decoded = bytes(body).decode("utf-8")
    except UnicodeDecodeError:
        return None, False
    return decoded[:PREVIEW_CHARS], len(decoded) > PREVIEW_CHARS


async def events(conn: AsyncConnection, project_id: UUID, listener_id: UUID,
                 limit: int) -> list[dict[str, Any]]:
    """p.261's stream, newest first."""
    await get(conn, project_id, listener_id)
    rows = await fetch_all(conn, """
        SELECT id, received_at, content_type, size_bytes, body, headers
          FROM listener_events WHERE listener_id = :lid ORDER BY id DESC LIMIT :n
    """, {"lid": str(listener_id), "n": limit})
    out = []
    for r in rows:
        preview, truncated = _preview(r.pop("body"))
        out.append({**r, "preview": preview, "truncated": truncated})
    return out
