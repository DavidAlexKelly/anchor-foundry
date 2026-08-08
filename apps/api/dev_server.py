"""Local development server for the API.

Runs the real app with one substitution: token verification uses a locally
generated RS256 keypair instead of Cognito's JWKS, and mints tokens for the
seeded users so the web app's dev sign-in box can be used. Everything else -
RLS, permissions, audit - is the production code path.

Flagged for review: development tooling only; never deploy. The production
entrypoint is `uvicorn src.main:app`, which uses CognitoTokenVerifier.

Usage:
    DATABASE_URL=postgresql+psycopg://platform_app:...@.../platform \\
    TEST_ADMIN_DSN=postgresql://platform:...@.../platform \\
    python3 dev_server.py [--port 8300]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

import jwt as pyjwt
import psycopg
from cryptography.hazmat.primitives.asymmetric import rsa

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Local dev is http://localhost, where a Secure cookie is never sent.
os.environ.setdefault("SESSION_COOKIE_SECURE", "false")
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
    tokens (§9) - the long TTL here exists purely to avoid re-pasting."""
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


def seed(
    admin_dsn: str, extra: list[tuple[str, str, str, str]] | None = None
) -> list[tuple[str, str, str]]:
    """Idempotently create the dev org, users, a workspace, and projects.
    Returns (email, org_role, sub) per user.

    `extra` is (email, display name, org role, workspace role) and adds users
    beyond the four fixed ones, so testing as somebody who is not one of
    owner/admin/editor/viewer does not mean editing this file. They join the
    same dev org: a *second* organisation would need its own workspace and a
    way to switch between them, which is a bigger thing than "let me try this
    as another person".

    **The workspace role is why this is not just an INSERT into users.** Org
    membership alone grants a plain member access to nothing -
    `effective_workspace_role` returns NULL without a `workspace_members` row -
    so a user seeded without one signs in successfully and sees an empty
    product. That is indistinguishable from a broken deployment at the moment
    you are trying to judge whether the thing works.
    """
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
        fixed = [(email, name, role, None) for email, name, role in DEV_USERS]
        for email, name, role, _ws_role in [*fixed, *(extra or [])]:
            # Derived from the whole address, not its local part: two extra
            # users at `sam@a.local` and `sam@b.local` would otherwise share one
            # identity and each other's permissions.
            sub = "dev-" + email.replace("@", "-at-").replace(".", "-")
            existing = conn.execute(
                "SELECT id, cognito_sub FROM users WHERE organisation_id=%s AND email=%s",
                (org_id, email),
            ).fetchone()
            if existing is None:
                existing = conn.execute(
                    """INSERT INTO users (organisation_id, email, display_name,
                                          org_role, cognito_sub, status)
                       VALUES (%s,%s,%s,%s,%s,'active') RETURNING id, cognito_sub""",
                    (org_id, email, name, role, sub),
                ).fetchone()
            assert existing is not None
            # **The stored identity wins.** A token is minted for whatever
            # `cognito_sub` the row already has; deriving one and minting for
            # that instead would issue tokens no existing user matches, and the
            # symptom would be every seeded login failing at once.
            user_ids[email] = existing[0]
            out.append((email, role, existing[1]))

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

        # **Outside the `if`**, unlike the four fixed grants above. Those run
        # once, when the workspace is created; an extra user asked for on a
        # database that already has one would otherwise be given nothing, and
        # the failure is invisible - the login works and the home screen is
        # empty. Upserted rather than inserted so re-running with a changed
        # role changes the role instead of raising on the primary key.
        for email, _name, org_role, ws_role in extra or []:
            if org_role in ("owner", "admin"):
                # An org owner or admin already resolves to workspace 'admin'
                # everywhere in the org. A membership row would be a second
                # copy of that fact, free to disagree with it later.
                continue
            conn.execute(
                # The `WHERE` is not decoration: `uq_workspace_members_user` is
                # a *partial* index (rows may name a group instead of a user),
                # and Postgres will not infer a partial index without it.
                """INSERT INTO workspace_members (workspace_id, user_id, role)
                   VALUES (%s,%s,%s)
                   ON CONFLICT (workspace_id, user_id) WHERE user_id IS NOT NULL
                   DO UPDATE SET role=EXCLUDED.role""",
                (ws[0], user_ids[email], ws_role),
            )
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8300)
    parser.add_argument("--seed-only", action="store_true")
    parser.add_argument(
        "--extra-user",
        action="append",
        default=[],
        metavar="EMAIL:NAME:ORG_ROLE[:WORKSPACE_ROLE]",
        help="Seed another dev user and mint a token for them, e.g. "
        "'sam@client.local:Sam Client:member'. ORG_ROLE is owner, admin or "
        "member; WORKSPACE_ROLE is admin, editor or viewer and defaults to "
        "editor, which is what makes a member see anything at all. Repeatable, "
        "and idempotent - re-running with the same value is a no-op.",
    )
    parser.add_argument(
        "--tokens-file",
        help="Write {email: token} here as JSON. The browser suite (e2e/) reads "
        "it, because the alternative is scraping this process's stdout - which "
        "worked until a log was truncated and a suite spent a run authenticating "
        "as nobody.",
    )
    args = parser.parse_args()

    admin_dsn = os.environ.get("TEST_ADMIN_DSN")
    if not admin_dsn:
        print("TEST_ADMIN_DSN is required for seeding", file=sys.stderr)
        sys.exit(2)

    extra: list[tuple[str, str, str, str]] = []
    for spec in args.extra_user:
        parts = [p.strip() for p in spec.split(":")]
        if len(parts) == 3:
            # Editor rather than viewer, because the reason to seed a user is
            # almost always to try building something as them, and a viewer
            # who cannot is a confusing default to have chosen silently.
            parts.append("editor")
        if len(parts) != 4 or not all(parts):
            print(
                f"--extra-user wants EMAIL:NAME:ORG_ROLE[:WORKSPACE_ROLE], got {spec!r}",
                file=sys.stderr,
            )
            sys.exit(2)
        email, name, role, ws_role = parts
        if role not in ("owner", "admin", "member"):
            print(f"org role must be owner, admin or member, got {role!r}", file=sys.stderr)
            sys.exit(2)
        if ws_role not in ("admin", "editor", "viewer"):
            print(
                f"workspace role must be admin, editor or viewer, got {ws_role!r}",
                file=sys.stderr,
            )
            sys.exit(2)
        extra.append((email, name, role, ws_role))

    users = seed(admin_dsn, extra)
    minted = {email: mint(sub) for email, _, sub in users}
    print("\ndev users (paste a token into the web sign-in box):\n")
    for email, role, _ in users:
        print(f"  {email:<28} {role:<7} {minted[email]}")
    print()
    if args.tokens_file:
        # Written before the server starts listening, so anything that waits for
        # /api/health can rely on the file already being there.
        with open(args.tokens_file, "w") as handle:
            json.dump(minted, handle)
    if args.seed_only:
        return

    auth_mw.configure_verifier(DevVerifier())
    from src.main import create_app

    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
