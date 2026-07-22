#!/usr/bin/env python3
"""Migration runner for packages/db.

Applies numbered ``migrations/NNNN_name.sql`` files in order, each inside its
own transaction, recording applied files (with a SHA-256 checksum) in
``schema_migrations``. Re-running is a no-op for already-applied files; a
checksum mismatch on an applied file aborts hard — applied migrations are
immutable, write a new one instead.

Usage:
    DATABASE_URL=postgresql://user:pass@host:5432/db python migrate.py [--dry-run]

Used in three places, identically:
  * local development
  * CI (schema tests run against a scratch database)
  * the deployed stack — the control plane runs this container command as
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

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
FILENAME_RE = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")

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
        elif p.is_file() and p.suffix == ".sql":
            raise SystemExit(
                f"error: {p.name} does not match NNNN_name.sql naming; refusing to guess order"
            )
    numbers = [FILENAME_RE.match(p.name).group(1) for p in files]  # type: ignore[union-attr]
    if len(set(numbers)) != len(numbers):
        raise SystemExit("error: duplicate migration numbers detected")
    return files


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="list pending migrations only")
    args = parser.parse_args()

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("error: DATABASE_URL is not set", file=sys.stderr)
        return 2

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
                return 0

            for m in pending:
                print(f"{'would apply' if args.dry_run else 'applying'}: {m.name}")
                if args.dry_run:
                    continue
                try:
                    with conn.transaction():
                        with conn.cursor() as cur:
                            cur.execute(m.read_text())
                            cur.execute(
                                "INSERT INTO schema_migrations (filename, checksum) VALUES (%s, %s)",
                                (m.name, checksum(m)),
                            )
                except psycopg.Error as exc:
                    print(f"error applying {m.name}: {exc}", file=sys.stderr)
                    return 1
            conn.commit()
    except psycopg.OperationalError as exc:
        print(f"error: could not connect to database: {exc}", file=sys.stderr)
        return 2

    print(f"applied {len(pending)} migration(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
