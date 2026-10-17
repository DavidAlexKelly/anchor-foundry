"""A search domain that does not answer is a 503, not a fault (§978).

Once objects are read from OpenSearch (decision 0006; E.2), a domain
restarting or changing its nodes made every object read an unhandled error -
a 500 to the person and an alarm for whoever is on call. The database's
moments of absence were made a 503 with a `Retry-After` in §951; these hold
the same for the search domain, and that the store's client says so within
seconds rather than retrying a dead host three times.
"""
from __future__ import annotations

import logging
import os
import socket
import sys
import time

import anyio
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

opensearchpy = pytest.importorskip("opensearchpy")

from src.main import SEARCH_UNAVAILABLE_DETAIL, create_app  # noqa: E402
from src.services import instance_store  # noqa: E402


def test_a_search_domain_that_did_not_answer_is_a_503_that_says_so(caplog) -> None:
    app = create_app()

    @app.get("/api/_probe/search")
    async def probe() -> None:
        raise opensearchpy.exceptions.ConnectionTimeout("TIMEOUT", "timed out", None)

    with caplog.at_level(logging.WARNING, logger="anchor.unavailable"):
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get("/api/_probe/search")
    assert r.status_code == 503
    assert r.json()["detail"] == SEARCH_UNAVAILABLE_DETAIL
    assert r.headers["retry-after"] == "5"
    assert "object search unavailable" in caplog.text


def test_the_stores_client_says_so_in_seconds() -> None:
    """A port nothing listens on: refused at once, retried once, and raised as
    the class the handler above answers."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    store = instance_store.OpenSearchInstanceStore(f"http://127.0.0.1:{port}", "admin", "admin")

    async def ask() -> None:
        try:
            await store._client.info()
        finally:
            await store._client.close()

    started = time.monotonic()
    with pytest.raises(opensearchpy.exceptions.ConnectionError):
        anyio.run(ask)
    assert time.monotonic() - started < 5
    assert store._client.transport.max_retries == 1
    assert store._client.transport.retry_on_timeout is False


# ---- AWS (§979) ---------------------------------------------------------------
@pytest.mark.parametrize("raised", ["EndpointConnectionError", "ConnectTimeoutError",
                                    "ReadTimeoutError"])
def test_an_aws_service_that_did_not_answer_is_a_503_that_says_so(raised: str, caplog) -> None:
    """§970's limits end a stalled call in seconds, with one of these."""
    from botocore import exceptions as botocore_exceptions

    from src.main import AWS_UNAVAILABLE_DETAIL

    app = create_app()

    @app.get("/api/_probe/aws")
    async def probe() -> None:
        raise getattr(botocore_exceptions, raised)(endpoint_url="https://s3.eu-west-2.amazonaws.com")

    with caplog.at_level(logging.WARNING, logger="anchor.unavailable"):
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get("/api/_probe/aws")
    assert (r.status_code, r.json()["detail"], r.headers["retry-after"]) == (
        503, AWS_UNAVAILABLE_DETAIL, "5")
    assert "aws unavailable" in caplog.text


def test_an_aws_refusal_is_not_taken_for_an_absence() -> None:
    """A `ClientError` is AWS answering, not AWS gone: left as it was."""
    from botocore.exceptions import ClientError

    app = create_app()

    @app.get("/api/_probe/refused")
    async def probe() -> None:
        raise ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "GetObject")

    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/api/_probe/refused").status_code == 500
