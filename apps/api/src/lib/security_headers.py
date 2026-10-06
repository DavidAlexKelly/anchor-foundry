"""Headers every API response carries (§836).

There were none: no response said not to sniff its type, any site could frame
one, and nothing set a referrer policy. In production CloudFront sends `/api/*`
straight to this service, past the web app, so the API sets its own rather
than relying on the web app's (`apps/web/next.config.mjs` sets the same three
for pages).

* `X-Content-Type-Options: nosniff` - a JSON body, or a file a user uploaded,
  is what its type says and nothing a browser guesses.
* `X-Frame-Options: SAMEORIGIN` - the platform frames its own pages (an
  attachment preview, an embedded module), and nothing else may frame it.
  Not `DENY`, which would break those.
* `Referrer-Policy: strict-origin-when-cross-origin` - a link out of the
  platform tells the other site which platform, not which page.

A header a route set itself is left as it is.
"""
from __future__ import annotations

from typing import Any

HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"SAMEORIGIN"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
)


class SecurityHeaders:
    """ASGI middleware adding `HEADERS` to every HTTP response start."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def with_headers(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                # Names arrive lowercased: ASGI requires it of the app.
                present = {name for name, _ in headers}
                headers.extend((n, v) for n, v in HEADERS if n not in present)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, with_headers)
