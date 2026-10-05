"""Copy a deployment's objects from Postgres into its OpenSearch index (§813).

`instance_store.backfill` is the cutover's migration step, and its docstring
names the procedure - **backfill, flip, backfill again** - but nothing could
run it against a deployment: it was a function the tests called. This is the
command, run as a one-off task from the API image with the owner role's
`DATABASE_URL`, as `restore_check` is:

    python -m src.services.instance_cutover [--workspace <uuid>]

**Configured by the task, not by the services.** It refuses to start unless
`OPENSEARCH_ENDPOINT` and `OPENSEARCH_SECRET_ARN` are set, and the procedure
needs them set on *this* task before they are set on the services: the first
backfill copies while the API still reads Postgres, the flip points the
services at the index (`docs/deploying.md`), and the second backfill copies
whatever was written in between. Every document id is derived, so the second
run rewrites the same documents rather than duplicating them.

It prints one JSON report - each workspace's counts, then the totals - and
commits each workspace as it finishes, so a run stopped halfway has finished
workspaces that stay finished, and running it again is the way to continue.
"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import TYPE_CHECKING, Any
from uuid import UUID

from ..lib.db import fetch_all
from . import instance_store

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection


async def run(
    conn: "AsyncConnection", gateway: Any, *, workspace_id: UUID | None = None
) -> dict[str, Any]:
    workspaces = await fetch_all(
        conn,
        "SELECT id, search_prefix FROM workspaces "
        "WHERE CAST(:wid AS uuid) IS NULL OR id = CAST(:wid AS uuid) ORDER BY id",
        {"wid": str(workspace_id) if workspace_id else None},
    )
    report: list[dict[str, Any]] = []
    for row in workspaces:
        moved = await instance_store.backfill(
            conn, gateway, workspace_id=UUID(str(row["id"])),
            search_prefix=str(row["search_prefix"]),
        )
        # The audit trail's new ids, kept as soon as their documents exist.
        await conn.commit()
        report.append({"workspace_id": str(row["id"]), **moved})
    return {
        "workspaces": report,
        "instances": sum(r["instances"] for r in report),
        "action_runs_remapped": sum(r["action_runs_remapped"] for r in report),
    }


async def _main(argv: list[str]) -> int:
    import argparse

    from ..lib.db import get_engine

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workspace", type=UUID, default=None,
                        help="copy one workspace rather than all of them")
    args = parser.parse_args(argv)
    gateway = instance_store.gateway_from_env()
    if gateway is None:
        print("no object index is configured: set OPENSEARCH_ENDPOINT and "
              "OPENSEARCH_SECRET_ARN on this task", file=sys.stderr)
        return 2
    try:
        async with get_engine().connect() as conn:
            report = await run(conn, gateway, workspace_id=args.workspace)
    finally:
        await gateway.close()
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(sys.argv[1:])))
