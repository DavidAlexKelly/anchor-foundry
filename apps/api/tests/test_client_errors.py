"""§926: a page that failed in a browser reaches the operators' logs, and the
deployed alarm counts it."""
from __future__ import annotations

import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from test_observability import deployed_filters, logged, matches  # noqa: E402,F401
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import client_errors  # noqa: E402

FAULT = {"kind": "fault", "message": "Cannot read properties of undefined (reading 'name')",
         "path": "/acme/p1/objects?token=SHOULD-NOT-BE-LOGGED#x", "digest": "1234567",
         "stack": "TypeError: Cannot read properties of undefined\n    at Page (page.js:1:1)"}


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client() -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh(monkeypatch) -> None:
    auth_mw.clear_identity_cache()
    monkeypatch.setattr(client_errors, "_recent", type(client_errors._recent)())


def _reported(logged_lines: list[dict]) -> list[dict]:
    return [line for line in logged_lines if line.get("logger") == "anchor.client_error"]


def test_a_failed_page_is_one_line_the_alarm_counts(client, fx, logged) -> None:
    r = client.post("/api/client-errors", json=FAULT, headers=hdr(fx.viewer_sub))
    assert r.status_code == 204, r.text
    [line] = _reported(logged)
    assert line["kind"] == "fault" and line["message"] == FAULT["message"]
    assert line["path"] == "/acme/p1/objects", "a query string can carry a token"
    assert "SHOULD-NOT-BE-LOGGED" not in str(line)
    assert line["digest"] == "1234567" and line["stack"].startswith("TypeError")
    assert line["user_id"]
    assert matches(deployed_filters()["WebPageErrors"][0], line)


def test_a_stale_page_is_logged_but_not_counted(client, fx, logged) -> None:
    r = client.post("/api/client-errors", json={**FAULT, "kind": "stale"}, headers=hdr(fx.viewer_sub))
    assert r.status_code == 204
    [line] = _reported(logged)
    assert not matches(deployed_filters()["WebPageErrors"][0], line)


def test_nobody_signed_out_can_write_to_the_log(client, logged) -> None:
    r = client.post("/api/client-errors", json=FAULT)
    assert r.status_code == 401
    assert _reported(logged) == []


@pytest.mark.parametrize("field,size", [("message", 501), ("path", 301), ("stack", 4001)])
def test_every_field_is_bounded(client, fx, logged, field: str, size: int) -> None:
    r = client.post("/api/client-errors", json={**FAULT, field: "x" * size},
                    headers=hdr(fx.viewer_sub))
    assert r.status_code == 422
    assert _reported(logged) == []


def test_a_flood_is_a_handful_of_lines(client, fx, logged, monkeypatch) -> None:
    monkeypatch.setattr(client_errors, "REPORTS_PER_MINUTE", 3)
    for _ in range(5):
        assert client.post("/api/client-errors", json=FAULT, headers=hdr(fx.viewer_sub)).status_code == 204
    assert len(_reported(logged)) == 3


def test_the_window_moves_on() -> None:
    client_errors._recent.clear()
    for second in range(client_errors.REPORTS_PER_MINUTE):
        assert client_errors._admit(1000.0 + second / 100)
    assert not client_errors._admit(1001.0)
    assert client_errors._admit(1000.0 + 60)
