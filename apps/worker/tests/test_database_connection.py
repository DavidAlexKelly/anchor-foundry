"""The worker's connection to the platform database notices when it has
gone (§958), rather than waiting on the kernel."""
from __future__ import annotations

import os
import socket
import sys
import threading
import time

import psycopg
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from anchor_worker import resources  # noqa: E402

APP_DSN = os.environ["WORKER_DATABASE_URL"]


def test_every_connection_carries_the_settings() -> None:
    db = resources.PlatformDatabase(dsn=APP_DSN)
    for connect in (db.connect, lambda: db.connect_scoped_to(__import__("uuid").uuid4())):
        with connect() as conn:
            got = conn.info.get_parameters()
            assert {k: got.get(k) for k in ("connect_timeout", "keepalives_idle",
                                            "tcp_user_timeout")} == {
                "connect_timeout": "10", "keepalives_idle": "30", "tcp_user_timeout": "30000"}


@pytest.fixture
def silent_database():
    """Takes the connection, then never says a word."""
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
    yield f"postgresql://x:y@127.0.0.1:{server.getsockname()[1]}/z?sslmode=disable"
    stop.set()
    thread.join(2)
    for s in held:
        s.close()
    server.close()


def test_a_database_that_does_not_answer_is_given_up_on(silent_database, monkeypatch) -> None:
    monkeypatch.setitem(resources.CONNECTION_SETTINGS, "connect_timeout", 1)
    started = time.monotonic()
    with pytest.raises(psycopg.OperationalError):
        with resources.PlatformDatabase(dsn=silent_database).connect():
            pass
    assert time.monotonic() - started < 5
