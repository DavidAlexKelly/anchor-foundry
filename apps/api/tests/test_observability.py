"""A request id, a structured line per request, metrics, and an unhandled error
that can be found again (§802; roadmap phase 3, E.3).

> "No error tracking, no structured logging worth querying, no metrics, no
> alerting. The first incident will be diagnosed by SSH and guesswork."
> (`docs/roadmap-phase-3-fidelity.md` E.3)
"""
from __future__ import annotations

import json
import logging
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.lib import observability  # noqa: E402
from src.main import create_app  # noqa: E402


@pytest.fixture
def app():
    made = create_app()

    @made.get("/api/_boom/{thing}", include_in_schema=False)
    async def boom(thing: str) -> dict:
        raise RuntimeError(f"the {thing} broke")

    @made.get("/api/_own_id", include_in_schema=False)
    async def own_id():
        from starlette.responses import JSONResponse
        return JSONResponse({}, headers={"X-Request-ID": "made-up-by-the-route"})

    return made


@pytest.fixture
def client(app) -> TestClient:
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class Lines(logging.Handler):
    """What a log store would receive, as the formatter writes it."""

    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(observability.JsonFormatter())
        self.addFilter(observability.RequestIdFilter())
        self.lines: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(json.loads(self.format(record)))


@pytest.fixture
def logged():
    handler = Lines()
    logger = logging.getLogger("anchor")
    logger.addHandler(handler)
    yield handler.lines
    logger.removeHandler(handler)


def metrics_of(client) -> str:
    r = client.get("/api/metrics")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/plain; version=0.0.4")
    return r.text


# ---- the request id ------------------------------------------------------------

def test_every_response_says_its_request_id(client) -> None:
    first = client.get("/api/nowhere").headers["x-request-id"]
    second = client.get("/api/nowhere").headers["x-request-id"]
    assert len(first) == 32 and first != second


def test_a_callers_id_is_carried_when_it_is_safe_to(client) -> None:
    assert client.get("/api/nowhere", headers={"X-Request-ID": "alb-1.2_x"}).headers[
        "x-request-id"] == "alb-1.2_x"
    for unsafe in ("x" * 65, "a b", "a\"b", "a;b"):
        got = client.get("/api/nowhere", headers={"X-Request-ID": unsafe}).headers[
            "x-request-id"]
        assert got != unsafe and len(got) == 32, unsafe


def test_the_id_is_the_requests_alone(client) -> None:
    """A route that names its own id is overruled, and there is one header."""
    r = client.get("/api/_own_id", headers={"X-Request-ID": "mine"})
    assert r.headers.get_list("x-request-id") == ["mine"]


def test_what_is_not_a_request_passes_through_untouched(logged) -> None:
    """The lifespan and a websocket are not requests: not timed, not logged."""
    import anyio

    seen = []

    async def inner(scope, receive, send):
        seen.append(scope["type"])
        await send({"type": "lifespan.startup.complete"})

    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "lifespan.startup"}

    middleware = observability.RequestContext(inner, observability.Metrics())
    anyio.run(middleware, {"type": "lifespan"}, receive, send)
    assert seen == ["lifespan"] and sent == [{"type": "lifespan.startup.complete"}]
    assert not logged and not middleware.metrics.requests


def test_request_id_from() -> None:
    assert observability.request_id_from("abc") == "abc"
    assert observability.request_id_from("a" * 64) == "a" * 64
    assert observability.request_id_from("") != ""
    assert observability.request_id_from(None) != observability.request_id_from(None)


# ---- the access line -----------------------------------------------------------

def test_one_line_per_request_naming_the_route_not_the_path(client, logged) -> None:
    r = client.get("/api/workspaces/not-a-uuid/object-types/also-not?token=secret",
                   headers={"X-Request-ID": "req-1"})
    access = [line for line in logged if line["logger"] == "anchor.access"]
    assert len(access) == 1, logged
    line = access[0]
    assert line["request_id"] == "req-1"
    assert line["method"] == "GET" and line["status"] == r.status_code
    # The template: no id, no query, nothing a token could hide in.
    assert line["route"] == "/api/workspaces/{workspace_id}/object-types/{type_id}"
    assert "secret" not in json.dumps(line) and "not-a-uuid" not in json.dumps(line)
    assert isinstance(line["duration_ms"], float) and line["duration_ms"] >= 0
    assert line["level"] == "info" and line["ts"].endswith("+00:00")


def test_a_path_no_route_matches_is_counted_as_one(client, logged) -> None:
    client.get("/api/does-not-exist-1")
    client.get("/api/does-not-exist-2")
    assert [line["route"] for line in logged if line["logger"] == "anchor.access"] == [
        "unmatched", "unmatched"]


# ---- metrics -------------------------------------------------------------------

def test_requests_are_counted_by_route_and_status_class(client) -> None:
    client.get("/api/does-not-exist")
    client.get("/api/does-not-exist")
    client.get("/api/_boom/pump")
    text = metrics_of(client)
    assert 'anchor_http_requests_total{method="GET",route="unmatched",status="4xx"} 2' in text
    assert ('anchor_http_requests_total{method="GET",route="/api/_boom/{thing}",'
            'status="5xx"} 1') in text
    assert "anchor_unhandled_errors_total 1" in text
    # Asking for the metrics is not itself counted - not even the second time.
    assert "/api/metrics" not in text and "/api/metrics" not in metrics_of(client)


def test_latency_is_a_cumulative_histogram(client) -> None:
    for _ in range(3):
        client.get("/api/does-not-exist")
    lines = [line for line in metrics_of(client).splitlines()
             if line.startswith('anchor_http_request_duration_seconds_bucket{route="unmatched"')]
    counts = [int(line.rsplit(" ", 1)[1]) for line in lines]
    assert len(counts) == len(observability.LATENCY_BUCKETS) + 1
    assert counts == sorted(counts) and counts[-1] == 3
    assert lines[-1].startswith('anchor_http_request_duration_seconds_bucket{route="unmatched",'
                                'le="+Inf"}')
    assert 'anchor_http_request_duration_seconds_count{route="unmatched"} 3' in metrics_of(client)


def test_metrics_can_require_a_token(client, monkeypatch) -> None:
    monkeypatch.setenv("METRICS_TOKEN", "s3cret")
    assert client.get("/api/metrics").status_code == 401
    assert client.get("/api/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/metrics",
                      headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_a_histogram_puts_each_duration_in_its_own_bucket() -> None:
    m = observability.Metrics()
    m.observe("GET", "/r", 200, 0.004)
    m.observe("GET", "/r", 200, 0.01)   # on an edge: in that bucket
    m.observe("GET", "/r", 503, 60.0)   # past every edge: only +Inf
    text = m.exposition()
    assert 'anchor_http_request_duration_seconds_bucket{route="/r",le="0.005"} 1' in text
    assert 'anchor_http_request_duration_seconds_bucket{route="/r",le="0.01"} 2' in text
    assert 'anchor_http_request_duration_seconds_bucket{route="/r",le="10.0"} 2' in text
    assert 'anchor_http_request_duration_seconds_bucket{route="/r",le="+Inf"} 3' in text
    assert 'anchor_http_request_duration_seconds_sum{route="/r"} 60.014000' in text
    assert 'anchor_http_requests_total{method="GET",route="/r",status="5xx"} 1' in text


def test_a_label_is_escaped() -> None:
    m = observability.Metrics()
    m.observe("GET", 'a"b\\c', 200, 0.1)
    assert 'route="a\\"b\\\\c"' in m.exposition()


# ---- an unhandled error --------------------------------------------------------

def test_an_unhandled_error_is_findable_by_the_id_its_500_quotes(client, logged) -> None:
    r = client.get("/api/_boom/pump", headers={"X-Request-ID": "incident-7"})
    assert r.status_code == 500
    assert r.json()["request_id"] == "incident-7"
    assert r.headers["x-request-id"] == "incident-7"
    assert "pump" not in r.text  # the error's own words stay in the log
    errors = [line for line in logged if line["logger"] == "anchor.error"]
    assert len(errors) == 1, logged
    error = errors[0]
    assert error["request_id"] == "incident-7"
    assert error["error"] == "RuntimeError" and error["route"] == "/api/_boom/{thing}"
    assert "RuntimeError: the pump broke" in error["exception"]
    access = [line for line in logged if line["logger"] == "anchor.access"]
    assert [(a["request_id"], a["status"]) for a in access] == [("incident-7", 500)]


def test_a_handled_refusal_is_not_an_error(client, logged) -> None:
    """A 404 or a 422 is the API working; only the unhandled is an error."""
    client.get("/api/does-not-exist")
    assert not [line for line in logged if line["logger"] == "anchor.error"]
    assert "anchor_unhandled_errors_total 0" in metrics_of(client)


# ---- the logging itself --------------------------------------------------------

def test_logging_is_configured_once_and_not_twice() -> None:
    observability.configure_logging()
    observability.configure_logging()
    root = logging.getLogger("anchor")
    assert sum(isinstance(h.formatter, observability.JsonFormatter) for h in root.handlers) == 1
    assert root.propagate is False


def test_a_line_outside_a_request_has_no_id() -> None:
    record = logging.LogRecord("anchor.x", logging.WARNING, __file__, 1, "hi %s", ("there",), None)
    observability.RequestIdFilter().filter(record)
    line = json.loads(observability.JsonFormatter().format(record))
    assert line["message"] == "hi there" and line["level"] == "warning"
    assert "request_id" not in line
