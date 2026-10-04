"""One SQL statement may run for so long, and no longer (§833).

CloudFront gives up on the API after 30 seconds, so a request whose query runs
past that has no one waiting for it - but the query ran on, holding a pooled
connection, and enough of them at once stalled every request on the task.
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.lib import config, db  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore")


def fresh_engine() -> None:
    """Settings and the engine are built once per process; start both again."""
    config.get_settings.cache_clear()
    if db._engine is not None:
        asyncio.run(db.dispose_engine())
    db._engine = None


@pytest.fixture
def short_timeout(monkeypatch):
    monkeypatch.setenv("STATEMENT_TIMEOUT_MS", "300")
    fresh_engine()
    yield
    monkeypatch.delenv("STATEMENT_TIMEOUT_MS")
    fresh_engine()


def test_the_limit_is_a_connection_option() -> None:
    assert db.connect_args(0) == {}
    assert db.connect_args(-1) == {}
    assert db.connect_args(30_000) == {"options": "-c statement_timeout=30000"}


def test_the_default_is_cloudfronts_thirty_seconds(monkeypatch) -> None:
    monkeypatch.delenv("STATEMENT_TIMEOUT_MS", raising=False)
    assert config.Settings(database_url="postgresql://x/y").statement_timeout_ms == 30_000


def test_every_pooled_connection_has_it(short_timeout) -> None:
    async def shown() -> str:
        async with db.user_connection(__import__("uuid").uuid4()) as conn:
            return (await conn.execute(text("SHOW statement_timeout"))).scalar_one()

    async def both() -> list[str]:
        try:
            return [await shown(), await shown()]
        finally:
            await db.dispose_engine()

    assert asyncio.run(both()) == ["300ms", "300ms"]


def test_a_statement_past_it_is_a_503_that_says_so(short_timeout) -> None:
    from src.main import create_app

    app = create_app()

    @app.get("/api/_slow", include_in_schema=False)
    async def slow() -> dict:
        async with db.user_connection(__import__("uuid").uuid4()) as conn:
            await conn.execute(text("SELECT pg_sleep(2)"))
        return {}

    @app.get("/api/_quick", include_in_schema=False)
    async def quick() -> dict:
        async with db.user_connection(__import__("uuid").uuid4()) as conn:
            await conn.execute(text("SELECT pg_sleep(0.05)"))
        return {"ok": True}

    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/api/_slow")
        assert r.status_code == 503, r.text
        assert "stopped this request after 0.3 seconds" in r.json()["detail"]
        # The connection went back to the pool usable.
        assert client.get("/api/_quick").json() == {"ok": True}


@pytest.mark.parametrize("module", ["instance_cutover", "restore_check"])
def test_the_operator_commands_run_without_it(module, monkeypatch) -> None:
    """A cutover or a restore check reads a whole deployment; a request limit
    would stop it partway. Each turns the limit off unless told otherwise."""
    import importlib

    cli = importlib.import_module(f"src.services.{module}")
    monkeypatch.delenv("STATEMENT_TIMEOUT_MS", raising=False)
    seen = {}

    class Stop(Exception):
        pass

    def no_engine():
        seen["limit"] = os.environ.get("STATEMENT_TIMEOUT_MS")
        raise Stop

    monkeypatch.setattr(db, "get_engine", no_engine)

    class Gateway:
        async def close(self) -> None:
            pass

    monkeypatch.setattr(cli.instance_store, "gateway_from_env", lambda: Gateway())
    if module == "restore_check":
        monkeypatch.setattr(cli.instance_store, "configure_instance_store", lambda g: None)
        monkeypatch.setattr(cli, "_storage_from_env", lambda: None)
    try:
        with pytest.raises(Stop):
            asyncio.run(cli._main([]))
    finally:
        os.environ.pop("STATEMENT_TIMEOUT_MS", None)
    assert seen["limit"] == "0"
