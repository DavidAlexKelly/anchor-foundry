"""The audit log records who sent a request, not the load balancer (§955).

Every audited action stored `request.client.host`, which behind CloudFront
and the load balancer is the load balancer's private address: the same for
every entry, and nothing to do with whoever acted. It records the address
the proxies vouch for now - the X-Forwarded-For entry `LISTENER_PROXY_HOPS`
from the right, as a listener's allowlist already read it (§850).
"""
from __future__ import annotations

import os
import sys
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.lib.proxy import client_address  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402

ADMIN_DSN = os.environ["TEST_ADMIN_DSN"]


def _request(peer: str, forwarded: str | None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers,
                    "client": (peer, 1234), "query_string": b""})


@pytest.mark.parametrize("hops, forwarded, expected", [
    (None, "203.0.113.9", "10.0.1.5"),           # development: the peer itself
    ("1", "198.51.100.7, 203.0.113.9", "203.0.113.9"),   # public: the edge CloudFront used
    ("2", "1.2.3.4, 198.51.100.7, 10.0.2.8", "198.51.100.7"),  # VPC origin: the viewer
    ("1", None, None),                           # nobody vouched for an address
])
def test_the_address_is_the_one_the_proxies_vouch_for(monkeypatch, hops, forwarded, expected):
    if hops is None:
        monkeypatch.delenv("LISTENER_PROXY_HOPS", raising=False)
    else:
        monkeypatch.setenv("LISTENER_PROXY_HOPS", hops)
    assert client_address(_request("10.0.1.5", forwarded)) == expected


def test_a_sender_cannot_choose_the_address_recorded(monkeypatch) -> None:
    """Whatever it puts in the header, only the entry the proxy wrote counts."""
    monkeypatch.setenv("LISTENER_PROXY_HOPS", "1")
    assert client_address(_request("10.0.1.5", "6.6.6.6, 6.6.6.7, 203.0.113.9")) == "203.0.113.9"


def test_an_audited_action_records_the_sender(monkeypatch) -> None:
    monkeypatch.setenv("LISTENER_PROXY_HOPS", "1")
    auth_mw.configure_verifier(LocalVerifier())
    auth_mw.clear_identity_cache()
    fx = Fixture()
    name = f"Audited {uuid.uuid4().hex[:6]}"
    with TestClient(create_app()) as client:
        r = client.post(f"/api/workspaces/{fx.workspace}/projects",
                        headers={**hdr(fx.admin_sub), "X-Forwarded-For": "6.6.6.6, 203.0.113.9"},
                        json={"name": name})
    assert r.status_code == 201, r.text
    with psycopg.connect(ADMIN_DSN) as conn:
        recorded = conn.execute(
            "SELECT host(ip_address) FROM audit_log WHERE action = 'project.create'"
            " AND resource_id = %s", (r.json()["id"],)).fetchone()[0]
    assert recorded == "203.0.113.9"


def test_nothing_else_reads_the_peer_address() -> None:
    """A route added later reaches for `request.client.host` the way the old
    ones did; it would record the load balancer again."""
    import pathlib

    src = pathlib.Path(__file__).resolve().parent.parent / "src"
    found = [f"{p.relative_to(src)}:{n}" for p in sorted(src.rglob("*.py")) if p.name != "proxy.py"
             for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
             if "request.client" in line]
    assert not found, "use lib.proxy.client_address(request):\n  " + "\n  ".join(found)
