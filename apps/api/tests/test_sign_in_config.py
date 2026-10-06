"""Where the sign-in page sends a person, told at run time (§851).

One web image serves every customer's stack, so the hosted UI's address and
the app client cannot be written into it when it is built. The API is given
both by the stack and hands them to the page.
"""
from __future__ import annotations

import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.lib import config  # noqa: E402
from src.main import create_app  # noqa: E402


@pytest.fixture
def ask(monkeypatch):
    def ask(**env: str) -> tuple[int, dict]:
        for name in ("COGNITO_DOMAIN", "COGNITO_CLIENT_ID"):
            monkeypatch.delenv(name, raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        config.get_settings.cache_clear()
        with TestClient(create_app()) as client:
            # No credential of any kind: the person asking has not signed in.
            r = client.get("/api/auth/config")
        return r.status_code, r.json()

    yield ask
    config.get_settings.cache_clear()


def test_a_stack_names_its_hosted_ui_to_anyone(ask) -> None:
    assert ask(COGNITO_DOMAIN="https://platform-acme.auth.eu-west-2.amazoncognito.com/",
               COGNITO_CLIENT_ID="abc123") == (200, {
        "domain": "https://platform-acme.auth.eu-west-2.amazoncognito.com",
        "client_id": "abc123",
    })


def test_half_a_configuration_is_none(ask) -> None:
    """A domain without a client, or the reverse, cannot start a sign-in, and
    the page should say there is no hosted UI rather than try."""
    nothing = (200, {"domain": None, "client_id": None})
    assert ask() == nothing
    assert ask(COGNITO_CLIENT_ID="abc123") == nothing
    assert ask(COGNITO_DOMAIN="https://x.auth.eu-west-2.amazoncognito.com") == nothing
