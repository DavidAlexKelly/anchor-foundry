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
import ipaddress
import json
import secrets as token_source
import time
from datetime import datetime, timezone
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

#: p.261: "HTTPS listeners are rate-limited at approximately 100 requests per
#: second". Per listener, counted in the database (db 0110) so it holds
#: across API tasks.
RATE_PER_SECOND = 100

#: The generic schemes (p.265's "security protocols laid out by those external
#: systems"). `none` is p.262's "custom, basic authentication listener" with
#: nothing to check, for a sender that signs nothing: the endpoint's random
#: path is then the only secret, and the screen says so.
VERIFICATIONS = ("none", "basic", "header_secret", "hmac_sha256", "hmac_sha256_base64",
                 "slack_v0", "stripe_v1", "query_token")

#: The schemes that read a named header, which is then stored and redacted.
HEADER_SCHEMES = ("header_secret", "hmac_sha256", "hmac_sha256_base64", "slack_v0", "stripe_v1")

#: How stale a signed timestamp may be (Slack and Stripe both sign one, and
#: both say five minutes), so a captured request cannot be replayed later.
TOLERANCE_SECONDS = 300

#: p.262's named listeners (§518): each fixes its scheme and the header it
#: reads, so its author gives only the secret. `"*"` is a header the author
#: names; None is a scheme with no header. The first scheme is the default.
LISTENER_TYPES: dict[str, dict[str, Any]] = {
    "custom": {"label": "Custom", "schemes": {
        "none": None, "basic": None, "header_secret": "*", "hmac_sha256": "*",
        "hmac_sha256_base64": "*", "query_token": None}},
    # p.285: "In the field for Message Signing Secret, enter the Signing Secret".
    "slack": {"label": "Slack", "schemes": {"slack_v0": "X-Slack-Signature"}},
    # p.279: "You can also set up without a signing secret."
    "jira": {"label": "Jira", "schemes": {"hmac_sha256": "X-Hub-Signature", "none": None}},
    "github": {"label": "GitHub", "schemes": {"hmac_sha256": "X-Hub-Signature-256"}},
    "gitlab": {"label": "GitLab", "schemes": {"header_secret": "X-Gitlab-Token"}},
    "stripe": {"label": "Stripe", "schemes": {"stripe_v1": "Stripe-Signature"}},
    "shopify": {"label": "Shopify", "schemes": {"hmac_sha256_base64": "X-Shopify-Hmac-Sha256"}},
    # p.274: "enter your shared secret into the URL field as a query parameter
    # after the listener endpoint URL. Example: ?token=<YOUR_TOKEN>".
    "pubsub": {"label": "Google Cloud Pub/Sub", "schemes": {"query_token": None}},
}

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
    # Which schemes exist is `resolve`'s question, answered per type before
    # this is asked.
    if verification == "none":
        if header or secret:
            raise ListenerError("a listener that verifies nothing has no header or secret")
        return
    if not secret:
        raise ListenerError(f"{verification} verification needs a secret")
    needs_header = verification in HEADER_SCHEMES
    if needs_header and not header:
        raise ListenerError(f"{verification} verification needs the header it arrives in")
    if not needs_header and header:
        raise ListenerError(
            "basic verification reads the Authorization header, so it takes no other"
            if verification == "basic"
            else f"{verification} verification reads the endpoint's query string, so it takes no header")
    if verification == "basic" and ":" not in secret:
        raise ListenerError("basic verification's secret is username:password")


def resolve(listener_type: str, verification: str | None, header: str | None,
            secret: str | None) -> tuple[str, str | None]:
    """A type's scheme and header, from what its author chose (§518).

    A named type fixes the header, so one given for it is refused rather
    than ignored (§214), and a scheme the type does not use is refused by
    naming the ones it does.
    """
    kind = LISTENER_TYPES.get(listener_type)
    if kind is None:
        raise ListenerError(
            f"listener_type must be one of {', '.join(LISTENER_TYPES)}, not {listener_type!r}")
    schemes: dict[str, str | None] = kind["schemes"]
    chosen = verification or next(iter(schemes))
    if chosen not in schemes:
        raise ListenerError(f"a {kind['label']} listener verifies with {', '.join(schemes)}")
    fixed = schemes[chosen]
    if fixed not in (None, "*"):
        if header:
            raise ListenerError(f"a {kind['label']} listener always reads {fixed}")
        header = fixed
    check_configuration(chosen, header, secret)
    return chosen, header


def _signed_at(stamp: str, now: float) -> bool:
    """Whether a signed timestamp is a whole number of seconds within the
    tolerance of now, either side."""
    return stamp.isdigit() and abs(now - int(stamp)) <= TOLERANCE_SECONDS


def verify(verification: str, header: str | None, secret: str | None,
           headers: Mapping[str, str], body: bytes, *,
           query: Mapping[str, str] | None = None, now: float = 0.0) -> bool:
    """Whether a request passes its listener's scheme.

    Every comparison is `hmac.compare_digest`, so how long a refusal takes says
    nothing about how much of a guess was right.
    """
    if verification == "none":
        return True
    assert secret is not None
    if verification == "query_token":
        return hmac.compare_digest((query or {}).get("token", "").encode(), secret.encode())
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
    if verification == "hmac_sha256_base64":
        digest = hmac.new(secret.encode(), body, hashlib.sha256).digest()
        return hmac.compare_digest(given.encode(), base64.b64encode(digest))
    if verification == "slack_v0":
        # Slack signs `v0:{timestamp}:{body}` and sends the timestamp beside
        # the signature, so a stale one is a replay.
        stamp = headers.get("x-slack-request-timestamp", "")
        if not _signed_at(stamp, now):
            return False
        expected = "v0=" + hmac.new(secret.encode(), f"v0:{stamp}:".encode() + body,
                                    hashlib.sha256).hexdigest()
        return hmac.compare_digest(given.encode(), expected.encode())
    if verification == "stripe_v1":
        # `t=1492774577,v1=5257a…,v1=…`: the time and one or more signatures of
        # `{t}.{body}` in one header. Any v1 that matches will do, since Stripe
        # sends two while a secret is being rolled.
        parts = [item.split("=", 1) for item in given.split(",") if "=" in item]
        # No `t` is "", which `_signed_at` refuses like a stale one.
        stamp = next((v for k, v in parts if k.strip() == "t"), "")
        if not _signed_at(stamp, now):
            return False
        expected = hmac.new(secret.encode(), f"{stamp}.".encode() + body,
                            hashlib.sha256).hexdigest()
        return any(hmac.compare_digest(v.encode(), expected.encode())
                   for k, v in parts if k.strip() == "v1")
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


# ---- ingress (§520; p.254-255) ------------------------------------------------
#: db 0109's ceiling.
MAX_RANGES = 50


def check_allowlist(entries: list[str]) -> list[str]:
    """Ranges as the database will hold them: normalised (`10.1.2.3/8` is
    `10.0.0.0/8`), a bare address as its own /32 or /128, in the order given
    with repeats dropped."""
    out: list[str] = []
    for entry in entries:
        try:
            network = str(ipaddress.ip_network(entry.strip(), strict=False))
        except ValueError as exc:
            raise ListenerError(f"{entry!r} is not an IP address or range") from exc
        if network not in out:
            out.append(network)
    if len(out) > MAX_RANGES:
        raise ListenerError(f"an allowlist holds at most {MAX_RANGES} ranges")
    return out


def address_allowed(address: str | None, allowlist: list[str]) -> bool:
    """Whether a sender may reach a listener. An empty list is p.255's
    inherited ingress: no restriction of its own. An IPv4 address that
    arrives written as IPv6 (`::ffff:10.0.0.1`) is read as the IPv4 it is."""
    if not allowlist:
        return True
    try:
        ip = ipaddress.ip_address(address or "")
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return any(ip in ipaddress.ip_network(entry) for entry in allowlist)


def sender_address(peer: str | None, forwarded_for: str | None, hops: int) -> str | None:
    """The address that sent the request, behind `hops` proxies.

    Each proxy appends the address it heard from to X-Forwarded-For, so the
    entry `hops` from the right is the one the nearest trusted proxy wrote;
    everything to its left came from the sender and proves nothing. With no
    proxies it is the peer itself. Fewer entries than hops is an address
    nobody vouched for."""
    if hops <= 0:
        return peer
    entries = [e.strip() for e in (forwarded_for or "").split(",") if e.strip()]
    return entries[-hops] if len(entries) >= hops else None


async def set_allowlist(conn: AsyncConnection, project_id: UUID, listener_id: UUID,
                        entries: list[str]) -> dict[str, Any]:
    ranges = check_allowlist(entries)
    await conn.execute(text("UPDATE listeners SET ingress_allowlist = CAST(:r AS cidr[]) WHERE id = :id"),
                       {"id": str(listener_id), "r": ranges})
    # The update may reach a listener in another project this user can see;
    # `get` refuses that with a 404, and the refusal rolls the update back.
    return await get(conn, project_id, listener_id)


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
    def __init__(self, status: int, detail: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.headers = headers


async def admit(conn: AsyncConnection, token: str, *, sender: str | None = None) -> dict[str, Any]:
    """Find the listener a request is for, refuse what costs nothing to
    refuse, and count the rest against the listener's second (db 0110).

    **Its own transaction**, committed before `accept` judges the request:
    a request that then fails verification still counts, and one over the
    limit stays recorded as throttled although it is refused."""
    found = await fetch_one(conn, "SELECT * FROM listener_for_token(:t)", {"t": token})
    # An expired endpoint is as gone as one that never existed (p.259: "When
    # an endpoint expires, it will no longer be able to process events").
    if found is None or found["expired"]:
        raise Refusal(404, "no listener answers here")
    # Before anything else is said about the listener: an address outside the
    # allowlist learns only that it may not send (p.255).
    if not address_allowed(sender, found["ingress_allowlist"]):
        raise Refusal(403, "this address may not send to this listener")
    if not found["running"]:
        raise Refusal(503, "this listener is stopped")
    taken = await fetch_one(conn, "SELECT take_listener_request(:lid, :s, :limit) AS taken", {
        "lid": str(found["listener_id"]), "s": int(time.time()),
        "limit": RATE_PER_SECOND})
    assert taken is not None
    return {**found, "taken": int(taken["taken"])}


async def accept(conn: AsyncConnection, gateway: SecretsGateway, found: Mapping[str, Any],
                 headers: Mapping[str, str], body: bytes, *,
                 query: Mapping[str, str] | None = None, now: float | None = None) -> dict[str, Any]:
    """Take one admitted request, or refuse it with the status that says why.

    Returns the event's id, or for Slack's set-up handshake the challenge to
    echo (p.287: "Slack will verify that the listener is correctly set up").
    """
    if found["taken"] > RATE_PER_SECOND:
        # p.261's limit. The count is per second, so a second is the wait.
        raise Refusal(429, f"this listener takes at most {RATE_PER_SECOND} requests a second",
                      headers={"Retry-After": "1"})
    if len(body) > MAX_BODY:
        raise Refusal(413, f"a request is at most {MAX_BODY} bytes")
    secret = (gateway.get_secret(found["secret_arn"])["secret"]
              if found["secret_arn"] else None)
    if not verify(found["verification"], found["verification_header"], secret, headers, body,
                  query=query, now=time.time() if now is None else now):
        raise Refusal(401, "the request did not verify")
    challenge = slack_challenge(found["verification"], body)
    if challenge is not None:
        # The handshake is not an event: Slack sends it once, to see the
        # address answer, and nothing downstream is waiting for it.
        return {"challenge": challenge}
    row = await fetch_one(conn, """
        SELECT record_listener_event(:lid, :eid, :ct, :body, CAST(:headers AS jsonb)) AS id
    """, {"lid": str(found["listener_id"]), "eid": str(found["endpoint_id"]),
          "ct": headers.get("content-type"), "body": body,
          "headers": json.dumps(stored_headers(headers, found["verification_header"]))})
    assert row is not None
    return {"event": int(row["id"])}


def slack_challenge(verification: str, body: bytes) -> str | None:
    """Slack's URL verification: a signed `{"type": "url_verification",
    "challenge": …}` answered with the challenge. Only for a Slack-signed
    listener, since any other sender posting that shape is sending an event."""
    if verification != "slack_v0":
        return None
    try:
        payload = json.loads(body)
    except ValueError:
        return None
    if isinstance(payload, dict) and payload.get("type") == "url_verification":
        challenge = payload.get("challenge")
        return challenge if isinstance(challenge, str) else None
    return None


# ---- management --------------------------------------------------------------
_COLUMNS = """l.id, l.display_name, l.listener_type, l.verification, l.verification_header, l.running,
              l.created_at, l.updated_at, l.archived_at,
              l.ingress_allowlist::text[] AS ingress_allowlist,
              d.name AS archive_dataset_name, d.resource_id AS archive_dataset_resource_id,
              (SELECT count(*) FROM listener_events e WHERE e.listener_id = l.id
                  AND e.id > CASE WHEN d.id IS NULL THEN 0 ELSE l.archived_through END)::int
                  AS pending_events,
              (SELECT count(*) FROM listener_events e WHERE e.listener_id = l.id)::int AS events,
              (SELECT max(received_at) FROM listener_events e WHERE e.listener_id = l.id)
                  AS last_event_at,
              COALESCE((SELECT r.throttled FROM listener_rates r WHERE r.listener_id = l.id), 0)
                  AS throttled,
              (SELECT r.throttled_at FROM listener_rates r WHERE r.listener_id = l.id)
                  AS throttled_at"""


async def _endpoints(conn: AsyncConnection, listener_id: Any) -> list[dict[str, Any]]:
    return await fetch_all(conn, """
        SELECT id, token, expires_at, created_at, (expires_at IS NULL) AS active,
               (expires_at IS NOT NULL AND expires_at <= now()) AS expired
          FROM listener_endpoints WHERE listener_id = :lid
         ORDER BY created_at DESC
    """, {"lid": str(listener_id)})
    # Newest first, which puts the active one first: only a rotation makes an
    # endpoint, and the one it makes is the active one (§517).


async def list_listeners(conn: AsyncConnection, project_id: UUID) -> list[dict[str, Any]]:
    rows = await fetch_all(conn, f"""
        SELECT {_COLUMNS} FROM listeners l LEFT JOIN datasets d ON d.id = l.archive_dataset_id
         WHERE l.project_id = :pid ORDER BY lower(l.display_name)
    """, {"pid": str(project_id)})
    return [{**r, "endpoints": await _endpoints(conn, r["id"])} for r in rows]


async def get(conn: AsyncConnection, project_id: UUID, listener_id: UUID) -> dict[str, Any]:
    row = await fetch_one(conn, f"""
        SELECT {_COLUMNS}, l.secret_arn FROM listeners l
          LEFT JOIN datasets d ON d.id = l.archive_dataset_id
         WHERE l.id = :id AND l.project_id = :pid
    """, {"id": str(listener_id), "pid": str(project_id)})
    if row is None:
        raise NotFoundError("listener")
    return {**row, "endpoints": await _endpoints(conn, row["id"])}


async def create(conn: AsyncConnection, gateway: SecretsGateway, *, workspace_id: UUID,
                 project_id: UUID, display_name: str, listener_type: str,
                 verification: str | None, header: str | None, secret: str | None,
                 by: UUID) -> dict[str, Any]:
    """A listener with its first endpoint, stopped (db 0106: one that took
    traffic from the moment it existed would take it before it was set up)."""
    verification, header = resolve(listener_type, verification, header, secret)
    lid = uuid4()
    arn = gateway.put_secret(f"listener-{lid}", {"secret": secret}) if secret else None
    await conn.execute(text("""
        INSERT INTO listeners (id, workspace_id, project_id, display_name, listener_type,
                               verification, verification_header, secret_arn, created_by)
        VALUES (:id, :wid, :pid, :name, :type, :v, :h, :arn, :by)
    """), {"id": str(lid), "wid": str(workspace_id), "pid": str(project_id), "type": listener_type,
           "name": display_name.strip(), "v": verification, "h": header, "arn": arn,
           "by": str(by)})
    await conn.execute(text(
        "INSERT INTO listener_endpoints (listener_id, token) VALUES (:lid, :token)"),
        {"lid": str(lid), "token": new_token()})
    return await get(conn, project_id, lid)


async def configure(conn: AsyncConnection, gateway: SecretsGateway, project_id: UUID,
                    listener_id: UUID, *, verification: str | None, header: str | None,
                    secret: str | None) -> dict[str, Any]:
    """Change how requests are verified, within the listener's type. The
    secret is replaced whole, and a listener moved to `none` forgets it."""
    current = await get(conn, project_id, listener_id)
    verification, header = resolve(current["listener_type"], verification, header, secret)
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


# ---- endpoint rotation (§517; p.258-259) -------------------------------------
#: p.258: "you can only have a maximum of two endpoints at a time".
MAX_ENDPOINTS = 2


async def rotate(conn: AsyncConnection, project_id: UUID, listener_id: UUID,
                 expire_old_at: datetime | None) -> dict[str, Any]:
    """p.258's rotation: a new active endpoint, and the old one either kept
    until `expire_old_at` for a zero-downtime move or deleted now.

        "Generate a new endpoint, and add an expiration date for the old
         endpoint. You should now have two usable endpoints. Replace any usage
         of your old endpoint with the new endpoint. Delete the old endpoint."
         (p.258)
    """
    current = await get(conn, project_id, listener_id)
    if len(current["endpoints"]) >= MAX_ENDPOINTS:
        raise ListenerError(
            f"a listener has at most {MAX_ENDPOINTS} endpoints; delete the one being retired first")
    if expire_old_at is not None and expire_old_at <= datetime.now(timezone.utc):
        raise ListenerError("the old endpoint's expiry has to be in the future")
    [active] = [e for e in current["endpoints"] if e["active"]]
    if expire_old_at is None:
        await conn.execute(text("DELETE FROM listener_endpoints WHERE id = :id"),
                           {"id": str(active["id"])})
    else:
        await conn.execute(text("UPDATE listener_endpoints SET expires_at = :at WHERE id = :id"),
                           {"id": str(active["id"]), "at": expire_old_at})
    await conn.execute(text(
        "INSERT INTO listener_endpoints (listener_id, token) VALUES (:lid, :token)"),
        {"lid": str(listener_id), "token": new_token()})
    return await get(conn, project_id, listener_id)


def _endpoint(current: dict[str, Any], endpoint_id: UUID) -> dict[str, Any]:
    for endpoint in current["endpoints"]:
        if str(endpoint["id"]) == str(endpoint_id):
            return endpoint
    raise NotFoundError("endpoint")


async def extend(conn: AsyncConnection, project_id: UUID, listener_id: UUID,
                 endpoint_id: UUID, expires_at: datetime) -> dict[str, Any]:
    """p.259: "you can extend the expiration if more time is needed … Once an
    endpoint is expired, you can no longer modify the expiration date"."""
    current = await get(conn, project_id, listener_id)
    endpoint = _endpoint(current, endpoint_id)
    if endpoint["active"]:
        raise ListenerError("the active endpoint does not expire; rotate to retire it")
    if endpoint["expired"]:
        raise ListenerError("an expired endpoint cannot be extended; delete it and rotate again")
    if expires_at <= datetime.now(timezone.utc):
        raise ListenerError("an endpoint's expiry has to be in the future")
    await conn.execute(text("UPDATE listener_endpoints SET expires_at = :at WHERE id = :id"),
                       {"id": str(endpoint_id), "at": expires_at})
    return await get(conn, project_id, listener_id)


async def delete_endpoint(conn: AsyncConnection, project_id: UUID, listener_id: UUID,
                          endpoint_id: UUID) -> dict[str, Any]:
    """The retired one only: deleting the active endpoint would leave the
    listener with no address at all."""
    current = await get(conn, project_id, listener_id)
    endpoint = _endpoint(current, endpoint_id)
    if endpoint["active"]:
        raise ListenerError("the active endpoint cannot be deleted; rotate to replace it")
    await conn.execute(text("DELETE FROM listener_endpoints WHERE id = :id"),
                       {"id": str(endpoint_id)})
    return await get(conn, project_id, listener_id)
