"""Every route the app serves, by the path a client calls (§837).

FastAPI 0.142 includes routers lazily: `app.routes` holds one entry per
included router, and a matched route's own `path` lacks the include's prefix.
A test that walked `app.routes` for `APIRoute`s found the app's own two and
nothing else - and one of the three that did so went on passing, having
checked nothing.
"""
from __future__ import annotations

from typing import Any

from fastapi.routing import APIRoute, iter_route_contexts


def api_routes(app: Any) -> list[tuple[str, set[str], APIRoute]]:
    """`(full path, methods, route)` for each `APIRoute` the app serves."""
    return [
        (context.path, set(context.methods or ()), context.original_route)
        for context in iter_route_contexts(app.routes)
        if isinstance(context.original_route, APIRoute)
    ]
