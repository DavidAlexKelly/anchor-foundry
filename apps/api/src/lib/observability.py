"""Observability: a request id, one structured line per request, metrics, and
an unhandled error that can be found again (roadmap phase 3, E.3; §802).

`docs/roadmap-phase-3-fidelity.md` E.3: "No error tracking, no structured
logging worth querying, no metrics, no alerting. The first incident will be
diagnosed by SSH and guesswork." This is the part of that which lives in the
process; alerting is the deployment's, and reads what this emits.

- **A request id** on every response (`X-Request-ID`). A caller's own id is
  kept when it is safe to echo, so a trace that started at the load balancer
  or in the browser carries through; anything else is replaced. Every log
  line written while the request is being handled carries it too
  (`RequestIdFilter`), so one id finds the access line, the error and
  whatever the code logged in between.
- **One JSON line per request** on the `anchor.access` logger: method, the
  *route template* rather than the path (a path holds ids, and sometimes a
  token in its query - the template is what you group by and leaks nothing),
  status and duration.
- **Metrics** at `/api/metrics`, in Prometheus' text format: requests by
  method, route and status class, and a latency histogram per route. Kept in
  the process, which is right for this deployment: the image runs one
  uvicorn process per task (`Dockerfile`), so a scrape per task sees all of
  it. `METRICS_TOKEN`, when set, is required as a bearer token.
- **An unhandled error** is logged with its traceback and request id on
  `anchor.error`, and the 500 says the id - so the person who saw it can
  hand over the one thing that finds it.

No dependency: a counter and a histogram are a dict and a list, and the
exposition format is a few lines of text.
"""
from __future__ import annotations

import contextvars
import hmac
import json
import logging
import os
import re
import time
import traceback
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: The id of the request being handled, for every log line written during it.
request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None)

#: An inbound id is echoed only if it looks like an id: bounded, and nothing
#: a log line or a header could be made to misread.
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

#: Seconds. Prometheus' own defaults, which suit an API whose interesting
#: requests run from a few milliseconds to a dataset build's tens of seconds.
LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

#: What a request no route matched is counted as. Grouping by the raw path
#: would let anyone grow the metrics without bound by asking for paths that
#: do not exist.
UNMATCHED = "unmatched"

METRICS_PATH = "/api/metrics"

access_log = logging.getLogger("anchor.access")
error_log = logging.getLogger("anchor.error")


def request_id_from(header: str | None) -> str:
    """The caller's id when it is safe to carry on, else a new one."""
    if header and _SAFE_ID.match(header):
        return header
    return uuid.uuid4().hex


class Metrics:
    """Request counts and latencies, by method, route and status class."""

    def __init__(self) -> None:
        self.requests: dict[tuple[str, str, str], int] = defaultdict(int)
        # Per route: a count per bucket (cumulative is computed on exposition),
        # the overflow, the sum and the count.
        self.buckets: dict[str, list[int]] = defaultdict(
            lambda: [0] * (len(LATENCY_BUCKETS) + 1))
        self.sums: dict[str, float] = defaultdict(float)
        self.errors = 0

    def observe(self, method: str, route: str, status: int, seconds: float) -> None:
        self.requests[(method, route, f"{status // 100}xx")] += 1
        slot = next((i for i, edge in enumerate(LATENCY_BUCKETS) if seconds <= edge),
                    len(LATENCY_BUCKETS))
        self.buckets[route][slot] += 1
        self.sums[route] += seconds

    def exposition(self) -> str:
        """Prometheus' text format, 0.0.4."""
        out = [
            "# HELP anchor_http_requests_total Requests handled, by method, route and status class.",
            "# TYPE anchor_http_requests_total counter",
        ]
        for (method, route, status), n in sorted(self.requests.items()):
            out.append(f'anchor_http_requests_total{{method="{method}",'
                       f'route="{_label(route)}",status="{status}"}} {n}')
        out += [
            "# HELP anchor_http_request_duration_seconds Time to handle a request, by route.",
            "# TYPE anchor_http_request_duration_seconds histogram",
        ]
        for route in sorted(self.buckets):
            counts, running = self.buckets[route], 0
            for edge, n in zip(LATENCY_BUCKETS, counts):
                running += n
                out.append(f'anchor_http_request_duration_seconds_bucket{{route="{_label(route)}",'
                           f'le="{edge}"}} {running}')
            total = running + counts[-1]
            out.append(f'anchor_http_request_duration_seconds_bucket{{route="{_label(route)}",'
                       f'le="+Inf"}} {total}')
            out.append(f'anchor_http_request_duration_seconds_sum{{route="{_label(route)}"}} '
                       f'{self.sums[route]:.6f}')
            out.append(f'anchor_http_request_duration_seconds_count{{route="{_label(route)}"}} '
                       f'{total}')
        out += [
            "# HELP anchor_unhandled_errors_total Requests that ended in an unhandled error.",
            "# TYPE anchor_unhandled_errors_total counter",
            f"anchor_unhandled_errors_total {self.errors}",
        ]
        return "\n".join(out) + "\n"


def _label(value: str) -> str:
    """A label value as the exposition format escapes it."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


#: Where `main` mounts every router.
API_PREFIX = "/api"


def route_template(scope: Scope) -> str:
    """The matched route's template, `UNMATCHED` when nothing matched.

    **Prefixed here when the route does not carry the prefix itself** (§837).
    FastAPI 0.111 copied an included router's routes with the include's prefix
    in their paths; from 0.12x it includes routers lazily, and the route a
    request matched knows only its own router's path - `/workspaces/...` where
    a dashboard has always grouped `/api/workspaces/...`. Every router is
    included under `API_PREFIX` and the app's own routes spell it out, so the
    full template is one of the two, on either version.
    """
    path = getattr(scope.get("route"), "path", None)
    if not path:
        return UNMATCHED
    return path if path.startswith(API_PREFIX) else API_PREFIX + path


class RequestContext:
    """Pure ASGI, so a streamed response streams: Starlette's
    `BaseHTTPMiddleware` buffers, and a dataset download is the one place that
    would be felt."""

    def __init__(self, app: ASGIApp, metrics: Metrics) -> None:
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                   for k, v in scope.get("headers", [])}
        request_id = request_id_from(headers.get("x-request-id"))
        # Not reset afterwards: every request runs in its own task, which
        # works on its own copy of the context, so nothing outlives it.
        request_id_var.set(request_id)
        # Also on the request itself: the handler for an unhandled error runs
        # in Starlette's outermost middleware, after this one has finished
        # and the context variable is gone.
        scope.setdefault("state", {})["request_id"] = request_id
        started = time.perf_counter()
        status = 500

        async def stamped(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
                message["headers"] = [
                    *[(k, v) for k, v in message.get("headers", [])
                      if k.lower() != b"x-request-id"],
                    (b"x-request-id", request_id.encode("latin-1")),
                ]
            await send(message)

        try:
            await self.app(scope, receive, stamped)
        finally:
            elapsed = time.perf_counter() - started
            route = route_template(scope)
            if scope.get("path") != METRICS_PATH:
                self.metrics.observe(scope["method"], route, status, elapsed)
            access_log.info("request", extra={"fields": {
                "method": scope["method"], "route": route, "status": status,
                "duration_ms": round(elapsed * 1000, 2),
            }})


class RequestIdFilter(logging.Filter):
    """Every record written while a request is handled carries its id."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line: what a log store can query."""

    def format(self, record: logging.LogRecord) -> str:
        body: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None)
        if request_id:
            body["request_id"] = request_id
        body.update(getattr(record, "fields", None) or {})
        if record.exc_info:
            body["exception"] = "".join(traceback.format_exception(*record.exc_info))
        return json.dumps(body, default=str)


def configure_logging() -> None:
    """Structured lines on stderr for the `anchor` loggers, once.

    Only `anchor.*`: the root logger and uvicorn's own are left as the server
    configured them, so a developer's terminal still reads as it did.
    """
    root = logging.getLogger("anchor")
    if any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RequestIdFilter())
    root.addHandler(handler)
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
    # Its own handler; not also the root's, or a configured root prints twice.
    root.propagate = False


def install(app: Any) -> Metrics:
    """Wire all of it into a FastAPI app; the metrics, for a test to read."""
    configure_logging()
    metrics = Metrics()
    app.add_middleware(RequestContext, metrics=metrics)

    @app.get(METRICS_PATH, include_in_schema=False)
    async def metrics_endpoint(request: Request) -> Response:
        wanted = os.environ.get("METRICS_TOKEN", "")
        if not wanted and os.environ.get("ECS_CONTAINER_METADATA_URI_V4"):
            # **Closed on a stack unless a token opens it (§884).** Through
            # CloudFront this was public: every route, its traffic and its
            # error rate, for anyone to read. Nothing on a stack scrapes it -
            # its alarms count log lines (§815) - so a deployment that wants
            # it sets METRICS_TOKEN and its scraper sends it.
            return PlainTextResponse("not found\n", status_code=404)
        if wanted:
            given = request.headers.get("authorization", "")
            if not hmac.compare_digest(given.encode(), f"Bearer {wanted}".encode()):
                return PlainTextResponse("unauthorised\n", status_code=401)
        return PlainTextResponse(metrics.exposition(),
                                 media_type="text/plain; version=0.0.4")

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        metrics.errors += 1
        request_id = getattr(request.state, "request_id", None) or request_id_from(None)
        error_log.error("unhandled error", exc_info=exc, extra={"fields": {
            "request_id": request_id,
            "method": request.method,
            "route": route_template(request.scope),
            "error": type(exc).__name__,
        }})
        return JSONResponse(
            status_code=500,
            content={"detail": "Something went wrong on our side. Quote this id if you "
                               "report it.", "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )

    return metrics
