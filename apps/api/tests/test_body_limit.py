"""Request bodies are bounded before anything reads them (§832).

The limits are patched small here so a test can cross them cheaply; the
middleware reads them at request time, as it would the real ones.
"""
from __future__ import annotations

import os
import sys

import pytest
from fastapi import File, Request, UploadFile
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.lib import body_limit  # noqa: E402
from src.main import create_app  # noqa: E402

ran: list[str] = []


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(body_limit, "BODY_MAX_BYTES", 1024)
    monkeypatch.setattr(body_limit, "UPLOAD_MAX_BYTES", 4096)
    app = create_app()

    @app.post("/api/_json", include_in_schema=False)
    async def json_route(body: dict) -> dict:
        ran.append("json")
        return {"keys": len(body)}

    @app.post("/api/_upload", include_in_schema=False)
    async def upload_route(file: UploadFile = File(...)) -> dict:
        ran.append("upload")
        return {"size": len(await file.read())}

    @app.post("/api/_stream", include_in_schema=False)
    async def stream_route(request: Request) -> dict:
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
        ran.append("stream")
        return {"size": size}

    ran.clear()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def payload(n: int) -> bytes:
    """A JSON object of exactly `n` bytes."""
    return b'{"k":"' + b"x" * (n - 8) + b'"}'


def chunks(data: bytes, size: int = 256):
    for i in range(0, len(data), size):
        yield data[i:i + size]


def test_a_body_within_the_limit_is_untouched(client) -> None:
    r = client.post("/api/_json", content=payload(1024),
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 200, r.text
    assert ran == ["json"]


def test_a_declared_length_over_the_limit_is_refused_unread(client) -> None:
    r = client.post("/api/_json", content=payload(1025),
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 413, r.text
    assert r.json()["detail"] == "a request body here is at most 1024 bytes"
    assert ran == [], "the route ran for a body it should never have seen"
    # Still a request the logs and metrics know about.
    assert r.headers.get("x-request-id")


def test_a_chunked_body_is_counted_as_it_arrives(client) -> None:
    """No Content-Length to go by: refused once the count passes the limit,
    as a 413 rather than FastAPI's "error parsing the body"."""
    r = client.post("/api/_json", content=chunks(payload(4000)),
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 413, r.text
    assert ran == []
    small = client.post("/api/_json", content=chunks(payload(900)),
                        headers={"Content-Type": "application/json"})
    assert small.status_code == 200, small.text


def test_a_route_reading_the_stream_itself_is_bounded_too(client) -> None:
    r = client.post("/api/_stream", content=chunks(b"x" * 3000),
                    headers={"Content-Type": "application/octet-stream"})
    assert r.status_code == 413, r.text
    assert ran == []


def test_an_upload_gets_the_upload_limit(client) -> None:
    """Past the limit for other bodies and within the one for files, a file
    is accepted; past that, refused."""
    ok = client.post("/api/_upload", files={"file": ("a.csv", b"x" * 2000)})
    assert ok.status_code == 200, ok.text
    assert ok.json() == {"size": 2000}
    big = client.post("/api/_upload", files={"file": ("a.csv", b"x" * 5000)})
    assert big.status_code == 413, big.text
    assert ran == ["upload"]


def test_a_declared_upload_is_not_an_upload_by_its_length_alone() -> None:
    """The limit follows the declared kind, parameters and case aside."""
    assert body_limit.limit_for({b"content-type": b"Multipart/Form-Data; boundary=x"}) == (
        body_limit.UPLOAD_MAX_BYTES)
    assert body_limit.limit_for({b"content-type": b"application/json"}) == (
        body_limit.BODY_MAX_BYTES)
    assert body_limit.limit_for({}) == body_limit.BODY_MAX_BYTES


def test_the_real_limits_leave_room_for_what_the_api_accepts() -> None:
    """The dataset cap is the largest file a route takes, and the test-run
    working set the largest JSON; both must fit under what is enforced first."""
    from src.services import code_test_runs, datasets

    assert body_limit.UPLOAD_MAX_BYTES > datasets.MAX_UPLOAD_BYTES
    assert body_limit.BODY_MAX_BYTES > code_test_runs.MAX_FILES_BYTES


# ---- the middleware on its own, under a bare ASGI app -------------------------
def run_asgi(app, headers: list[tuple[bytes, bytes]], parts: list[bytes]) -> list[dict]:
    import asyncio

    sent: list[dict] = []
    queue = [{"type": "http.request", "body": p, "more_body": i < len(parts) - 1}
             for i, p in enumerate(parts)]

    async def receive():
        return queue.pop(0) if queue else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    asyncio.run(body_limit.BodyLimit(app)(
        {"type": "http", "method": "POST", "path": "/", "headers": headers}, receive, send))
    return sent


def test_a_declared_length_over_the_limit_never_reaches_the_app(monkeypatch) -> None:
    monkeypatch.setattr(body_limit, "BODY_MAX_BYTES", 10)
    called = []

    async def app(scope, receive, send):
        called.append(True)

    sent = run_asgi(app, [(b"content-length", b"11")], [b"x" * 11])
    assert called == []
    assert sent[0]["status"] == 413


def test_a_read_no_handler_answers_is_still_refused(monkeypatch) -> None:
    """An app with no exception handlers - the 413 raised from the read
    reaches the middleware, which answers it."""
    monkeypatch.setattr(body_limit, "BODY_MAX_BYTES", 10)

    async def app(scope, receive, send):
        while (await receive()).get("more_body"):
            pass
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    sent = run_asgi(app, [], [b"x" * 6, b"x" * 6])
    assert sent[0]["status"] == 413
    assert b"at most 10 bytes" in sent[1]["body"]
    ok = run_asgi(app, [], [b"x" * 5, b"x" * 5])
    assert ok[0]["status"] == 200


def test_a_response_already_begun_is_not_begun_twice(monkeypatch) -> None:
    """An app that answers before reading its whole body cannot be given a 413
    as well - a second response start breaks the protocol - so the refusal
    propagates instead, and the server ends the connection."""
    monkeypatch.setattr(body_limit, "BODY_MAX_BYTES", 10)

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        while (await receive()).get("more_body"):
            pass

    sent: list[dict] = []
    with pytest.raises(body_limit.BodyTooLarge):
        import asyncio

        queue = [{"type": "http.request", "body": b"x" * 6, "more_body": True},
                 {"type": "http.request", "body": b"x" * 6, "more_body": False}]

        async def receive():
            return queue.pop(0)

        async def send(message):
            sent.append(message)

        asyncio.run(body_limit.BodyLimit(app)(
            {"type": "http", "method": "POST", "path": "/", "headers": []}, receive, send))
    assert [m["type"] for m in sent] == ["http.response.start"]
