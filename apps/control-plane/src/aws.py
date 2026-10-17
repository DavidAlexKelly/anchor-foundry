"""How long the control plane's AWS calls may take (§977): the control
plane's copy of the API's `lib/aws.py` (§970).

boto3's defaults are a minute to connect, a minute for each read, and
retries in its legacy mode. The onboarding page's preflight, connect and
provision run their AWS calls inside the customer's request, one after
another, so an AWS endpoint that stopped answering held the customer's page
for minutes with nothing on it. Each client is made here with a limit.
"""
from __future__ import annotations

from typing import Any

#: Every call the control plane makes answers small - STS, IAM, CloudFormation,
#: SSM, EC2, quotas, RDS, KMS. Three tries in botocore's standard mode, which
#: backs off between them and retries only what is worth retrying.
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
