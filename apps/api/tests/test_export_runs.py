"""Exports as rows, and as real writes to a real database (§265).

`test_exports.py` is what a configuration *means*; this is whether an export
actually moves data, and whether the two modes differ in the one way p.195 says
they do.

**Against a real Postgres**, for `test_connections.py`'s reason in reverse: the
sync tests use the local server as a customer's source system, and these use it
as a customer's *destination*. A mocked connector would test the mock's shape.

**The mode tests run twice**, and that is the whole point. `mirror` and `full`
are indistinguishable on a first run into an empty table — both leave the
dataset's rows there. p.195's difference only appears on the second run, and a
suite that ran each once would pass against an implementation that had them the
wrong way round.

`data-connection` pages are `p.N`.
"""
from __future__ import annotations

import io
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

#: A database of its own standing in for the customer's warehouse, with a login
#: role of its own — because "the credentials can truncate this table" is one of
#: p.197's real constraints and it cannot be tested as the owner of everything.
DEST_DB = "export_dest_test"
DEST_USER = "export_dest_user"
DEST_PASSWORD = "d3st-Secret-77"


@pytest.fixture(scope="module")
def destination() -> dict[str, object]:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {DEST_DB}")
        conn.execute(f"DROP ROLE IF EXISTS {DEST_USER}")
        conn.execute(f"CREATE ROLE {DEST_USER} LOGIN PASSWORD '{DEST_PASSWORD}'")
        conn.execute(f"GRANT {DEST_USER} TO platform")
        conn.execute(f"CREATE DATABASE {DEST_DB} OWNER {DEST_USER}")
    yield {"host": "localhost", "port": 5432, "database": DEST_DB, "user": DEST_USER}
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {DEST_DB}")
        conn.execute(f"DROP ROLE IF EXISTS {DEST_USER}")


def dest_dsn() -> str:
    return for_database(ADMIN_DSN, DEST_DB)


def make_table(name: str, columns: str) -> None:
    with psycopg.connect(dest_dsn(), autocommit=True) as conn:
        conn.execute(f"DROP TABLE IF EXISTS public.{name}")
        conn.execute(f"CREATE TABLE public.{name} ({columns})")
        conn.execute(f"GRANT ALL ON public.{name} TO {DEST_USER}")


def rows_in(name: str) -> list[tuple]:
    with psycopg.connect(dest_dsn(), autocommit=True) as conn:
        return conn.execute(f"SELECT * FROM public.{name} ORDER BY 1").fetchall()


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def storage_root(tmp_path_factory: pytest.TempPathFactory) -> str:
    return str(tmp_path_factory.mktemp("export-storage"))


@pytest.fixture(scope="module")
def client(storage_root: str) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    conn_routes.configure_secrets_gateway(InMemorySecretsGateway())
    ds_routes.configure_storage_gateway(LocalStorageGateway(storage_root))
    with TestClient(create_app(), raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def base(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


# ---- the pieces an export needs ---------------------------------------------------
CSV = "id,email\n1,ada@example.com\n2,grace@example.com\n"


def upload(client: TestClient, fx: Fixture, csv: str) -> str:
    """A dataset from a CSV, which is the shortest path to a real parquet."""
    r = client.post(
        f"{base(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"orders_{uuid.uuid4().hex[:6]}"},
        files={"file": ("orders.csv", io.BytesIO(csv.encode()), "text/csv")},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def versioned(client: TestClient, fx: Fixture, csv: str = CSV) -> tuple[str, str]:
    """A dataset that can gain versions, and the model that gives it them.

    **An upload only ever makes version 1** — there is no route that adds a
    version to an uploaded dataset, because in this platform versions come from
    the things that *produce* data: syncs, models and actions. A model output is
    the one of those three reachable in two HTTP calls, so p.192's skip gets
    something real to stop skipping rather than a row written by a fixture.

    Returns (model_id, output_dataset_id).
    """
    source = upload(client, fx, csv)
    r = client.post(
        f"{base(fx)}/models", headers=hdr(fx.editor_sub),
        json={"name": f"Copy {uuid.uuid4().hex[:6]}",
              "code": "SELECT * FROM orders",
              "inputs": [{"dataset_id": source, "input_alias": "orders"}]},
    )
    assert r.status_code == 201, r.text
    model_id = r.json()["id"]
    run = client.post(f"{base(fx)}/models/{model_id}/run", headers=hdr(fx.editor_sub))
    assert run.status_code == 200, run.text
    assert run.json()["output_dataset"]["current_version"] == 1
    return model_id, run.json()["output_dataset"]["id"]


def revise(client: TestClient, fx: Fixture, model_id: str) -> int:
    """Another version of the model's output. The rows are the same; the
    *version number* is what `should_skip` compares, so this is the change that
    matters and making the content differ too would test something else."""
    r = client.post(f"{base(fx)}/models/{model_id}/run", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    return int(r.json()["output_dataset"]["current_version"])


def destination_connection(
    client: TestClient, fx: Fixture, destination: dict, *, enable: bool = True
) -> str:
    r = client.post(
        f"{base(fx)}/connections", headers=hdr(fx.editor_sub),
        json={"name": f"Warehouse {uuid.uuid4().hex[:6]}", "source_type": "postgres",
              "scope": "project", "config": destination,
              "secret": {"password": DEST_PASSWORD}},
    )
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert r.json()["exports_enabled"] is False, "p.202: off until turned on"
    if enable:
        turn_on(client, fx, cid)
    return cid


def turn_on(client: TestClient, fx: Fixture, cid: str, enabled: bool = True):
    return client.put(
        f"{base(fx)}/connections/{cid}/exports-enabled",
        headers=hdr(fx.admin_sub), json={"enabled": enabled},
    )


def make_export(client: TestClient, fx: Fixture, cid: str, did: str, **over):
    payload = {"connection_id": cid, "dataset_id": did,
               "name": f"Export {uuid.uuid4().hex[:6]}", "mode": "mirror",
               "destination": {"schema": "public", "table": "orders"}}
    payload.update(over)
    return client.post(f"{base(fx)}/exports", headers=hdr(fx.editor_sub), json=payload)


def run(client: TestClient, fx: Fixture, export_id: str) -> dict:
    r = client.post(f"{base(fx)}/exports/{export_id}/run", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    return r.json()




# ---- p.202's switch ----------------------------------------------------------------
def test_exports_are_off_until_somebody_turns_them_on(
    client: TestClient, fx: Fixture, destination: dict
) -> None:
    """p.202: "you must enable exports in the Connection settings section of
    the source to which you are exporting."

    **The default is the control.** Without it any project editor who can make
    a connection can move every row they can read out of the platform, and
    nothing anywhere says so.
    """
    cid = destination_connection(client, fx, destination, enable=False)
    did = upload(client, fx, CSV)
    r = make_export(client, fx, cid, did)
    assert r.status_code == 409, r.text
    assert "not enabled" in r.json()["detail"]
    assert "workspace admin" in r.json()["detail"]


def test_turning_exports_on_is_a_workspace_admins_decision(
    client: TestClient, fx: Fixture, destination: dict
) -> None:
    """p.202 gives this to the `Information Security Officer` role. This
    platform has none; workspace admin is the nearest and decision 0014 §4
    records it as a narrowing rather than an equivalent."""
    cid = destination_connection(client, fx, destination, enable=False)
    assert client.put(
        f"{base(fx)}/connections/{cid}/exports-enabled",
        headers=hdr(fx.editor_sub), json={"enabled": True},
    ).status_code == 403
    assert turn_on(client, fx, cid).status_code == 200


def test_turning_exports_off_again_stops_an_export_that_already_exists(
    client: TestClient, fx: Fixture, destination: dict
) -> None:
    """**The switch works in both directions, and the second is the one that
    matters.** A control that only applied to exports nobody had made yet would
    be a control that does nothing about the ones somebody is worried about."""
    make_table("orders", "id bigint, email text")
    cid = destination_connection(client, fx, destination)
    did = upload(client, fx, CSV)
    export_id = make_export(client, fx, cid, did).json()["id"]
    assert run(client, fx, export_id)["status"] == "succeeded"

    turn_on(client, fx, cid, enabled=False)
    r = client.post(f"{base(fx)}/exports/{export_id}/run", headers=hdr(fx.editor_sub))
    assert r.status_code == 409
    assert "not enabled" in r.json()["detail"]


# ---- the two modes, each run twice --------------------------------------------------
def test_mirror_leaves_the_table_equal_to_the_dataset_run_twice(
    client: TestClient, fx: Fixture, destination: dict
) -> None:
    """p.195: "truncate (drop) the target table, and then export a snapshot of
    the full current dataset view… the external table always mirroring the
    Foundry dataset."

    Twice, and the second run is the assertion: a first run into an empty table
    is identical under both modes.
    """
    make_table("orders", "id bigint, email text")
    cid = destination_connection(client, fx, destination)
    model_id, did = versioned(client, fx)
    export_id = make_export(client, fx, cid, did, mode="mirror").json()["id"]

    first = run(client, fx, export_id)
    assert first["status"] == "succeeded" and first["rows_written"] == 2
    assert len(rows_in("orders")) == 2

    revise(client, fx, model_id)
    second = run(client, fx, export_id)
    assert second["status"] == "succeeded"
    assert second["rows_written"] == 2
    # **Two, not four**, and that single number is the whole difference between
    # the two modes. `full` on the same input leaves four (below).
    assert len(rows_in("orders")) == 2, "mirror replaces rather than appends"


def test_full_leaves_twice_the_rows_because_p195_says_so(
    client: TestClient, fx: Fixture, destination: dict
) -> None:
    """p.195: "Note: This option will almost always result in duplicates in the
    external table."

    **The duplicates are the feature**, and a `full` that quietly de-duplicated
    would be a fifth mode nobody chose. p.195's stated use is an external system
    that "consume[s] and remove[s] rows after each run".
    """
    make_table("orders_full", "id bigint, email text")
    cid = destination_connection(client, fx, destination)
    did = upload(client, fx, CSV)
    export_id = make_export(
        client, fx, cid, did, mode="full",
        destination={"schema": "public", "table": "orders_full"},
    ).json()["id"]

    assert run(client, fx, export_id)["rows_written"] == 2
    assert len(rows_in("orders_full")) == 2
    assert run(client, fx, export_id)["rows_written"] == 2
    assert len(rows_in("orders_full")) == 4


# ---- p.192's nothing-to-export --------------------------------------------------------
def test_an_unchanged_dataset_is_a_success_that_writes_nothing(
    client: TestClient, fx: Fixture, destination: dict
) -> None:
    """p.192: "From June 2025 onward, exports with no new files or rows to be
    exported will be marked as `success`.\""""
    make_table("orders_skip", "id bigint, email text")
    cid = destination_connection(client, fx, destination)
    did = upload(client, fx, CSV)
    export_id = make_export(
        client, fx, cid, did, mode="mirror",
        destination={"schema": "public", "table": "orders_skip"},
    ).json()["id"]

    assert run(client, fx, export_id)["skipped"] is False
    second = run(client, fx, export_id)
    assert second["status"] == "succeeded"
    assert second["skipped"] is True
    assert second["rows_written"] == 0


def test_a_changed_dataset_is_not_skipped(
    client: TestClient, fx: Fixture, destination: dict
) -> None:
    """**The presence half of the test above**, and it is not a formality:
    without it, that one passes against an export that never writes at all."""
    make_table("orders_change", "id bigint, email text")
    cid = destination_connection(client, fx, destination)
    model_id, did = versioned(client, fx)
    export_id = make_export(
        client, fx, cid, did, mode="mirror",
        destination={"schema": "public", "table": "orders_change"},
    ).json()["id"]

    run(client, fx, export_id)
    assert run(client, fx, export_id)["skipped"] is True
    revise(client, fx, model_id)
    third = run(client, fx, export_id)
    assert third["skipped"] is False
    assert third["rows_written"] == 2


def test_full_writes_again_on_an_unchanged_dataset(
    client: TestClient, fx: Fixture, destination: dict
) -> None:
    """§3 of decision 0014, and the one a single skip-test would erase: `full`
    exists for a destination that empties itself, so there is always something
    new to send."""
    make_table("orders_full_skip", "id bigint, email text")
    cid = destination_connection(client, fx, destination)
    did = upload(client, fx, CSV)
    export_id = make_export(
        client, fx, cid, did, mode="full",
        destination={"schema": "public", "table": "orders_full_skip"},
    ).json()["id"]

    assert run(client, fx, export_id)["skipped"] is False
    assert run(client, fx, export_id)["skipped"] is False


# ---- p.197's run-time refusals ---------------------------------------------------------
def test_a_column_the_destination_lacks_is_refused_before_any_row_is_written(
    client: TestClient, fx: Fixture, destination: dict
) -> None:
    """p.197: "The dataset you export from Foundry must have a 1:1 match with
    the external source, including exact column names (case-sensitive)."

    **Before any row**, which is the half Foundry leaves to run time: failing at
    row 40,000 of a table export names a driver error rather than a column.
    """
    make_table("orders_narrow", "id bigint")
    cid = destination_connection(client, fx, destination)
    did = upload(client, fx, CSV)
    export_id = make_export(
        client, fx, cid, did,
        destination={"schema": "public", "table": "orders_narrow"},
    ).json()["id"]

    outcome = run(client, fx, export_id)
    assert outcome["status"] == "failed"
    assert "email" in outcome["error"]
    assert "p.197" in outcome["error"]
    assert rows_in("orders_narrow") == [], "nothing was written"


def test_a_table_that_does_not_exist_is_a_sentence_not_a_driver_error(
    client: TestClient, fx: Fixture, destination: dict
) -> None:
    """p.197: "The destination table must already exist in the source system;
    it will not be automatically created by Foundry.\""""
    cid = destination_connection(client, fx, destination)
    did = upload(client, fx, CSV)
    export_id = make_export(
        client, fx, cid, did,
        destination={"schema": "public", "table": "no_such_table"},
    ).json()["id"]

    outcome = run(client, fx, export_id)
    assert outcome["status"] == "failed"
    assert "does not exist" in outcome["error"]
    assert "p.197" in outcome["error"]


def test_a_dataset_with_no_versions_is_refused_rather_than_run(
    client: TestClient, fx: Fixture, destination: dict
) -> None:
    """Nothing to export is different from nothing new to export: p.192's
    success is about a version already sent, and this is about there being no
    version at all.

    **The row is made directly, because no route can make it.** Every path that
    creates a dataset here — upload, model output, sync, action — writes version
    1 with it, so `current_version = 0` is a state the API cannot produce today.
    The guard is not decoration for that reason: db 0069 constrains
    `export_runs.dataset_version` to be `> 0`, so without the 409 this run would
    reach a constraint violation and surface as a 500. A guard whose absence is
    a crash is worth having even when only the schema can currently trip it,
    and the honest way to test one is to build the state the only way it can be
    built — and to say, here, that this is what that means.
    """
    cid = destination_connection(client, fx, destination)
    dataset_id = uuid.uuid4()
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO datasets (id, project_id, workspace_id, name, slug,
                                  origin, s3_location, current_version)
            VALUES (%s, %s, %s, %s, %s, 'upload', %s, 0)
            """,
            (dataset_id, fx.project, fx.workspace, f"empty {dataset_id.hex[:6]}",
             f"empty-{dataset_id.hex[:6]}", f"datasets/{dataset_id}/"),
        )
    export_id = make_export(client, fx, cid, str(dataset_id)).json()["id"]
    refused = client.post(f"{base(fx)}/exports/{export_id}/run", headers=hdr(fx.editor_sub))
    assert refused.status_code == 409
    assert "nothing to export" in refused.json()["detail"]


# ---- the history (p.206) ----------------------------------------------------------------
def test_every_run_is_in_the_history_including_the_one_that_did_nothing(
    client: TestClient, fx: Fixture, destination: dict
) -> None:
    """p.206: "the History view of an export shows the history of the jobs
    associated with it."

    **Including the skip**, because "nothing happened" and "nothing ran" are
    exactly the two answers somebody reading a schedule's history is trying to
    tell apart.
    """
    make_table("orders_hist", "id bigint, email text")
    cid = destination_connection(client, fx, destination)
    did = upload(client, fx, CSV)
    export_id = make_export(
        client, fx, cid, did,
        destination={"schema": "public", "table": "orders_hist"},
    ).json()["id"]

    run(client, fx, export_id)
    run(client, fx, export_id)
    r = client.get(f"{base(fx)}/exports/{export_id}/runs", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert [entry["skipped"] for entry in body["runs"]] == [True, False]


def test_a_failed_run_does_not_move_the_mark(
    client: TestClient, fx: Fixture, destination: dict
) -> None:
    """**A retry has to do the work the failure did not.** If a failure
    advanced `last_version`, the next run would find nothing new and report
    success — which is the worst possible outcome: a broken export that looks
    fixed."""
    make_table("orders_retry", "id bigint")
    cid = destination_connection(client, fx, destination)
    did = upload(client, fx, CSV)
    export_id = make_export(
        client, fx, cid, did,
        destination={"schema": "public", "table": "orders_retry"},
    ).json()["id"]

    assert run(client, fx, export_id)["status"] == "failed"
    # Widen the table so the retry can work, and check the retry *runs* rather
    # than skipping past the version the failure claimed.
    with psycopg.connect(dest_dsn(), autocommit=True) as conn:
        conn.execute("ALTER TABLE public.orders_retry ADD COLUMN email text")
    retried = run(client, fx, export_id)
    assert retried["status"] == "succeeded"
    assert retried["skipped"] is False
    assert len(rows_in("orders_retry")) == 2


# ---- the fifth outbound path (§263, decision 0013 §3) ---------------------------------------
def test_an_export_is_governed_by_the_sources_egress_policies(
    client: TestClient, fx: Fixture, destination: dict
) -> None:
    """**Decision 0013's table gained a row with this unit, and this is the
    test that makes the row true rather than argued.**

    An export writes through `PostgresConnector._conninfo`, which is where §263
    put the guard — so an export was governed the moment it existed, with no
    line added. That is exactly the reasoning decision 0013 §3 exists to
    distrust: "the guard is in a shared function" is not "every path reaches
    it", and two of its four rows were written because that argument had been
    made and was wrong.

    Paired, like every refusal §263 wrote: the allowed call comes first, so a
    refusal cannot pass against an export that could never reach anything.
    """
    make_table("orders_egress", "id bigint, email text")
    cid = destination_connection(client, fx, destination)
    model_id, did = versioned(client, fx)
    export_id = make_export(
        client, fx, cid, did,
        destination={"schema": "public", "table": "orders_egress"},
    ).json()["id"]

    # Allowed: a policy naming the host this source actually dials.
    assert client.post(
        f"{base(fx)}/connections/{cid}/egress-policies", headers=hdr(fx.editor_sub),
        json={"host": "localhost", "port": 5432},
    ).status_code == 201
    assert run(client, fx, export_id)["status"] == "succeeded"

    # Refused: a second export on a source scoped somewhere else entirely.
    other = destination_connection(client, fx, destination)
    assert client.post(
        f"{base(fx)}/connections/{other}/egress-policies", headers=hdr(fx.editor_sub),
        json={"host": "warehouse.example.com", "port": 5432,
              "description": "the analytics warehouse"},
    ).status_code == 201
    blocked_id = make_export(
        client, fx, other, did,
        destination={"schema": "public", "table": "orders_egress"},
    ).json()["id"]

    outcome = run(client, fx, blocked_id)
    assert outcome["status"] == "failed"
    assert "not allowed to reach localhost:5432" in outcome["error"]
    # Decision 0013 §4: the refusal names what *is* allowed, so the
    # investigation ends here rather than at DNS and a firewall.
    assert "warehouse.example.com:5432" in outcome["error"]
    # **In its own words, not wrapped as a generic failure.** Decision 0013 §4:
    # a refused destination is not a failure to reach one, because nothing was
    # attempted - and if the two read the same, the distinction the whole
    # section argues for is one nobody can act on.
    assert not outcome["error"].startswith("the export failed")


# ---- roles and isolation ------------------------------------------------------------------
def test_a_viewer_may_read_and_may_not_run(
    client: TestClient, fx: Fixture, destination: dict
) -> None:
    """Running reaches out of the platform and writes to somebody else's
    database — the same reason `POST /connections/{id}/test` sits at editor."""
    make_table("orders_role", "id bigint, email text")
    cid = destination_connection(client, fx, destination)
    did = upload(client, fx, CSV)
    export_id = make_export(
        client, fx, cid, did,
        destination={"schema": "public", "table": "orders_role"},
    ).json()["id"]

    assert client.get(f"{base(fx)}/exports", headers=hdr(fx.viewer_sub)).status_code == 200
    assert client.post(
        f"{base(fx)}/exports/{export_id}/run", headers=hdr(fx.viewer_sub)
    ).status_code == 403


def test_a_stranger_sees_nothing(client: TestClient, fx: Fixture) -> None:
    assert client.get(
        f"{base(fx)}/exports", headers=hdr(fx.outsider_sub)
    ).status_code in (403, 404)


def test_two_exports_in_one_project_may_not_share_a_name(
    client: TestClient, fx: Fixture, destination: dict
) -> None:
    """db 0069's unique constraint refuses it too; this turns that into a
    sentence rather than a 500 quoting a constraint name — the fix §259 made
    for webhooks and §263 for egress policies, needed a third time."""
    cid = destination_connection(client, fx, destination)
    _, did = versioned(client, fx)
    name = f"Nightly {uuid.uuid4().hex[:6]}"
    assert make_export(client, fx, cid, did, name=name).status_code == 201
    clash = make_export(client, fx, cid, did, name=name)
    assert clash.status_code == 409
    assert name in clash.json()["detail"]


def test_an_export_in_another_project_is_a_404(
    client: TestClient, fx: Fixture, destination: dict
) -> None:
    """**A second project, because one project cannot see this rule.**

    `export_store.get` filters on `project_id` as well as id, and RLS alone
    does not cover it: both projects here are in the same workspace and this
    caller can read both, so the *store's* filter is the only thing keeping an
    export addressable from the project it belongs to. §257's tell — a suite
    whose fixtures all sit on one side of a rule cannot see the rule — and this
    suite had exactly one project until now.
    """
    cid = destination_connection(client, fx, destination)
    _, did = versioned(client, fx)
    export_id = make_export(client, fx, cid, did).json()["id"]

    other = client.post(
        f"/api/workspaces/{fx.workspace}/projects", headers=hdr(fx.admin_sub),
        json={"name": f"Elsewhere {uuid.uuid4().hex[:6]}"},
    )
    assert other.status_code == 201, other.text
    elsewhere = other.json()["id"]

    r = client.get(
        f"/api/workspaces/{fx.workspace}/projects/{elsewhere}/exports/{export_id}",
        headers=hdr(fx.admin_sub),
    )
    assert r.status_code == 404
    # The presence half: the same export, asked for from its own project.
    assert client.get(
        f"{base(fx)}/exports/{export_id}", headers=hdr(fx.admin_sub)
    ).status_code == 200


def test_a_version_whose_bytes_are_unaddressable_says_so(
    client: TestClient, fx: Fixture, destination: dict
) -> None:
    """A version row with no recorded file key: its metadata is true and its
    bytes are not addressable, which `routes/datasets.py` already treats as a
    state rather than a bug.

    **Built directly, like the no-versions case above**, because every writing
    path records a key. What is asserted is the *sentence*: without the guard
    the run still fails, but with a message from inside DuckDB about a path of
    `None` — which tells whoever reads the history nothing about what to do.
    """
    make_table("orders_nofile", "id bigint, email text")
    cid = destination_connection(client, fx, destination)
    _, did = versioned(client, fx)
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "UPDATE dataset_versions SET s3_manifest_key = NULL"
            " WHERE dataset_id = %s AND version_number = 1",
            (did,),
        )
    export_id = make_export(
        client, fx, cid, did,
        destination={"schema": "public", "table": "orders_nofile"},
    ).json()["id"]

    outcome = run(client, fx, export_id)
    assert outcome["status"] == "failed"
    assert "no stored file" in outcome["error"]


def test_the_columns_written_come_from_the_file_not_the_stored_schema(
    client: TestClient, fx: Fixture, destination: dict
) -> None:
    """**Postgres `COPY` maps by position, so this is a silent-corruption
    guard.**

    `COPY t (a, b) FROM STDIN ... HEADER true` skips the header line and writes
    values by the position of the column list. The dataset's stored
    `table_schema` and the CSV written from its parquet agree today, and if
    they ever disagreed on *order* every value would land in the wrong column
    and the run would report success.

    The two are forced apart here — the stored schema is reversed while the
    parquet is untouched — which is the only way to observe which one the code
    reads. Reversed rather than renamed, because a rename would fail the p.197
    column check and never reach the write.
    """
    make_table("orders_order", "id bigint, email text")
    cid = destination_connection(client, fx, destination)
    _, did = versioned(client, fx)
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            """
            UPDATE datasets
               SET table_schema = (
                   SELECT jsonb_agg(entry ORDER BY ordinality DESC)
                     FROM jsonb_array_elements(table_schema) WITH ORDINALITY AS t(entry, ordinality)
               )
             WHERE id = %s
            """,
            (did,),
        )
    export_id = make_export(
        client, fx, cid, did,
        destination={"schema": "public", "table": "orders_order"},
    ).json()["id"]

    assert run(client, fx, export_id)["status"] == "succeeded"
    # id is a bigint and email is text: had the reversed list been used, the
    # emails would have been written into `id` and the insert would have failed
    # or the values would be swapped. They are not.
    assert rows_in("orders_order") == [(1, "ada@example.com"), (2, "grace@example.com")]


def test_a_source_an_export_writes_to_cannot_be_deleted_out_from_under_it(
    client: TestClient, fx: Fixture, destination: dict
) -> None:
    """db 0069's `ON DELETE RESTRICT`, turned into a sentence rather than a 500
    quoting a constraint — the fix §259 made for webhooks, needed again for the
    same reason one table over."""
    cid = destination_connection(client, fx, destination)
    did = upload(client, fx, CSV)
    made = make_export(client, fx, cid, did).json()
    r = client.delete(f"{base(fx)}/connections/{cid}", headers=hdr(fx.editor_sub))
    assert r.status_code == 409
    assert made["name"] in r.json()["detail"]
    assert "export" in r.json()["detail"]
