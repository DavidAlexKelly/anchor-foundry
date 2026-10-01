"""Diagnose a connection (§646; `data-connection` TOC §6, *Where to start*).

> "1. Confirm the source is reachable … run dig, curl, and openssl s_client …
> 2. Check egress configuration … 3. Check credentials … 4. Check
> certificates." (TOC §6)

The list, run in order against the destination the connection names, and
stopped at the first step that fails. The unit half stands in for the network
so each failure can be made on demand; the API half runs it against the local
Postgres acting as the customer's source (`test_connections`).
"""
from __future__ import annotations

import os
import socket
import ssl
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import hdr  # noqa: E402
from test_connections import (  # noqa: E402,F401
    SOURCE_PASSWORD, _fresh_identity_cache, base, client, fx, gateway, source_database,
)
from src.services import diagnose, egress  # noqa: E402

PG = {"host": "db.example.com", "port": 5432, "database": "d", "user": "u"}


def statuses(steps) -> list[tuple[str, str]]:
    return [(s.name, s.status) for s in steps]


@pytest.fixture
def network(monkeypatch):
    """A network that answers, unless a test says otherwise, and records what
    was asked of it."""
    asked: list[str] = []

    def resolve(host, port):
        asked.append(f"dns {host}")
        return ["192.0.2.7"]

    def reach(host, port):
        asked.append(f"tcp {host}:{port}")

    def handshake(host, port):
        asked.append(f"tls {host}:{port}")
        return "TLSv1.3, TLS_AES_256_GCM_SHA384"

    monkeypatch.setattr(diagnose, "resolve", resolve)
    monkeypatch.setattr(diagnose, "reach", reach)
    monkeypatch.setattr(diagnose, "handshake", handshake)
    return asked


def ok() -> None:
    return None


# ---- where a connection connects ---------------------------------------------------
def test_each_connector_names_its_destination() -> None:
    d = diagnose.destination
    assert d("postgres", PG) == diagnose.Destination("db.example.com", 5432, "in_protocol")
    assert d("postgres", {**PG, "sslmode": "disable"}).tls == "none"
    assert d("postgres", {"host": "h", "database": "d", "user": "u"}).port == 5432
    assert d("mysql", {"host": "m", "database": "d", "user": "u"}) == \
        diagnose.Destination("m", 3306, "in_protocol")
    assert d("mysql", {"host": "m", "ssl_mode": "disabled"}).tls == "none"
    assert d("rest", {"base_url": "https://api.example.com/v1"}) == \
        diagnose.Destination("api.example.com", 443, "direct")
    assert d("rest", {"base_url": "http://api.example.com:8080"}) == \
        diagnose.Destination("api.example.com", 8080, "none")
    assert d("s3", {"bucket": "b", "endpoint_url": "https://minio.internal:9000"}) == \
        diagnose.Destination("minio.internal", 9000, "direct")
    assert d("s3", {"bucket": "b", "region": "eu-west-2"}) == \
        diagnose.Destination("s3.eu-west-2.amazonaws.com", 443, "direct", scoped=False)
    assert d("postgres", {"host": ""}) is None
    assert d("rest", {"base_url": "ftp://x"}) is None
    assert d("rest", {"base_url": ""}) is None
    assert d("carrier-pigeon", {"host": "x"}) is None


# ---- TOC §6's order ------------------------------------------------------------------
def test_a_reachable_database_passes_every_step(network) -> None:
    steps = diagnose.run("postgres", PG, [], ok)
    assert statuses(steps) == [("destination", "ok"), ("egress", "ok"), ("dns", "ok"),
                               ("tcp", "ok"), ("tls", "info"), ("credentials", "ok")]
    assert steps[1].detail == "no policies: unrestricted"
    assert "inside the database protocol" in steps[4].detail
    assert network == ["dns db.example.com", "tcp db.example.com:5432"]


def test_an_https_source_is_shaken_hands_with(network) -> None:
    steps = diagnose.run("rest", {"base_url": "https://api.example.com"}, [], ok)
    assert steps[4] == diagnose.Step("tls", "ok", "TLSv1.3, TLS_AES_256_GCM_SHA384")
    assert "tls api.example.com:443" in network


def test_plaintext_is_said_to_be_plaintext(network) -> None:
    steps = diagnose.run("rest", {"base_url": "http://api.example.com"}, [], ok)
    assert steps[4].status == "info" and "plaintext" in steps[4].detail
    assert not any(a.startswith("tls") for a in network)


def test_a_host_that_does_not_resolve_stops_the_list(network, monkeypatch) -> None:
    def nowhere(host, port):
        raise socket.gaierror(-2, "Name or service not known")

    monkeypatch.setattr(diagnose, "resolve", nowhere)
    steps = diagnose.run("postgres", PG, [], ok)
    assert statuses(steps)[2:] == [("dns", "failed"), ("tcp", "skipped"), ("tls", "skipped"),
                                   ("credentials", "skipped")]
    assert "does not resolve" in steps[2].detail and "host name" in steps[2].hint
    assert steps[3].detail == "not tried: dns failed"
    assert network == []


def test_a_closed_port_stops_the_list(network, monkeypatch) -> None:
    def refused(host, port):
        raise ConnectionRefusedError(111, "Connection refused")

    monkeypatch.setattr(diagnose, "reach", refused)
    steps = diagnose.run("postgres", PG, [], ok)
    assert statuses(steps)[3:] == [("tcp", "failed"), ("tls", "skipped"), ("credentials", "skipped")]
    assert "db.example.com:5432" in steps[3].detail and "firewall" in steps[3].hint


def test_egress_is_checked_before_the_network_is_touched(network) -> None:
    """A destination the policies refuse is never probed: the refusal is the
    answer, and a probe would be the egress the policy exists to stop."""
    policies = [{"host": "other.example.com", "port": 5432}]
    steps = diagnose.run("postgres", PG, policies, ok)
    assert statuses(steps)[1:] == [("egress", "failed"), ("dns", "skipped"), ("tcp", "skipped"),
                                   ("tls", "skipped"), ("credentials", "skipped")]
    assert "db.example.com:5432" in steps[1].hint
    assert network == []
    allowed = diagnose.run("postgres", PG, [{"host": "db.example.com", "port": 5432}], ok)
    assert allowed[1] == diagnose.Step("egress", "ok", "allowed by the source's policies (1)")


def test_an_aws_bucket_is_not_scoped_and_says_so(network) -> None:
    steps = diagnose.run("s3", {"bucket": "b", "region": "eu-west-2"},
                         [{"host": "elsewhere", "port": 443}], ok)
    assert steps[1].status == "info" and "do not scope" in steps[1].detail
    assert steps[-1].status == "ok"


def test_an_untrusted_certificate_is_named(network, monkeypatch) -> None:
    def untrusted(host, port):
        error = ssl.SSLCertVerificationError(1, "certificate verify failed")
        error.verify_message = "self-signed certificate"
        raise error

    monkeypatch.setattr(diagnose, "handshake", untrusted)
    steps = diagnose.run("rest", {"base_url": "https://api.example.com"}, [], ok)
    assert steps[4].status == "failed"
    assert "self-signed certificate" in steps[4].detail and "private authority" in steps[4].hint
    assert steps[5].status == "skipped"


def test_a_failed_handshake_points_at_the_openssl_check(network, monkeypatch) -> None:
    def refused(host, port):
        raise ssl.SSLError(1, "unsupported protocol")

    monkeypatch.setattr(diagnose, "handshake", refused)
    steps = diagnose.run("rest", {"base_url": "https://api.example.com"}, [], ok)
    assert steps[4].status == "failed" and "openssl s_client" in steps[4].hint


def test_credentials_that_fail_say_how(network) -> None:
    def bad() -> None:
        raise RuntimeError("password authentication failed for user \"u\"")

    def gone() -> None:
        raise KeyError("password")

    def second_host() -> None:
        raise egress.EgressRefused("token.example.com:443 is not allowed")

    assert diagnose.run("postgres", PG, [], bad)[5] == diagnose.Step(
        "credentials", "failed", "password authentication failed for user \"u\"",
        "Re-enter the credentials if they may be stale, and check the account may read "
        "what the connection names.")
    assert "missing" in diagnose.run("postgres", PG, [], gone)[5].detail
    assert "another host" in diagnose.run("postgres", PG, [], second_host)[5].hint


def test_a_connection_with_no_host_fails_first(network) -> None:
    steps = diagnose.run("postgres", {"host": ""}, [], ok)
    assert statuses(steps) == [("destination", "failed")] + [
        (name, "skipped") for name in diagnose.STEPS[1:]]


# ---- through the API, against a real source ----------------------------------------
def make(client: TestClient, fx, config: dict, password: str = SOURCE_PASSWORD) -> str:
    r = client.post(base(fx), headers=hdr(fx.editor_sub), json={
        "name": f"Diag {len(config)} {id(config)}", "source_type": "postgres",
        "config": config, "secret": {"password": password}})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def run(client: TestClient, fx, cid: str, who: str | None = None):
    return client.post(f"{base(fx)}/{cid}/diagnose", headers=hdr(who or fx.editor_sub))


def test_the_local_source_passes(client: TestClient, fx, source_database) -> None:
    r = run(client, fx, make(client, fx, source_database))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert [s["status"] for s in body["steps"]] == ["ok", "ok", "ok", "ok", "info", "ok"]
    assert SOURCE_PASSWORD not in r.text


def test_a_wrong_password_fails_at_credentials(client: TestClient, fx, source_database) -> None:
    body = run(client, fx, make(client, fx, source_database, "wrong")).json()
    assert body["ok"] is False
    assert body["steps"][5]["status"] == "failed" and body["steps"][4]["status"] == "info"


def test_a_closed_port_fails_at_tcp(client: TestClient, fx, source_database) -> None:
    body = run(client, fx, make(client, fx, {**source_database, "port": 1})).json()
    assert [s["status"] for s in body["steps"]][2:4] == ["ok", "failed"]


def test_a_name_that_does_not_resolve_fails_at_dns(client: TestClient, fx, source_database) -> None:
    body = run(client, fx, make(client, fx, {**source_database, "host": "nowhere.invalid"})).json()
    assert body["steps"][2]["status"] == "failed"


def test_diagnosing_needs_the_role_that_could_test(client: TestClient, fx, source_database) -> None:
    cid = make(client, fx, source_database)
    assert run(client, fx, cid, fx.viewer_sub).status_code == 403
    assert run(client, fx, cid, fx.outsider_sub).status_code == 404
