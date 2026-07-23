"""Dagster resources. The worker connects as platform_app and identifies
itself via the app.service GUC — RLS policies (db 0006) grant the worker
branch cross-workspace read where jobs require it. DDL never happens
directly: privileged operations go through SECURITY DEFINER functions
installed by migrations (e.g. drop_orphaned_workspace_schema, db 0010)."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator
from uuid import UUID

import psycopg
from dagster import ConfigurableResource


class PlatformDatabase(ConfigurableResource):
    """Connection factory for the platform database."""

    dsn: str

    @contextmanager
    def connect(self) -> Iterator[psycopg.Connection]:
        """Unscoped worker identity — visible only where a policy explicitly
        checks `app.service = 'worker'` without a workspace match (e.g. the
        SECURITY DEFINER discovery functions, which don't need row access at
        all). Ordinary RLS-protected tables (models, connections, datasets,
        ...) are invisible through this connection — use `connect_scoped_to`
        for those, one workspace at a time, exactly like `rls_worker_for_workspace`
        (db 0006) requires."""
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('app.service', 'worker', false)")
            yield conn

    @contextmanager
    def connect_scoped_to(self, workspace_id: UUID) -> Iterator[psycopg.Connection]:
        """Worker identity scoped to a single workspace — the only shape
        `rls_worker_for_workspace` grants. Jobs discover candidates across
        every workspace via a SECURITY DEFINER function first (never trusted
        for the mutation itself), then open one of these per candidate to
        re-verify and act on it through the normal RLS-scoped path."""
        with psycopg.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('app.service', 'worker', false)")
                cur.execute("SELECT set_config('app.workspace_id', %s, false)", (str(workspace_id),))
            yield conn
