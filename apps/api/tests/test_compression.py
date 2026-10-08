"""§919: the API compresses what it answers.

CloudFront compresses only what its cache policy may cache, and the API's
behaviour caches nothing, so before this every response crossed the internet
as plain JSON. These run against `create_app()`'s own middleware, through
routes added for the purpose, so what is checked is the configuration a
deployment runs.
"""
from __future__ import annotations

import os
import sys

from fastapi.responses import JSONResponse, Response
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.main import create_app  # noqa: E402

ROWS = [{"id": n, "name": f"row {n}", "status": "succeeded"} for n in range(200)]


def _client() -> TestClient:
    app = create_app()

    @app.get("/api/__test/big")
    async def big() -> JSONResponse:
        return JSONResponse({"rows": ROWS})

    @app.get("/api/__test/small")
    async def small() -> JSONResponse:
        return JSONResponse({"ok": True})

    @app.get("/api/__test/parquet")
    async def parquet() -> Response:
        return Response(b"PAR1" + b"\0" * 4096, media_type="application/vnd.apache.parquet")

    return TestClient(app)


def test_a_large_answer_is_gzipped_and_reads_the_same() -> None:
    r = _client().get("/api/__test/big", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"
    assert "accept-encoding" in r.headers.get("vary", "").lower(), "a cache must key on it"
    assert r.json() == {"rows": ROWS}
    assert int(r.headers["content-length"]) < len(r.content) / 4


def test_a_small_answer_is_left_alone() -> None:
    r = _client().get("/api/__test/small", headers={"Accept-Encoding": "gzip"})
    assert "content-encoding" not in r.headers


def test_a_client_that_did_not_ask_gets_it_plain() -> None:
    r = _client().get("/api/__test/big", headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in r.headers
    assert r.json() == {"rows": ROWS}


def test_parquet_is_not_compressed_twice() -> None:
    r = _client().get("/api/__test/parquet", headers={"Accept-Encoding": "gzip"})
    assert "content-encoding" not in r.headers


def test_security_headers_survive_compression() -> None:
    r = _client().get("/api/__test/big", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("x-content-type-options") == "nosniff"
