"""How long the platform's own AWS calls may take (§970).

boto3's defaults are a minute to connect, a minute for each read, and
retries in its legacy mode. So when an AWS endpoint stopped answering, a
request that asked Secrets Manager for a source's password, or Cognito to
invite somebody, waited minutes - long after CloudFront had given up on it -
holding one of the threads every other blocking call shares (§954). A few of
those and requests that never touch AWS waited too.

Each client is made here with a limit that fits what it asks for. A source's
own S3 bucket is the customer's, not the platform's, and its connector sets
its own (`services/connectors.py`).
"""
from __future__ import annotations

from typing import Any

#: Secrets Manager and Cognito: small answers, asked for on a request's
#: path. Three tries in botocore's standard mode, which backs off between
#: them and retries only what is worth retrying, inside CloudFront's minute.
CONTROL: dict[str, Any] = {
    "connect_timeout": 3, "read_timeout": 5,
    "retries": {"mode": "standard", "total_max_attempts": 3},
}

#: The data bucket: an object may be large, and the read timeout is for each
#: read of the socket rather than the whole object, so it is longer; the
#: connect is not.
STORAGE: dict[str, Any] = {
    "connect_timeout": 3, "read_timeout": 30,
    "retries": {"mode": "standard", "total_max_attempts": 3},
}


def client(service: str, limits: dict[str, Any] = CONTROL, **kwargs: Any) -> Any:
    """A boto3 client for `service` held to `limits`."""
    import boto3  # deferred: not installed in local dev
    from botocore.config import Config

    return boto3.client(service, config=Config(**limits), **kwargs)
