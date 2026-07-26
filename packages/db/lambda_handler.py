"""Lambda entrypoint for infra/cdk's migration trigger (constructs/migration.ts).

Runs migrate.py's pending migrations against the just-provisioned RDS
instance, then syncs platform_app's password - the same two steps §17 of
STATUS.md documented doing by hand via CloudShell on every real deploy,
because nothing in the pipeline ever ran them. `triggers.TriggerFunction`
wires this to run after the database exists and before the app services
that depend on its schema come up.

Not a copy of the CLI: Lambda has no ECS-style Secrets Manager env
injection, so connection pieces are resolved here via boto3 at invoke time
(DB_SECRET_ARN/APP_DB_SECRET_ARN env vars carry only the secret ARNs, never
the values themselves - consistent with how the API/worker never embed
resolved secrets in their own task definitions either).
"""
from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import quote

import boto3

import migrate

_secrets = boto3.client("secretsmanager")


def _secret_json(arn: str) -> dict[str, str]:
    resp = _secrets.get_secret_value(SecretId=arn)
    return json.loads(resp["SecretString"])


def handler(event: dict[str, Any], context: object) -> dict[str, str]:
    master = _secret_json(os.environ["DB_SECRET_ARN"])
    app = _secret_json(os.environ["APP_DB_SECRET_ARN"])
    host = os.environ["DATABASE_HOST"]
    port = os.environ["DATABASE_PORT"]
    dbname = os.environ.get("DATABASE_NAME", "platform")

    dsn = (
        f"postgresql://{master['username']}:{quote(master['password'], safe='')}"
        f"@{host}:{port}/{dbname}?sslmode=require"
    )
    os.environ["PLATFORM_APP_PASSWORD"] = app["password"]

    status = migrate.run(dsn)
    if status != 0:
        raise RuntimeError(f"migration run failed with exit status {status}")
    return {"status": "ok"}
