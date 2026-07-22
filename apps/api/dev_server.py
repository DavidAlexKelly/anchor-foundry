"""Local development server for the API.

Runs the real app with one substitution: token verification uses a locally
generated RS256 keypair instead of Cognito's JWKS, and mints tokens for the
seeded users so the web app's dev sign-in box can be used. Everything else —
RLS, permissions, audit — is the production code path.

Flagged for review: development tooling only; never deploy. The production
entrypoint is `uvicorn src.main:app`, which uses CognitoTokenVerifier.

Usage:
    DATABASE_URL=postgresql+psycopg://platform_app:...@.../platform \\
    TEST_ADMIN_DSN=postgresql://platform:...@.../platform \\
    python3 dev_server.py [--port 8300]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any

import jwt as pyjwt
import psycopg
from cryptography.hazmat.primitives.asymmetric import rsa

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("COGNITO_CLIENT_ID", "dev-client")
os.environ.setdefault("COGNITO_ISSUER", "https://dev-issuer.local")

from src.lib.errors import UnauthorizedError  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_ISSUER = os.environ["COGNITO_ISSUER"]
_CLIENT = os.environ["COGNITO_CLIENT_ID"]

DEV_ORG_SLUG = "acme-dev"
DEV_USERS: list[tuple[str, str, str]] = [
    # (email, display name, org role)
    ("owner@acme.dev.local", "Odette Owner", "owner"),
    ("admin@acme.dev.local", "Ada Admin", "admin"),
    ("editor@acme.dev.local", "Ed Editor", "member"),
    ("viewer@acme.dev.local", "Vi Viewer", "member"),
]


class DevVerifier:
    """Mirrors CognitoTokenVerifier's claim checks against the dev keypair."""

    def verify(self, token: str) -> dict[str, Any]:
        try:
            claims: dict[str, Any] = pyjwt.decode(
                token,
                _KEY.public_key(),
                algorithms=["RS256"],
                issuer=_ISSUER,
                options={"require": ["exp", "iss", "sub"], "verify_exp": True},
            )
        except pyjwt.PyJWTError as exc:
            raise UnauthorizedError(f"invalid token: {type(exc).__name__}") from exc
        if claims.get("token_use") != "access" or claims.get("client_id") != _CLIENT:
            raise UnauthorizedError("token client mismatch")
        return claims


def mint(sub: str, ttl_seconds: int = 8 * 3600) -> str:
    """Dev tokens last a working day; production Cognito issues 15-minute
    tokens (§9) — the long TTL here exists purely to avoid re-pasting."""
    now = int(time.time())
    return pyjwt.encode(
        {
            "sub": sub,
            "iss": _ISSUER,
            "token_use": "access",
            "client_id": _CLIENT,
            "iat": now,
            "exp": now + ttl_seconds,
        },
        _KEY,
        algorithm="RS256",
    )


def seed(admin_dsn: str) -> list[tuple[str, str, str]]:
    """Idempotently create the dev org, users, a workspace, and projects.
    Returns (email, org_role, sub) per user."""
    out: list[tuple[str, str, str]] = []
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        row = conn.execute(
            "SELECT id FROM organisations WHERE slug=%s", (DEV_ORG_SLUG,)
        ).fetchone()
        if row is None:
            row = conn.execute(
                "INSERT INTO organisations (name, slug) VALUES (%s,%s) RETURNING id",
                ("Acme (dev)", DEV_ORG_SLUG),
            ).fetchone()
        assert row is not None
        org_id = row[0]

        user_ids: dict[str, Any] = {}
        for email, name, role in DEV_USERS:
            sub = f"dev-{email.split('@')[0]}"
            existing = conn.execute(
                "SELECT id FROM users WHERE organisation_id=%s AND email=%s",
                (org_id, email),
            ).fetchone()
            if existing is None:
                existing = conn.execute(
                    """INSERT INTO users (organisation_id, email, display_name,
                                          org_role, cognito_sub, status)
                       VALUES (%s,%s,%s,%s,%s,'active') RETURNING id""",
                    (org_id, email, name, role, sub),
                ).fetchone()
            assert existing is not None
            user_ids[email] = existing[0]
            out.append((email, role, sub))

        ws = conn.execute(
            "SELECT id FROM workspaces WHERE organisation_id=%s AND slug=%s",
            (org_id, "operations"),
        ).fetchone()
        if ws is None:
            import uuid

            wid = uuid.uuid4()
            short = wid.hex[:12]
            ws = conn.execute(
                """INSERT INTO workspaces (id, organisation_id, name, slug, description,
                                           s3_prefix, pg_schema, search_prefix, created_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (
                    wid, org_id, "Operations", "operations",
                    "Day-to-day operational data and apps.",
                    f"workspaces/operations-{short}/", f"ws_{short}", f"ws-{short}-",
                    user_ids["owner@acme.dev.local"],
                ),
            ).fetchone()
            assert ws is not None
            conn.execute("SELECT provision_workspace_schema(%s)", (ws[0],))
            conn.execute(
                "INSERT INTO workspace_members (workspace_id, user_id, role) VALUES (%s,%s,'editor')",
                (ws[0], user_ids["editor@acme.dev.local"]),
            )
            conn.execute(
                "INSERT INTO workspace_members (workspace_id, user_id, role) VALUES (%s,%s,'viewer')",
                (ws[0], user_ids["viewer@acme.dev.local"]),
            )
            for pname, pslug, pdescr in [
                ("Logistics", "logistics", "Shipment tracking and carrier data."),
                ("Customer 360", "customer-360", "A single view of every customer."),
            ]:
                conn.execute(
                    """INSERT INTO projects (workspace_id, name, slug, description, created_by)
                       VALUES (%s,%s,%s,%s,%s)""",
                    (ws[0], pname, pslug, pdescr, user_ids["owner@acme.dev.local"]),
                )
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8300)
    parser.add_argument("--seed-only", action="store_true")
    args = parser.parse_args()

    admin_dsn = os.environ.get("TEST_ADMIN_DSN")
    if not admin_dsn:
        print("TEST_ADMIN_DSN is required for seeding", file=sys.stderr)
        sys.exit(2)

    users = seed(admin_dsn)
    print("\ndev users (paste a token into the web sign-in box):\n")
    for email, role, sub in users:
        print(f"  {email:<28} {role:<7} {mint(sub)}")
    print()
    if args.seed_only:
        return

    auth_mw.configure_verifier(DevVerifier())
    from src.main import create_app

    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
