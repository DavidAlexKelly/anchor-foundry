"""Dagster resources. The worker connects as platform_app and identifies
itself via the app.service GUC — RLS policies (db 0006) grant the worker
branch cross-workspace read where jobs require it. DDL never happens
directly: privileged operations go through SECURITY DEFINER functions
installed by migrations (e.g. drop_orphaned_workspace_schema, db 0010)."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg
from dagster import ConfigurableResource


class PlatformDatabase(ConfigurableResource):
    """Connection factory for the platform database."""

    dsn: str

    @contextmanager
    def connect(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                # Session-scoped service identity for RLS worker branches.
                cur.execute("SELECT set_config('app.service', 'worker', false)")
            yield conn
