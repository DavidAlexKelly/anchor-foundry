"""The platform's own AWS calls wait seconds, not minutes (§970): the
worker's copy of the API's test, for the clients the worker makes."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

pytest.importorskip("boto3")

from anchor_worker import transform_dispatch  # noqa: E402
from anchor_worker.storage import S3StorageGateway  # noqa: E402


@pytest.fixture(autouse=True)
def _credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-2")


def limits_of(client) -> tuple:
    c = client.meta.config
    return c.connect_timeout, c.read_timeout, c.retries["mode"], c.retries["total_max_attempts"]


def test_each_platform_client_carries_its_limits() -> None:
    assert limits_of(transform_dispatch._ecs_client()) == (3, 5, "standard", 3)
    assert limits_of(S3StorageGateway("data", "eu-west-2")._client) == (3, 30, "standard", 3)


def test_nothing_makes_an_aws_client_any_other_way() -> None:
    """The source connectors are the customer's buckets and set their own."""
    makers = {
        str(path.relative_to(SRC / "anchor_worker"))
        for path in SRC.rglob("*.py")
        if re.search(r"\bboto3\.client\(", path.read_text())
    }
    assert makers == {"aws.py", "connectors.py"}
