"""The health check is not held up by the requests it keeps alive (§956).

The load balancer replaces a task that fails its check twice. The check went
through the request pool, so a task whose every pooled connection was busy -
load, not a fault - waited past the check's five seconds, was replaced, and
pushed its requests onto tasks just as busy.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.lib import config, db  # noqa: E402
from src.main import create_app  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore")


def _run(scenario):
    async def wrapped():
        try:
            return await scenario()
        finally:
            await db.dispose_engine()
    return asyncio.run(wrapped())


def test_a_pool_with_nothing_free_is_still_healthy(monkeypatch) -> None:
    async def scenario():
        # A pool of one, held by a request that is taking its time.
        db._engine = create_async_engine(config.get_settings().database_url,
                                         pool_size=1, max_overflow=0, pool_timeout=2)
        held = await db._engine.connect()
        try:
            await held.execute(text("SELECT 1"))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()),
                                         base_url="http://api") as client:
                started = time.monotonic()
                r = await client.get("/api/health")
                return r.status_code, time.monotonic() - started
        finally:
            await held.close()

    status, took = _run(scenario)
    assert status == 200
    assert took < 1.5, f"health waited {took:.2f} s for the pool"


def test_a_database_that_does_not_answer_is_a_503_in_time(monkeypatch) -> None:
    """Inside the load balancer's five seconds, and said, not timed out."""
    monkeypatch.setattr(db, "HEALTH_DEADLINE_S", 1)
    import src.main as main_module
    monkeypatch.setattr(main_module, "HEALTH_DEADLINE_S", 1)

    async def scenario():
        # A database that takes the connection and then says nothing back.
        held: list = []

        async def say_nothing(reader, writer):
            held.append(writer)  # kept open, and never written to
            await asyncio.sleep(30)

        server = await asyncio.start_server(say_nothing, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        db._health_engine = create_async_engine(
            f"postgresql+psycopg://x:y@127.0.0.1:{port}/z?sslmode=disable",
            connect_args={"connect_timeout": 10})
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()),
                                         base_url="http://api") as client:
                started = time.monotonic()
                r = await client.get("/api/health")
                return r.status_code, time.monotonic() - started
        finally:
            for writer in held:
                writer.close()
            server.close()

    status, took = _run(scenario)
    assert status == 503
    assert took < 3


def test_a_healthy_task_says_so() -> None:
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()),
                                     base_url="http://api") as client:
            r = await client.get("/api/health")
            return r.status_code, r.json()
    assert _run(scenario) == (200, {"status": "ok"})
