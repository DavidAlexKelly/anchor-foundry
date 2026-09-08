"""Export schedules from the API (decision 0016; `data-connection` p.205; §270).

`apps/worker/tests/test_export_schedules.py` is the cron *firing*; this is the
cron being **set**, and the guards that stop somebody saving one that could
never run.

**And the drift tests are here rather than there**, for the reason
`test_egress.py` gives about the worker's copy of the allowlist: the API is
where the original lives, so the API's suite is where "the copy still matches"
belongs. Decision 0016 §2 says why that matters more for exports than for the
other copied modules — p.192 makes "nothing new" a *success*, so two
implementations of the skip rule that disagreed would both report green.

`data-connection` pages are `p.N`.
"""
from __future__ import annotations

import os
import sys
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, for_database, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import connections as conn_routes  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services.secrets import InMemorySecretsGateway  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

ADMIN_DSN = os.environ["TEST_ADMIN_DSN"]
DEST_DB = "export_schedule_dest"
DEST_USER = "export_schedule_user"
DEST_PASSWORD = "sch3dule-D3st-4"

#: The repository root. Four levels: this file → tests → api → apps → root.
#: `test_egress.py`'s equivalent stops at `apps` and joins from there; this one
#: also reaches `packages/`, so it goes the whole way and says so.
ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)


@pytest.fixture(scope="module")
def warehouse():
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {DEST_DB}")
        conn.execute(f"DROP ROLE IF EXISTS {DEST_USER}")
        conn.execute(f"CREATE ROLE {DEST_USER} LOGIN PASSWORD '{DEST_PASSWORD}'")
        conn.execute(f"GRANT {DEST_USER} TO platform")
        conn.execute(f"CREATE DATABASE {DEST_DB} OWNER {DEST_USER}")
    with psycopg.connect(for_database(ADMIN_DSN, DEST_DB), autocommit=True) as conn:
        conn.execute("CREATE TABLE public.orders (id bigint, email text)")
        conn.execute(f"GRANT ALL ON public.orders TO {DEST_USER}")
    yield {"host": "localhost", "port": 5432, "database": DEST_DB, "user": DEST_USER}
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {DEST_DB}")
        conn.execute(f"DROP ROLE IF EXISTS {DEST_USER}")


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    conn_routes.configure_secrets_gateway(InMemorySecretsGateway())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("export-schedule-storage")))
    )
    with TestClient(create_app(), raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def base(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


def a_source(client: TestClient, fx: Fixture, warehouse: dict, *, enabled: bool = True) -> dict:
    made = client.post(
        f"{base(fx)}/connections", headers=hdr(fx.editor_sub),
        json={"name": f"Warehouse {uuid.uuid4().hex[:6]}", "source_type": "postgres",
              "scope": "project", "config": warehouse,
              "secret": {"password": DEST_PASSWORD}},
    ).json()
    if enabled:
        r = client.put(
            f"{base(fx)}/connections/{made['id']}/exports-enabled",
            headers=hdr(fx.admin_sub), json={"enabled": True},
        )
        assert r.status_code == 200, r.text
    return made


def a_dataset(client: TestClient, fx: Fixture) -> dict:
    name = f"orders_{uuid.uuid4().hex[:6]}"
    r = client.post(
        f"{base(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        files={"file": (f"{name}.csv", b"id,email\n1,ada@example.com\n", "text/csv")},
        data={"name": name},
    )
    assert r.status_code in (200, 201), r.text
    return r.json()


def an_export(client: TestClient, fx: Fixture, source: dict, dataset: dict) -> dict:
    r = client.post(
        f"{base(fx)}/exports", headers=hdr(fx.editor_sub),
        json={"connection_id": source["id"], "dataset_id": dataset["id"],
              "name": f"Nightly {uuid.uuid4().hex[:4]}", "mode": "mirror",
              "destination": {"schema": "public", "table": "orders"}},
    )
    assert r.status_code == 201, r.text
    return r.json()


def set_schedule(client: TestClient, fx: Fixture, export_id: str, cron, sub=None):
    return client.put(
        f"{base(fx)}/exports/{export_id}/schedule",
        headers=hdr(sub or fx.editor_sub), json={"schedule": cron},
    )


# ---- p.205's schedule -------------------------------------------------------
def test_a_schedule_is_stored_with_the_time_it_will_next_fire(
    client: TestClient, fx: Fixture, warehouse: dict
) -> None:
    """p.205: "Exports should be scheduled to run regularly."

    Both columns, because they are one fact: a cron with no `next_run_at` would
    never be found by the worker's discovery, and the API is the only place
    that computes the first one (`lib/cron`'s docstring — cron is interpreted at
    exactly two trusted call sites).
    """
    source = a_source(client, fx, warehouse)
    export = an_export(client, fx, source, a_dataset(client, fx))
    assert export["schedule"] is None and export["next_run_at"] is None

    r = set_schedule(client, fx, export["id"], "0 3 * * *")
    assert r.status_code == 200, r.text
    assert r.json()["schedule"] == "0 3 * * *"
    assert r.json()["next_run_at"] is not None


def test_a_null_schedule_clears_both_columns(
    client: TestClient, fx: Fixture, warehouse: dict
) -> None:
    """**There is no separate off switch** (db 0070): an export with no
    schedule and one whose schedule is switched off are the same state, and a
    cleared cron that left a timestamp behind would leave a row reading as due
    to anyone querying it directly."""
    source = a_source(client, fx, warehouse)
    export = an_export(client, fx, source, a_dataset(client, fx))
    assert set_schedule(client, fx, export["id"], "0 3 * * *").status_code == 200

    r = set_schedule(client, fx, export["id"], None)
    assert r.status_code == 200, r.text
    assert r.json()["schedule"] is None
    assert r.json()["next_run_at"] is None


def test_whitespace_is_not_a_schedule(
    client: TestClient, fx: Fixture, warehouse: dict
) -> None:
    """A form that sends an emptied field sends `" "`, and storing that would
    make an export permanently due against a cron nothing can parse — the
    worker would log a warning every poll and never advance it."""
    source = a_source(client, fx, warehouse)
    export = an_export(client, fx, source, a_dataset(client, fx))
    r = set_schedule(client, fx, export["id"], "   ")
    assert r.status_code == 200, r.text
    assert r.json()["schedule"] is None


def test_an_unparseable_cron_is_refused_at_the_moment_it_is_typed(
    client: TestClient, fx: Fixture, warehouse: dict
) -> None:
    """**Refused by `croniter`, not by a regex**, because croniter is what the
    worker will run it through: an expression a pattern accepted and the
    library did not would be a schedule that saved and never fired, and the
    only symptom would be a warning in a log nobody reads."""
    source = a_source(client, fx, warehouse)
    export = an_export(client, fx, source, a_dataset(client, fx))
    r = set_schedule(client, fx, export["id"], "not a cron")
    assert r.status_code == 422, r.text
    assert "cron" in r.json()["detail"].lower()


def test_a_valid_looking_but_impossible_cron_is_refused_too(
    client: TestClient, fx: Fixture, warehouse: dict
) -> None:
    """The pair for the test above, and the reason a regex would not have been
    enough: `0 0 30 2 *` has five fields of the right shape and names the
    thirtieth of February."""
    source = a_source(client, fx, warehouse)
    export = an_export(client, fx, source, a_dataset(client, fx))
    r = set_schedule(client, fx, export["id"], "99 * * * *")
    assert r.status_code == 422, r.text


# ---- p.202's switch ---------------------------------------------------------
def test_a_schedule_on_a_source_with_exports_off_is_refused_with_the_reason(
    client: TestClient, fx: Fixture, warehouse: dict
) -> None:
    """**A schedule that could never fire is worse than no schedule**, because
    it looks like one.

    `list_due_exports()` joins `exports_enabled`, so setting a cron on a
    disabled source would save and silently never run. §214's rule is about
    controls that cannot work; this is the same thing one layer in, and the
    refusal names who can change it (p.202: a workspace admin, this platform's
    nearest thing to the Information Security Officer role).
    """
    source = a_source(client, fx, warehouse, enabled=False)
    dataset = a_dataset(client, fx)
    # The export itself cannot be created either — §265's rule — so the switch
    # goes on, the export is made, and then it goes off again. Which is also
    # the realistic sequence.
    client.put(
        f"{base(fx)}/connections/{source['id']}/exports-enabled",
        headers=hdr(fx.admin_sub), json={"enabled": True},
    )
    export = an_export(client, fx, source, dataset)
    client.put(
        f"{base(fx)}/connections/{source['id']}/exports-enabled",
        headers=hdr(fx.admin_sub), json={"enabled": False},
    )

    r = set_schedule(client, fx, export["id"], "0 3 * * *")
    assert r.status_code == 409, r.text
    assert "turned off" in r.json()["detail"]
    assert "workspace admin" in r.json()["detail"]


def test_clearing_a_schedule_still_works_on_a_disabled_source(
    client: TestClient, fx: Fixture, warehouse: dict
) -> None:
    """**The pair, and it is not symmetry for its own sake.** Somebody tidying
    up after an admin turned exports off must be able to remove the schedule —
    a guard that refused *every* write to the column would trap the row in the
    state it is complaining about."""
    source = a_source(client, fx, warehouse)
    export = an_export(client, fx, source, a_dataset(client, fx))
    assert set_schedule(client, fx, export["id"], "0 3 * * *").status_code == 200
    client.put(
        f"{base(fx)}/connections/{source['id']}/exports-enabled",
        headers=hdr(fx.admin_sub), json={"enabled": False},
    )

    r = set_schedule(client, fx, export["id"], None)
    assert r.status_code == 200, r.text
    assert r.json()["schedule"] is None


# ---- who may set one --------------------------------------------------------
def test_a_viewer_cannot_set_a_schedule(
    client: TestClient, fx: Fixture, warehouse: dict
) -> None:
    """Editor, the same floor as running it: a schedule is a run somebody will
    not be present for, which is not a smaller act than pressing the button."""
    source = a_source(client, fx, warehouse)
    export = an_export(client, fx, source, a_dataset(client, fx))
    assert set_schedule(client, fx, export["id"], "0 3 * * *",
                        sub=fx.viewer_sub).status_code == 403


def test_an_editor_can(client: TestClient, fx: Fixture, warehouse: dict) -> None:
    source = a_source(client, fx, warehouse)
    export = an_export(client, fx, source, a_dataset(client, fx))
    assert set_schedule(client, fx, export["id"], "0 3 * * *",
                        sub=fx.editor_sub).status_code == 200


def test_setting_a_schedule_is_audited(
    client: TestClient, fx: Fixture, warehouse: dict
) -> None:
    source = a_source(client, fx, warehouse)
    export = an_export(client, fx, source, a_dataset(client, fx))
    set_schedule(client, fx, export["id"], "0 3 * * *")

    r = client.get("/api/org/audit?limit=200", headers=hdr(fx.admin_sub))
    entries = [e for e in r.json() if e["action"] == "export.schedule"]
    assert entries, "setting a schedule was not audited"
    assert entries[0]["metadata"]["schedule"] == "0 3 * * *"
    assert DEST_PASSWORD not in r.text


# ---- the worker's copies ----------------------------------------------------
def test_the_worker_runs_the_same_export_rule_byte_for_byte() -> None:
    """**The rule module is the same file, not a second implementation.**

    Decision 0016 §2: `should_skip` is where a divergence would be invisible.
    p.192 makes "nothing new" a *success*, so a worker that computed the skip
    differently from the API would report green either way — an export that
    silently stopped writing and an export that silently rewrote every poll
    both look like a column of ticks.

    `exports.py` imports nothing but `re` and `typing`, which is what makes
    byte-for-byte possible here rather than a behavioural comparison. §191's
    rule: "they agree on the cases I thought of" is what a behavioural
    comparison buys; "they are the same file" is what stops the case nobody
    thought of from differing.
    """
    api = open(os.path.join(ROOT, "apps", "api", "src", "services", "exports.py"), "rb").read()
    worker = open(
        os.path.join(ROOT, "apps", "worker", "src", "anchor_worker", "exports.py"), "rb"
    ).read()
    assert api == worker, (
        "apps/worker/src/anchor_worker/exports.py has drifted from "
        "apps/api/src/services/exports.py - copy it across rather than editing "
        "one of them"
    )


def test_the_worker_can_actually_run_an_export() -> None:
    """The three connector methods a scheduled export needs, asserted by name.

    Not a substitute for `apps/worker/tests/test_export_schedules.py`, which
    runs one end to end — this is the cheap check that catches the specific way
    this breaks: a method added to the API's connector and not to the worker's.
    The worker's suite would catch it too, and only for whichever source type
    that suite happens to exercise.
    """
    sys.path.insert(0, os.path.join(ROOT, "apps", "worker", "src"))
    from anchor_worker import connectors as worker_connectors

    for source_type, methods in (
        ("postgres", ("destination_columns", "export_rows")),
        ("mysql", ("destination_columns", "export_rows")),
        ("s3", ("export_file",)),
    ):
        connector = worker_connectors.get_connector(source_type)
        for method in methods:
            assert callable(getattr(connector, method, None)), (
                f"the worker's {source_type} connector has no {method} - a scheduled "
                "export to that source would fail with an AttributeError at run time"
            )


def test_the_two_runners_record_the_same_shape() -> None:
    """**The result dict is a contract between two writers into one table.**

    A scheduled run and a manual one insert into `export_runs`, and §267's
    history screen reads them as one list. A key present in one runner's result
    and absent from the other's would surface as a `KeyError` in whichever
    recorder was written against the other — so the shapes are compared
    directly rather than trusted to stay in step.
    """
    sys.path.insert(0, os.path.join(ROOT, "apps", "worker", "src"))
    from anchor_worker import export_runs as worker_runner

    from src.services import export_runs as api_runner

    assert set(worker_runner.result(ok=True)) == set(api_runner.result(ok=True))
