"""Renewing a browser session from Cognito's refresh token (§859).

An access token lives fifteen minutes (`infra/cdk/src/constructs/auth.ts`),
and the session cookie carried nothing else, so every deployed session ended
fifteen minutes in: the next request was a 401 and a full-page trip through
sign-in, taking any unsaved work - a module being built, a form half filled -
with it. Cognito issues a refresh token for thirty days alongside, and the
browser threw it away.

The refresh token is now kept in a cookie of its own, which only the renewal
route is sent, and this asks Cognito's token endpoint for a new access token
with it. Server side, because the cookie is httpOnly: no script on the page
can read the token that outlives it.

`urllib` in a thread rather than an HTTP client library, because the API's
runtime has none and one call every fifteen minutes does not justify adding
one.
"""
from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request


class RefreshRefused(Exception):
    """Cognito will not renew this session: the refresh token is expired,
    revoked, or for another app client. Signing in again is the only way on."""


class RefreshUnavailable(Exception):
    """Cognito could not be asked. The session may still be renewable."""


def _exchange(domain: str, client_id: str, refresh_token: str, timeout: float) -> str:
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": refresh_token,
    }).encode()
    request = urllib.request.Request(
        f"{domain.rstrip('/')}/oauth2/token", data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            answer = json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        # The token endpoint answers a bad grant with 400 (RFC 6749 §5.2) and
        # a bad client with 400 or 401; anything else is Cognito having
        # trouble, not this session being over.
        if exc.code in (400, 401):
            raise RefreshRefused(_reason(exc)) from exc
        raise RefreshUnavailable(f"the token endpoint answered {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise RefreshUnavailable(f"the token endpoint could not be reached: {exc}") from exc
    token = answer.get("access_token") if isinstance(answer, dict) else None
    if not isinstance(token, str) or not token:
        raise RefreshUnavailable("the token endpoint returned no access token")
    return token


def _reason(exc: urllib.error.HTTPError) -> str:
    try:
        answer = json.loads(exc.read() or b"{}")
    except ValueError:
        answer = {}
    return str(answer.get("error") or f"refused ({exc.code})")


async def refreshed_access_token(
    domain: str, client_id: str, refresh_token: str, *, timeout: float = 10.0,
) -> str:
    """A new access token for this refresh token, from the hosted UI's token
    endpoint. The app client is public (no secret, PKCE), so the client id is
    all it is asked for."""
    return await asyncio.to_thread(_exchange, domain, client_id, refresh_token, timeout)
