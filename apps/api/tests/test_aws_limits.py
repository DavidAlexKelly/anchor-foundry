"""The platform's own AWS calls wait seconds, not minutes (§970).

boto3's defaults are a minute to connect, a minute a read and legacy
retries, so a stalled AWS endpoint held a request - and a thread every other
blocking call shares - for minutes. These hold that each of the platform's
clients is made with `lib/aws.py`'s limits, that nothing makes one any other
way, and that a call to an endpoint that never answers ends.
"""
from __future__ import annotations

import os
import re
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("boto3")
from botocore.exceptions import ConnectTimeoutError, ReadTimeoutError  # noqa: E402

from src.lib import aws  # noqa: E402
from src.services.orgs import Boto3CognitoGateway  # noqa: E402
from src.services.secrets import Boto3SecretsGateway  # noqa: E402
from src.services.storage import S3StorageGateway  # noqa: E402

SRC = Path(__file__).resolve().parent.parent / "src"


@pytest.fixture(autouse=True)
def _credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-2")


def limits_of(client) -> tuple:
    c = client.meta.config
    return c.connect_timeout, c.read_timeout, c.retries["mode"], c.retries["total_max_attempts"]


def test_each_platform_client_carries_its_limits() -> None:
    control = (3, 5, "standard", 3)
    assert limits_of(Boto3SecretsGateway("eu-west-2")._client) == control
    assert limits_of(Boto3CognitoGateway("pool", "eu-west-2")._client) == control
    # The bucket's reads may be of a large object, so each may take longer.
    assert limits_of(S3StorageGateway("data", "eu-west-2")._client) == (3, 30, "standard", 3)


def test_nothing_makes_an_aws_client_any_other_way() -> None:
    """The source connectors are the customer's buckets and set their own."""
    makers = {
        str(path.relative_to(SRC))
        for path in SRC.rglob("*.py")
        if re.search(r"\bboto3\.client\(", path.read_text())
    }
    assert makers == {"lib/aws.py", "services/connectors.py"}


def test_a_call_to_an_endpoint_that_never_answers_ends(monkeypatch: pytest.MonkeyPatch) -> None:
    """An endpoint that accepts and then says nothing: the shape of a stall.
    The read limit is made short so the test is; what is under test is that
    the gateway's calls are bound by it at all."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(8)
    held: list[socket.socket] = []
    stop = threading.Event()

    def accept() -> None:
        server.settimeout(0.2)
        while not stop.is_set():
            try:
                held.append(server.accept()[0])
            except OSError:
                continue

    threading.Thread(target=accept, daemon=True).start()
    monkeypatch.setitem(aws.CONTROL, "read_timeout", 1)
    monkeypatch.setenv("AWS_ENDPOINT_URL", f"http://127.0.0.1:{server.getsockname()[1]}")
    try:
        gateway = Boto3SecretsGateway("eu-west-2")
        started = time.monotonic()
        with pytest.raises((ReadTimeoutError, ConnectTimeoutError)):
            gateway.get_secret("arn:aws:secretsmanager:eu-west-2:1:secret:x")
        # Three tries of a second each, and the backoff between them.
        assert time.monotonic() - started < 15
        assert len(held) == 3
    finally:
        stop.set()
        for conn in held:
            conn.close()
        server.close()
