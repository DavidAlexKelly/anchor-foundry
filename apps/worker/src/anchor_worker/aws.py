"""How long the platform's own AWS calls may take (§970): the worker's copy of
the API's `lib/aws.py`.

boto3's defaults are a minute to connect, a minute for each read, and
retries in its legacy mode, so a pass that asked Secrets Manager for a
source's password while the endpoint did not answer sat there for minutes,
holding its run and everything queued behind it. Each client is made here
with a limit that fits what it asks for. A source's own S3 bucket is the
customer's, and its connector sets its own (`connectors.py`).
"""
from __future__ import annotations

from typing import Any

#: Secrets Manager and ECS: small answers. Three tries in botocore's
#: standard mode, which backs off between them and retries only what is
#: worth retrying.
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
