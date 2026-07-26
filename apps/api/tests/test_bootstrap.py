"""Bootstrap route tests (migration 0017, services/orgs.platform_needs_setup /
bootstrap_first_owner, routes/bootstrap.py).

The one-time first-owner guard can only be exercised truthfully against a
platform database with zero organisations - but the shared dev/test database
already has rows by the time this module runs (test_actions.py/test_api.py's
fixtures insert them first, alphabetically) - so the empty-platform happy path
runs against its own freshly migrated scratch database, exactly like
test_connections.py's source_database fixture. The already-set-up assertions
(409, validation) run against the ordinary shared client/fx fixtures, since
those don't depend on the table being empty.
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, client, fx  # noqa: E402,F401  (fixtures + reuse)
from src.lib import config as config_lib  # noqa: E402
from src.lib import db as db_lib  # noqa: E402
from src.main import create_app  # noqa: E402
from src.routes import bootstrap as bootstrap_routes  # noqa: E402
from src.services.orgs import NullCognitoGateway  # noqa: E402

ADMIN_DSN = os.environ["TEST_ADMIN_DSN"]
REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATE_PY = REPO_ROOT / "packages" / "db" / "migrate.py"


# ---- already-set-up path: shared dev database is never empty ---------------
def test_status_is_false_once_any_organisation_exists(client: TestClient, fx: Fixture) -> None:
    r = client.get("/api/bootstrap/status")
    assert r.status_code == 200
    assert r.json() == {"needs_setup": False}


def test_first_owner_conflicts_once_platform_is_set_up(client: TestClient, fx: Fixture) -> None:
    r = client.post(
        "/api/bootstrap/first-owner",
        json={
            "organisation_name": "Should Not Exist",
            "organisation_slug": "should-not-exist",
            "owner_email": "nope@example.com",
            "owner_display_name": "Nobody",
        },
    )
    assert r.status_code == 409
    assert r.json() == {"detail": "this platform has already been set up"}


def test_bad_slug_is_422(client: TestClient) -> None:
    r = client.post(
        "/api/bootstrap/first-owner",
        json={
            "organisation_name": "Bad",
            "organisation_slug": "Not Valid!",
            "owner_email": "x@example.com",
            "owner_display_name": "X",
        },
    )
    assert r.status_code == 422


def test_bad_email_is_422(client: TestClient) -> None:
    r = client.post(
        "/api/bootstrap/first-owner",
        json={
            "organisation_name": "Bad",
            "organisation_slug": "bad-email",
            "owner_email": "not-an-email",
            "owner_display_name": "X",
        },
    )
    assert r.status_code == 422


# ---- SQL-level: migration 0017's functions on a genuinely empty database ---
# Function-scoped (not module-scoped): both tests below need the table to
# start genuinely empty, so each gets its own freshly migrated database
# rather than sharing one that an earlier test already bootstrapped.
@pytest.fixture
def scratch_dsns() -> Iterator[dict[str, str]]:
    name = f"bootstrap_scratch_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(f"CREATE DATABASE {name} OWNER platform")
    owner_dsn = ADMIN_DSN.replace("/platform?", f"/{name}?")
    subprocess.run(
        [sys.executable, str(MIGRATE_PY)],
        check=True,
        env={**os.environ, "DATABASE_URL": owner_dsn},
        cwd=str(MIGRATE_PY.parent),
    )
    app_dsn = owner_dsn.replace("postgresql://platform:", "postgresql://platform_app:")
    try:
        yield {"owner": owner_dsn, "app": app_dsn, "name": name}
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
            conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname=%s AND pid <> pg_backend_pid()",
                (name,),
            )
            conn.execute(f"DROP DATABASE {name}")


def test_migration_0017_functions_on_empty_database(scratch_dsns: dict[str, str]) -> None:
    with psycopg.connect(scratch_dsns["app"], autocommit=True) as conn:
        assert conn.execute("SELECT platform_has_any_organisation()").fetchone()[0] is False

        org_id = conn.execute(
            "SELECT bootstrap_first_owner(%s, %s, %s, %s, %s)",
            ("Acme", "acme", "sub-123", "owner@acme.example", "Owner Person"),
        ).fetchone()[0]
        assert org_id is not None

        assert conn.execute("SELECT platform_has_any_organisation()").fetchone()[0] is True

        # One-time guard: a second call is rejected atomically, not silently.
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(
                "SELECT bootstrap_first_owner(%s, %s, %s, %s, %s)",
                ("Acme2", "acme2", "sub-456", "owner2@acme.example", "Owner Two"),
            )

    # platform_app has no app.user_id session context here, so RLS blocks a
    # plain SELECT even for its own just-inserted row - only the table owner
    # (migrations/DBA role) bypasses non-FORCEd RLS. Verify the row's actual
    # content through that connection instead.
    with psycopg.connect(scratch_dsns["owner"], autocommit=True) as conn:
        row = conn.execute(
            "SELECT email, org_role, cognito_sub FROM users WHERE organisation_id=%s",
            (org_id,),
        ).fetchone()
        assert row == ("owner@acme.example", "owner", "sub-123")


# ---- full route/service stack against the same empty scratch database ------
@pytest.fixture
def scratch_client(monkeypatch: pytest.MonkeyPatch, scratch_dsns: dict[str, str]) -> Iterator[TestClient]:
    """Points the whole app (its process-wide engine/settings singletons)
    at the scratch database for the duration of one test, then restores
    them - db.py's engine and config.py's get_settings() are both cached
    globals, so later modules in the same pytest run must see the shared
    dev database again, not this scratch one."""
    app_url = scratch_dsns["app"].replace("postgresql://", "postgresql+psycopg://")
    monkeypatch.setenv("DATABASE_URL", app_url)
    config_lib.get_settings.cache_clear()
    db_lib._engine = None
    bootstrap_routes.configure_cognito_gateway(NullCognitoGateway())
    app = create_app()
    with TestClient(app) as c:
        yield c
    db_lib._engine = None
    config_lib.get_settings.cache_clear()


def test_full_bootstrap_flow_on_empty_platform(scratch_client: TestClient) -> None:
    r = scratch_client.get("/api/bootstrap/status")
    assert r.status_code == 200
    assert r.json() == {"needs_setup": True}

    r = scratch_client.post(
        "/api/bootstrap/first-owner",
        json={
            "organisation_name": "Acme",
            "organisation_slug": "acme",
            "owner_email": "owner@acmecorp.io",
            "owner_display_name": "Owner Person",
        },
    )
    assert r.status_code == 201
    org_id = r.json()["organisation_id"]
    assert uuid.UUID(org_id)

    r = scratch_client.get("/api/bootstrap/status")
    assert r.json() == {"needs_setup": False}

    r = scratch_client.post(
        "/api/bootstrap/first-owner",
        json={
            "organisation_name": "Acme2",
            "organisation_slug": "acme2",
            "owner_email": "owner2@acmecorp.io",
            "owner_display_name": "Owner Two",
        },
    )
    assert r.status_code == 409
