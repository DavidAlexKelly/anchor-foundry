"""The API's connections to its database notice when it has gone (§958).

Unset, a database that did not answer the connect held the request until
the kernel gave up, and a pooled connection whose host vanished - a failover
- waited on TCP retransmission, a quarter of an hour by default, for the
pool's own pre-ping as much as for a query. These are libpq's settings and
never reach the server.
"""
from __future__ import annotations

import asyncio
import os
import socket
import sys
import threading
import time
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.lib import config, db  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore")


def _fresh() -> None:
    config.get_settings.cache_clear()
    if db._engine is not None:
        asyncio.run(db.dispose_engine())
    db._engine = None


def test_every_pooled_connection_carries_the_settings() -> None:
    _fresh()

    async def read() -> dict:
        try:
            async with db.user_connection(uuid.uuid4()) as conn:
                raw = await conn.get_raw_connection()
                return raw.driver_connection.info.get_parameters()
        finally:
            await db.dispose_engine()

    got = asyncio.run(read())
    assert {k: got.get(k) for k in ("connect_timeout", "keepalives", "keepalives_idle",
                                    "tcp_user_timeout")} == {
        "connect_timeout": "10", "keepalives": "1", "keepalives_idle": "30",
        "tcp_user_timeout": "30000"}


@pytest.fixture
def silent_database(monkeypatch):
    """A database that takes the connection and never says a word."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    held: list[socket.socket] = []
    stop = threading.Event()

    def accept() -> None:
        server.settimeout(0.2)
        while not stop.is_set():
            try:
                held.append(server.accept()[0])
            except OSError:
                continue

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:y@127.0.0.1:"
                       f"{server.getsockname()[1]}/z?sslmode=disable")
    monkeypatch.setitem(db.CONNECTION_SETTINGS, "connect_timeout", 1)
    _fresh()
    yield
    stop.set()
    thread.join(2)
    for s in held:
        s.close()
    server.close()
    monkeypatch.undo()
    _fresh()


def test_a_database_that_does_not_answer_is_a_prompt_503(silent_database) -> None:
    from src.main import create_app

    app = create_app()

    @app.get("/api/_reads", include_in_schema=False)
    async def reads() -> dict:
        async with db.user_connection(uuid.uuid4()):
            return {}

    with TestClient(app, raise_server_exceptions=False) as client:
        started = time.monotonic()
        r = client.get("/api/_reads")
    assert r.status_code == 503, r.text
    assert time.monotonic() - started < 5


def test_a_request_waits_seconds_for_a_pooled_connection_not_half_a_minute() -> None:
    """§984: with every pooled connection taken, the wait is ten seconds, not
    SQLAlchemy's thirty - half of CloudFront's minute before any work."""
    from src.lib import db

    engine = db.get_engine()
    assert engine.sync_engine.pool.timeout() == db.POOL_WAIT_S == 10
