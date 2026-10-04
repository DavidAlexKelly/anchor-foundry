"""A scheduled S3 sync's custom endpoint is held as the API's is (§880).

The worker built its S3 client from the stored endpoint with neither the
source's egress policy nor the metadata refusal, so a name that resolved
publicly when the source was saved could point a nightly sync at the task's
metadata address.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from anchor_worker import egress  # noqa: E402
from anchor_worker.connectors import ConnectorError, S3Connector  # noqa: E402

CONFIG = {"bucket": "b", "region": "eu-west-2"}


def test_a_metadata_endpoint_is_refused() -> None:
    with pytest.raises(ConnectorError, match="link-local"):
        S3Connector()._client({**CONFIG, "endpoint_url": "http://169.254.170.2"}, {})


def test_the_endpoint_is_asked_of_the_egress_policy(monkeypatch) -> None:
    asked: list[tuple[str, int | None]] = []

    def policy(host: str, port: int | None) -> None:
        asked.append((host, port))
        raise egress.EgressRefused(f"{host} is not allowed")

    monkeypatch.setattr(egress, "check_current", policy)
    with pytest.raises(egress.EgressRefused):
        S3Connector()._client({**CONFIG, "endpoint_url": "https://store.example.com:9000"}, {})
    assert asked == [("store.example.com", 9000)]


def test_an_ordinary_endpoint_builds_a_client() -> None:
    client = S3Connector()._client({**CONFIG, "endpoint_url": "http://127.0.0.1:9000"}, {})
    assert client.meta.endpoint_url == "http://127.0.0.1:9000"
