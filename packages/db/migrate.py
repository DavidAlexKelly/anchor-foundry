#!/usr/bin/env python3
"""Migration runner for packages/db.

Applies numbered ``migrations/NNNN_name.sql`` files in order, each inside its
own transaction, recording applied files (with a SHA-256 checksum) in
``schema_migrations``. Re-running is a no-op for already-applied files; a
checksum mismatch on an applied file aborts hard - applied migrations are
immutable, write a new one instead.

Usage:
    DATABASE_URL=postgresql://user:pass@host:5432/db python migrate.py [--dry-run]

Used in three places, identically:
  * local development
  * CI (schema tests run against a scratch database)
  * the deployed stack - the control plane runs this container command as
    part of every version update (spec §6 "Runs any database migrations
    automatically").
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path

import psycopg
from psycopg import sql

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
# `.py` steps run in the same numbered sequence as `.sql` ones, in their own
# transaction, recorded the same way. They exist for the one thing SQL is the
# wrong tool for: rewriting a jsonb document whose *meaning* the application
# defines. Decision 0002's Workshop conversion is the first, and it is
# deliberately the same converter the tests exercise rather than a second
# implementation of the format in PL/pgSQL.
FILENAME_RE = re.compile(r"^(\d{4})_[a-z0-9_]+\.(sql|py)$")

BOOTSTRAP_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename    text PRIMARY KEY,
    checksum    text NOT NULL,
    applied_at  timestamptz NOT NULL DEFAULT now()
);
"""


def discover_migrations() -> list[Path]:
    files: list[Path] = []
    for p in sorted(MIGRATIONS_DIR.iterdir()):
        if p.is_file() and FILENAME_RE.match(p.name):
            files.append(p)
        elif p.is_file() and p.suffix in (".sql", ".py"):
            raise SystemExit(
                f"error: {p.name} does not match NNNN_name.(sql|py) naming; "
                "refusing to guess order"
            )
    numbers = [FILENAME_RE.match(p.name).group(1) for p in files]  # type: ignore[union-attr]
    if len(set(numbers)) != len(numbers):
        raise SystemExit("error: duplicate migration numbers detected")
    return files


def apply_python_migration(path: Path, cur: "psycopg.Cursor") -> None:
    """Run a `.py` migration's `apply(cur)`.

    Loaded by path rather than imported as a module: migration file names are
    not importable identifiers (they start with a digit), and putting them on
    `sys.path` would make every migration a permanent name in the process.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(f"migration_{path.stem}", path)
    if spec is None or spec.loader is None:  # pragma: no cover - unreachable in practice
        raise RuntimeError(f"{path.name} could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    apply = getattr(module, "apply", None)
    if not callable(apply):
        raise RuntimeError(f"{path.name} has no apply(cur) function")
    apply(cur)


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sync_app_password(conn: psycopg.Connection) -> None:
    """0006_rls.sql creates platform_app with a fixed placeholder password
    (migrations are checksummed/immutable, so the real per-deployment
    password can't live in the migration file itself). PLATFORM_APP_PASSWORD
    carries the actual value from Secrets Manager in the deployed stack.
    Safe to run on every invocation, not just first-time — keeps the role in
    sync if the secret is ever rotated.

    **Every environment has to set it, including CI.** This docstring used to
    say local dev and CI don't, "so this is a no-op there", and that sentence
    was the whole of the CI failure: the placeholder password stayed in place
    while DATABASE_URL connected as platform_app with `devpass`. Locally
    `scripts/setup.sh` arranges it; in CI the workflow sets it on the Migrate
    step. Unset, the role exists and every migration applies, and then
    everything that connects as the app role is refused."""
    password = os.environ.get("PLATFORM_APP_PASSWORD")
    if not password:
        return
    with conn.cursor() as cur:
        cur.execute(sql.SQL("ALTER ROLE platform_app PASSWORD {}").format(sql.Literal(password)))
    conn.commit()


def run(dsn: str, *, dry_run: bool = False) -> int:
    """Applies pending migrations against dsn. Returns an exit-code-shaped
    int (0 ok, 1 migration error, 2 setup/connection error) rather than
    raising, so main() keeps its existing exit-code behaviour; callers that
    want a hard failure (the CDK migration Lambda, infra/cdk's
    MigrationTriggerConstruct) should raise on a nonzero result themselves."""
    migrations = discover_migrations()
    if not migrations:
        print("no migrations found", file=sys.stderr)
        return 2

    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(BOOTSTRAP_SQL)
            conn.commit()

            with conn.cursor() as cur:
                cur.execute("SELECT filename, checksum FROM schema_migrations")
                applied: dict[str, str] = {row[0]: row[1] for row in cur.fetchall()}

            pending: list[Path] = []
            for m in migrations:
                digest = checksum(m)
                if m.name in applied:
                    if applied[m.name] != digest:
                        print(
                            f"error: {m.name} was modified after being applied "
                            f"(checksum mismatch). Applied migrations are immutable.",
                            file=sys.stderr,
                        )
                        return 1
                    continue
                pending.append(m)

            if not pending:
                print("database is up to date")
                if not dry_run:
                    sync_app_password(conn)
                return 0

            for m in pending:
                print(f"{'would apply' if dry_run else 'applying'}: {m.name}")
                if dry_run:
                    continue
                try:
                    with conn.transaction():
                        with conn.cursor() as cur:
                            if m.suffix == ".py":
                                apply_python_migration(m, cur)
                            else:
                                cur.execute(m.read_text())
                            cur.execute(
                                "INSERT INTO schema_migrations (filename, checksum) VALUES (%s, %s)",
                                (m.name, checksum(m)),
                            )
                except psycopg.Error as exc:
                    print(f"error applying {m.name}: {exc}", file=sys.stderr)
                    return 1
                except Exception as exc:  # noqa: BLE001 - a .py step can raise anything
                    # Same outcome as a SQL failure and for the same reason: the
                    # transaction rolls back and nothing is recorded, so a
                    # half-converted database is not a state this can leave
                    # behind.
                    print(f"error applying {m.name}: {exc}", file=sys.stderr)
                    return 1
            conn.commit()
            if not dry_run:
                sync_app_password(conn)
    except psycopg.OperationalError as exc:
        print(f"error: could not connect to database: {exc}", file=sys.stderr)
        return 2

    print(f"applied {len(pending)} migration(s)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="list pending migrations only")
    args = parser.parse_args()

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("error: DATABASE_URL is not set", file=sys.stderr)
        return 2

    return run(dsn, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
