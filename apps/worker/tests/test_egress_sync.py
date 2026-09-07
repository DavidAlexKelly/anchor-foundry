"""Egress policies on the one outbound path with no caller (§263).

`apps/api/tests/test_egress_policies.py` covers the three paths a *request*
starts: a source test, a discovery, a webhook. This covers the fourth, and it
is the one that matters most for the same reason it is easiest to leave out —
a **scheduled sync** has nobody watching it, runs in a different process, and
reaches an external system on a timer.

**The line under test is `sync_configs.run_due_scheduled_syncs`'s
`egress.restricted_to(policies)`.** Every guard in the worker's connectors is
downstream of it, and `egress.check` treats an empty scope as unrestricted by
design (decision 0013 §2) — so dropping that one `with` would leave four
guards intact, every test in `test_egress.py` green, and the whole worker
reaching anything. It fails *open*, which is why it gets a behavioural test
rather than a grep.

Paired throughout, like the API suite: the refusal is asserted beside a sync
that succeeds, because a refusal alone passes against a worker that can no
longer reach anything at all.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from dagster import build_op_context

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import anchor_worker.jobs.sync_configs as sync_configs  # noqa: E402
from anchor_worker.jobs.sync_configs import run_due_scheduled_syncs  # noqa: E402
from anchor_worker.resources import PlatformDatabase  # noqa: E402
from test_sync_configs import (  # noqa: E402,F401 (fixtures used by name)
    _connection_row,
    _create_connection,
    storage_root,
    workspace,
)

APP_DSN = os.environ["WORKER_DATABASE_URL"]
ADMIN_DSN = os.environ["TEST_ADMIN_DSN"]

SERVER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "api", "tests", "rest_fixture_server.py",
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def api_base() -> tuple[str, int]:
    if not os.path.exists(SERVER):  # pragma: no cover - environment guard
        pytest.skip(f"fixture server not found at {SERVER}")
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, SERVER, str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.25)
    else:  # pragma: no cover
        proc.terminate()
        pytest.skip("fixture API did not start")
    yield f"http://127.0.0.1:{port}", port
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="module", autouse=True)
def _fake_secrets():
    import unittest.mock as mock

    with mock.patch.object(sync_configs, "_read_secret", lambda arn: {}):
        yield


def _ctx():
    return build_op_context(resources={"platform_db": PlatformDatabase(dsn=APP_DSN)})


def _config(base: str) -> dict:
    return {"base_url": base, "resource_path": "/records", "allow_insecure_http": True,
            "auth_type": "none", "pagination": "none", "records_path": ""}


def _allow(connection_id: uuid.UUID, host: str, port: int | None, description: str = "") -> None:
    """A policy straight into the table, because what is under test is the
    worker reading it — the API route that writes one has its own tests."""
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO egress_policies (connection_id, host, port, description)"
            " VALUES (%s, %s, %s, %s)",
            (connection_id, host, port, description),
        )


def _scheduled(workspace: dict, base: str, next_run_at=None) -> uuid.UUID:
    return _create_connection(
        workspace, _config(base), mode="full",
        dataset_name=f"egress_{uuid.uuid4().hex[:6]}",
        source_type="rest", source_schema="", source_table="records",
        next_run_at=next_run_at,
    )


def test_a_scheduled_sync_with_no_policies_runs(workspace: dict, api_base) -> None:
    """**The presence half, and the state every existing source is in.**

    Decision 0013 §2: an empty allowlist means unrestricted. Without this, both
    refusals below pass against a worker whose scheduled syncs stopped working
    entirely — which is exactly the failure closed-by-default would have caused
    on the migration that added the table.
    """
    base, _ = api_base
    cid = _scheduled(workspace, base)
    assert run_due_scheduled_syncs(_ctx()) >= 1
    row = _connection_row(cid)
    assert row["status"] == "ok", row["last_error"]


def test_a_scheduled_sync_with_a_policy_for_its_own_host_runs(
    workspace: dict, api_base
) -> None:
    base, port = api_base
    cid = _scheduled(workspace, base)
    _allow(cid, "127.0.0.1", port, "the fixture API")
    assert run_due_scheduled_syncs(_ctx()) >= 1
    row = _connection_row(cid)
    assert row["status"] == "ok", row["last_error"]


def test_a_scheduled_sync_is_refused_by_a_policy_for_another_host(
    workspace: dict, api_base
) -> None:
    """The claim this file exists for: the worker reads the policies with the
    row and the connectors' guards find them in scope.

    The refusal is read off the **connection row**, because that is where
    somebody would look — a scheduled sync has no response for it to be in, and
    a control whose refusal is only in a log is one nobody will connect to the
    sync that stopped working.
    """
    base, _ = api_base
    cid = _scheduled(workspace, base)
    _allow(cid, "api.example.com", 443, "the vendor API")

    run_due_scheduled_syncs(_ctx())
    row = _connection_row(cid)
    assert row["status"] == "error"
    error = row["last_error"] or ""
    assert "not allowed to reach 127.0.0.1" in error, error
    # Decision 0013 §4: naming what *is* allowed is what ends the
    # investigation, and it is the half a refusal usually leaves out.
    assert "api.example.com:443" in error
    assert "the vendor API" in error
    # And the candidate is rescheduled rather than wedged: an egress refusal is
    # a configuration answer, and the sync should run the moment somebody fixes
    # the policy.
    assert row["sync_next_run_at"] is not None


def test_a_refused_sync_does_not_take_the_other_candidates_down(
    workspace: dict, api_base
) -> None:
    """One connection's policies are one connection's.

    `restricted_to` is a `contextvars` scope entered per candidate, and a leak
    would mean every source later in the same run inheriting the refused one's
    allowlist — the failure that stops a hundred syncs because somebody
    restricted one.

    **The order is pinned rather than hoped for.** `list_due_scheduled_syncs`
    orders by `sync_next_run_at NULLS FIRST`, and two candidates created the
    usual way both have NULL, which leaves the order unspecified. If the
    unrestricted one ran first, a leak would be invisible and this test would
    pass for the wrong reason — §262's lesson, that a test can walk the right
    path and still be blind.
    """
    base, _ = api_base
    earlier = datetime(2020, 1, 1, tzinfo=timezone.utc)
    refused = _scheduled(workspace, base, next_run_at=earlier)
    _allow(refused, "api.example.com", 443)
    allowed = _scheduled(workspace, base, next_run_at=earlier + timedelta(minutes=1))

    run_due_scheduled_syncs(_ctx())
    assert _connection_row(refused)["status"] == "error"
    assert _connection_row(allowed)["status"] == "ok", _connection_row(allowed)["last_error"]
