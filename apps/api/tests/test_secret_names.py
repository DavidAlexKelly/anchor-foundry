"""The task roles may touch the secrets the code creates (§846).

`Boto3SecretsGateway` names each connection's secret `anchor/connections/<id>`;
the API and worker task roles allowed `platform/connections/*`. So on a
deployed stack, saving a connection's credentials was denied, and so was the
worker reading one to sync. Nothing exercised it: the deployment rehearsals
never created a connection with a secret. This reads both and holds them
together.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import secrets  # noqa: E402

SERVICES_TS = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                           "infra", "cdk", "src", "constructs", "services.ts")


def granted_prefixes() -> list[str]:
    text = open(SERVICES_TS, encoding="utf-8").read()
    return re.findall(r'resourceName:\s*"([^"]+)\*"', text)


def test_the_roles_name_the_prefix_the_gateway_writes() -> None:
    granted = granted_prefixes()
    assert granted, "no secret prefix found in services.ts - the parse went stale"
    assert granted == [secrets.SECRET_PREFIX], granted


def test_the_gateway_writes_under_that_prefix() -> None:
    class Client:
        class exceptions:
            class ResourceExistsException(Exception):
                pass

        def create_secret(self, Name, SecretString):
            self.name = Name
            return {"ARN": f"arn:aws:secretsmanager:eu-west-2:1:secret:{Name}-AbCdEf"}

    gateway = secrets.Boto3SecretsGateway.__new__(secrets.Boto3SecretsGateway)
    gateway._client = Client()
    gateway.put_secret("conn-1", {"password": "x"})
    assert gateway._client.name == f"{secrets.SECRET_PREFIX}conn-1"


def test_nothing_still_grants_the_old_prefix() -> None:
    assert "platform/connections" not in open(SERVICES_TS, encoding="utf-8").read().replace(
        "this named `platform/connections/*`", "")
