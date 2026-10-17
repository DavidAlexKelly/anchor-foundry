"""Verifying a token does not hold up the rest of the task (§953).

PyJWKClient refreshes Cognito's keys with a blocking fetch of up to 30
seconds, hourly and on a key id it has not seen. Verification ran on the
event loop, so that fetch stopped every request on the task, health checks
included. It runs on its own threads now.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.lib.db import dispose_engine  # noqa: E402
from src.lib.errors import UnauthorizedError  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore")


class FetchingKeys:
    """A verifier caught refreshing its keys from a slow Cognito."""

    def verify(self, token: str) -> dict:
        time.sleep(1.0)
        raise UnauthorizedError("invalid token: PyJWKClientConnectionError")


def test_a_slow_key_fetch_does_not_stop_other_requests(monkeypatch) -> None:
    monkeypatch.setattr(auth_mw, "_verifier", FetchingKeys())
    auth_mw.clear_identity_cache()

    async def scenario() -> tuple[int, float, int]:
        app = create_app()
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://api") as client:
                started = time.monotonic()
                login = asyncio.create_task(
                    client.get("/api/auth/me", headers={"Authorization": "Bearer t"}))
                await asyncio.sleep(0.1)
                health = await client.get("/api/health")
                answered = time.monotonic() - started
                return health.status_code, answered, (await login).status_code
        finally:
            await dispose_engine()

    health, answered, login = asyncio.run(scenario())
    assert health == 200
    assert answered < 0.8, f"health waited {answered:.2f} s behind the key fetch"
    assert login == 401
