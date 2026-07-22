"""Customer stack registry (spec §7 monorepo: control-plane/src/registry).

Tracks every customer deployment: which AWS account, which region, which
version, the bootstrap role ARN, and the per-customer external ID used to
assume it (spec §6 "The Bootstrap IAM Role").

The external ID is a secret shared between us and exactly one customer. It is
stored encrypted with a KMS data key in production; this module treats the
cipherblob as opaque and delegates crypto to `SecretsCodec` so tests can use
a deterministic codec. It is never logged and never returned by any API.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol

import psycopg
from psycopg.rows import dict_row

# 32+ chars required by the bootstrap CloudFormation template's MinLength.
_EXTERNAL_ID_BYTES = 32


class StackStatus(str, Enum):
    PENDING = "pending"
    PROVISIONING = "provisioning"
    READY = "ready"
    UPDATING = "updating"
    FAILED = "failed"
    DESTROYING = "destroying"
    DESTROYED = "destroyed"


class SecretsCodec(Protocol):
    """Encrypt/decrypt external IDs. Production: KMS envelope encryption."""

    def encrypt(self, plaintext: str) -> bytes: ...
    def decrypt(self, ciphertext: bytes) -> str: ...


@dataclass(frozen=True)
class CustomerRecord:
    id: str
    org_slug: str
    aws_account_id: str | None
    aws_region: str | None
    bootstrap_role_arn: str | None
    stack_status: StackStatus
    stack_version: str | None
    platform_url: str | None
    outputs: dict[str, str]
    created_at: datetime
    updated_at: datetime


_SCHEMA = """
CREATE TABLE IF NOT EXISTS customer_stacks (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_slug             text NOT NULL UNIQUE,
    aws_account_id       text,
    aws_region           text,
    bootstrap_role_arn   text,
    external_id_cipher   bytea NOT NULL,
    stack_status         text NOT NULL DEFAULT 'pending',
    stack_version        text,
    platform_url         text,
    outputs              jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now()
);
"""

_SLUG_RE = r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$"


def generate_external_id() -> str:
    """Unique per customer, secret, high entropy (spec §6)."""
    return secrets.token_urlsafe(_EXTERNAL_ID_BYTES)


class StackRegistry:
    def __init__(self, dsn: str, codec: SecretsCodec) -> None:
        self._dsn = dsn
        self._codec = codec

    def _conn(self) -> psycopg.Connection:
        return psycopg.connect(self._dsn, row_factory=dict_row)

    def ensure_schema(self) -> None:
        with self._conn() as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
            conn.execute(_SCHEMA)
            conn.commit()

    # ---- lifecycle ----------------------------------------------------------
    def register_customer(self, org_slug: str) -> tuple[CustomerRecord, str]:
        """Create the registry row and mint the external ID.

        Returns (record, external_id_plaintext). The plaintext is shown to the
        customer exactly once during onboarding (they paste it into the
        bootstrap CloudFormation parameters) and is otherwise only ever
        decrypted server-side at assume-role time.
        """
        import re

        if not re.match(_SLUG_RE, org_slug):
            raise ValueError(f"invalid org slug: {org_slug!r}")
        external_id = generate_external_id()
        cipher = self._codec.encrypt(external_id)
        with self._conn() as conn:
            row = conn.execute(
                """INSERT INTO customer_stacks (org_slug, external_id_cipher)
                   VALUES (%s, %s)
                   ON CONFLICT (org_slug) DO NOTHING
                   RETURNING *""",
                (org_slug, cipher),
            ).fetchone()
            conn.commit()
        if row is None:
            raise ValueError(f"customer {org_slug!r} is already registered")
        return self._to_record(row), external_id

    def connect_aws(
        self, org_slug: str, aws_account_id: str, aws_region: str, bootstrap_role_arn: str
    ) -> CustomerRecord:
        import re

        if not re.match(r"^[0-9]{12}$", aws_account_id):
            raise ValueError("aws_account_id must be a 12-digit account ID")
        if not re.match(r"^[a-z]{2}(-[a-z]+)+-[0-9]$", aws_region):
            raise ValueError(f"invalid AWS region: {aws_region!r}")
        if not re.match(rf"^arn:aws:iam::{aws_account_id}:role/.+$", bootstrap_role_arn):
            raise ValueError("bootstrap_role_arn must be an IAM role ARN in the connected account")
        with self._conn() as conn:
            row = conn.execute(
                """UPDATE customer_stacks
                      SET aws_account_id=%s, aws_region=%s, bootstrap_role_arn=%s,
                          updated_at=now()
                    WHERE org_slug=%s RETURNING *""",
                (aws_account_id, aws_region, bootstrap_role_arn, org_slug),
            ).fetchone()
            conn.commit()
        if row is None:
            raise KeyError(f"unknown customer {org_slug!r}")
        return self._to_record(row)

    def set_status(
        self,
        org_slug: str,
        status: StackStatus,
        *,
        version: str | None = None,
        platform_url: str | None = None,
        outputs: dict[str, str] | None = None,
    ) -> CustomerRecord:
        import json

        with self._conn() as conn:
            row = conn.execute(
                """UPDATE customer_stacks
                      SET stack_status=%s,
                          stack_version=COALESCE(%s, stack_version),
                          platform_url=COALESCE(%s, platform_url),
                          outputs=COALESCE(%s::jsonb, outputs),
                          updated_at=now()
                    WHERE org_slug=%s RETURNING *""",
                (
                    status.value,
                    version,
                    platform_url,
                    json.dumps(outputs) if outputs is not None else None,
                    org_slug,
                ),
            ).fetchone()
            conn.commit()
        if row is None:
            raise KeyError(f"unknown customer {org_slug!r}")
        return self._to_record(row)

    def get(self, org_slug: str) -> CustomerRecord:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM customer_stacks WHERE org_slug=%s", (org_slug,)
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown customer {org_slug!r}")
        return self._to_record(row)

    def external_id_for(self, org_slug: str) -> str:
        """Decrypt the external ID — used ONLY at STS assume-role time."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT external_id_cipher FROM customer_stacks WHERE org_slug=%s",
                (org_slug,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown customer {org_slug!r}")
        return self._codec.decrypt(bytes(row["external_id_cipher"]))

    @staticmethod
    def _to_record(row: dict[str, object]) -> CustomerRecord:
        return CustomerRecord(
            id=str(row["id"]),
            org_slug=str(row["org_slug"]),
            aws_account_id=row["aws_account_id"],  # type: ignore[arg-type]
            aws_region=row["aws_region"],  # type: ignore[arg-type]
            bootstrap_role_arn=row["bootstrap_role_arn"],  # type: ignore[arg-type]
            stack_status=StackStatus(str(row["stack_status"])),
            stack_version=row["stack_version"],  # type: ignore[arg-type]
            platform_url=row["platform_url"],  # type: ignore[arg-type]
            outputs=dict(row["outputs"] or {}),  # type: ignore[arg-type]
            created_at=row["created_at"] if isinstance(row["created_at"], datetime) else datetime.now(timezone.utc),
            updated_at=row["updated_at"] if isinstance(row["updated_at"], datetime) else datetime.now(timezone.utc),
        )
