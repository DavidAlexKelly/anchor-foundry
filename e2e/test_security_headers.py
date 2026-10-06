"""Pages and the API both say not to sniff them, not to frame them
elsewhere, and how much of a referrer to send (§836)."""
from __future__ import annotations

import urllib.request

from conftest import WEB_BASE

EXPECTED = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "SAMEORIGIN",
    "referrer-policy": "strict-origin-when-cross-origin",
}


def headers_of(url: str) -> dict[str, list[str]]:
    with urllib.request.urlopen(url, timeout=60) as response:
        got: dict[str, list[str]] = {}
        for name, value in response.headers.items():
            got.setdefault(name.lower(), []).append(value)
        return got


def test_a_page_carries_them() -> None:
    got = headers_of(f"{WEB_BASE}/")
    assert {k: got.get(k) for k in EXPECTED} == {k: [v] for k, v in EXPECTED.items()}


def test_an_api_answer_through_the_web_origin_carries_each_once() -> None:
    """The API's own, passed through the dev proxy - once each, not once from
    the API and again from the web app."""
    got = headers_of(f"{WEB_BASE}/api/health")
    assert {k: got.get(k) for k in EXPECTED} == {k: [v] for k, v in EXPECTED.items()}
