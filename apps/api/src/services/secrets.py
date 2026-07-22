"""Connection credential storage (spec §"Connections" credential handling).

Credentials live in the customer's own AWS Secrets Manager and nowhere else:
the API writes them at creation, reads them only to open a connection, and
never returns them in any response. The gateway protocol keeps that boundary
explicit and testable.

Secret names follow anchor/connections/{connection_id} — one secret per
connection, replaced wholesale on credential update, deleted with the
connection.
"""
from __future__ import annotations

import json
from typing import Protocol


class SecretsGateway(Protocol):
    def put_secret(self, connection_id: str, values: dict[str, str]) -> str:
        """Create or replace the secret; returns its ARN (or stable id)."""
        ...

    def get_secret(self, secret_arn: str) -> dict[str, str]:
        """Fetch secret values for establishing a connection. Callers must
        never place the result in a response, log line, or audit record."""
        ...

    def delete_secret(self, secret_arn: str) -> None: ...


class Boto3SecretsGateway:
    """Production gateway. The ECS task role carries a policy scoped to the
    anchor/connections/* name prefix (CDK services construct) — the API can
    manage exactly these secrets and nothing else in the account."""

    def __init__(self, region: str) -> None:
        import boto3  # deferred: not installed in local dev

        self._client = boto3.client("secretsmanager", region_name=region)

    def put_secret(self, connection_id: str, values: dict[str, str]) -> str:
        name = f"anchor/connections/{connection_id}"
        payload = json.dumps(values)
        try:
            resp = self._client.create_secret(Name=name, SecretString=payload)
            return str(resp["ARN"])
        except self._client.exceptions.ResourceExistsException:
            resp = self._client.put_secret_value(SecretId=name, SecretString=payload)
            return str(resp["ARN"])

    def get_secret(self, secret_arn: str) -> dict[str, str]:
        resp = self._client.get_secret_value(SecretId=secret_arn)
        data = json.loads(resp["SecretString"])
        if not isinstance(data, dict):
            raise ValueError("secret payload is not an object")
        return {str(k): str(v) for k, v in data.items()}

    def delete_secret(self, secret_arn: str) -> None:
        # Recovery window rather than force-delete: a mistaken connection
        # delete should not destroy the customer's credentials instantly.
        self._client.delete_secret(SecretId=secret_arn, RecoveryWindowInDays=7)


class InMemorySecretsGateway:
    """Dev/test gateway. Flagged for review: development only — holds values
    in process memory, so credentials do not survive a restart and are never
    written to disk or the database."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, str]] = {}

    def put_secret(self, connection_id: str, values: dict[str, str]) -> str:
        arn = f"local:secret:anchor/connections/{connection_id}"
        self._store[arn] = dict(values)
        return arn

    def get_secret(self, secret_arn: str) -> dict[str, str]:
        if secret_arn not in self._store:
            raise KeyError("secret not found")
        return dict(self._store[secret_arn])

    def delete_secret(self, secret_arn: str) -> None:
        self._store.pop(secret_arn, None)
