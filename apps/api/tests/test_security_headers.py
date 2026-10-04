"""Every API response says not to sniff it, not to frame it elsewhere, and
how much of a referrer to send (§836)."""
from __future__ import annotations

import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.lib import body_limit, security_headers  # noqa: E402
from src.main import create_app  # noqa: E402

EXPECTED = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "SAMEORIGIN",
    "referrer-policy": "strict-origin-when-cross-origin",
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(body_limit, "BODY_MAX_BYTES", 16)
    app = create_app()

    @app.get("/api/_plain", include_in_schema=False)
    async def plain() -> dict:
        return {"ok": True}

    @app.get("/api/_own", include_in_schema=False)
    async def own():
        from starlette.responses import JSONResponse
        return JSONResponse({}, headers={"X-Frame-Options": "DENY"})

    @app.post("/api/_body", include_in_schema=False)
    async def body(payload: dict) -> dict:
        return payload

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def carries(response) -> dict:
    return {k: response.headers.get(k) for k in EXPECTED}


def test_an_answer_carries_them(client) -> None:
    assert carries(client.get("/api/_plain")) == EXPECTED


def test_so_does_a_refusal_from_anywhere(client) -> None:
    """A route nobody matched, and a body refused before any route ran."""
    assert carries(client.get("/api/nowhere")) == EXPECTED
    big = client.post("/api/_body", content=b'{"k": "' + b"x" * 40 + b'"}',
                      headers={"Content-Type": "application/json"})
    assert big.status_code == 413
    assert carries(big) == EXPECTED


def test_a_header_a_route_set_is_its_own(client) -> None:
    r = client.get("/api/_own")
    assert r.headers.get_list("x-frame-options") == ["DENY"]
    assert r.headers["x-content-type-options"] == "nosniff"


def test_the_set_is_what_the_module_says() -> None:
    assert {n.decode(): v.decode() for n, v in security_headers.HEADERS} == EXPECTED
