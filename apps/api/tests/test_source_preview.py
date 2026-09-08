"""Source preview — a sample of a system this platform does not own yet
(`data-connection` p.142-143; decision 0015; §268).

`test_connections.py` covers `discover`, which reads a *catalogue*. This reads
**rows**, and that difference is the whole file: a preview returns data no
platform permission covers, because the data is not in the platform.

p.18 is why the feature exists in the shape it does — "Exploration is most
commonly used to check that a connection is working as intended and that the
correct permissions and credentials are being used to connect" — so the
credential-refusal tests here are the feature working, not its error path.

Against a real Postgres acting as the customer's system, for the reason
`test_connections.py` gives: a preview whose driver call is patched is a test
of the patch.

`data-connection` pages are `p.N`.
"""
from __future__ import annotations

import os
import sys
import urllib.parse
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, for_database, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import connections as conn_routes  # noqa: E402
from src.services import connectors  # noqa: E402
from src.services.secrets import InMemorySecretsGateway  # noqa: E402

ADMIN_DSN = os.environ["TEST_ADMIN_DSN"]
DB = urllib.parse.urlparse(ADMIN_DSN)

SOURCE_DB = "preview_source_test"
SOURCE_USER = "preview_source_user"
SOURCE_PASSWORD = "pr3view-Secret-9"

#: Rows the source holds, in the order they are inserted. The order is *not*
#: what the preview is asserted to return (decision 0015 §5) — what is asserted
#: is the set — but a fixture whose rows were identical could not tell a
#: preview that read the table from one that echoed a constant.
ROWS = [
    (1, "ada@example.com", 1200, None),
    (2, "grace@example.com", None, "note two"),
    (3, "katherine@example.com", 900, "note three"),
]


@pytest.fixture(scope="module")
def source_database() -> dict[str, object]:
    """The customer's system: its own database, its own login role.

    Its own role rather than the platform owner, because p.18's "the correct
    permissions … are being used" cannot be exercised as the owner of
    everything — `denied` below is a table this user genuinely cannot read.
    """
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {SOURCE_DB}")
        conn.execute(f"DROP ROLE IF EXISTS {SOURCE_USER}")
        conn.execute(f"CREATE ROLE {SOURCE_USER} LOGIN PASSWORD '{SOURCE_PASSWORD}'")
        conn.execute(f"GRANT {SOURCE_USER} TO platform")
        conn.execute(f"CREATE DATABASE {SOURCE_DB} OWNER {SOURCE_USER}")
    with psycopg.connect(for_database(ADMIN_DSN, SOURCE_DB), autocommit=True) as conn:
        conn.execute(
            """CREATE TABLE public.orders (
                   id bigint PRIMARY KEY,
                   customer_email text NOT NULL,
                   total_pence integer,
                   note text
               )"""
        )
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO public.orders (id, customer_email, total_pence, note)"
                " VALUES (%s, %s, %s, %s)",
                ROWS,
            )
        # Wider than the cap, to exercise decision 0015 §4's one inexactness.
        conn.execute("CREATE TABLE public.wide (id int, body text)")
        conn.execute(
            "INSERT INTO public.wide VALUES (1, %s)",
            ("x" * (connectors.PREVIEW_CELL + 40),),
        )
        # Exactly the cap, and one past it: `more` is the only field that can
        # be wrong in two directions, so both sides need a table.
        conn.execute("CREATE TABLE public.exactly_fifty (n int)")
        conn.execute(
            f"INSERT INTO public.exactly_fifty"
            f" SELECT generate_series(1, {connectors.PREVIEW_ROWS})"
        )
        conn.execute("CREATE TABLE public.one_too_many (n int)")
        conn.execute(
            f"INSERT INTO public.one_too_many"
            f" SELECT generate_series(1, {connectors.PREVIEW_ROWS + 1})"
        )
        conn.execute("CREATE TABLE public.empty_table (n int)")
        conn.execute(f"GRANT ALL ON ALL TABLES IN SCHEMA public TO {SOURCE_USER}")

        # A table the connection's user cannot read. Created and owned by the
        # platform role, with no grant — p.18's most common use of this screen.
        conn.execute("CREATE TABLE public.denied (secret text)")
        conn.execute("INSERT INTO public.denied VALUES ('do not show this')")
        conn.execute(f"REVOKE ALL ON public.denied FROM {SOURCE_USER}")
    yield {"host": "localhost", "port": 5432, "database": SOURCE_DB, "user": SOURCE_USER}
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {SOURCE_DB}")
        conn.execute(f"DROP ROLE IF EXISTS {SOURCE_USER}")


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client() -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    conn_routes.configure_secrets_gateway(InMemorySecretsGateway())
    with TestClient(create_app(), raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def base(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


@pytest.fixture(scope="module")
def source(client: TestClient, fx: Fixture, source_database: dict[str, object]) -> str:
    r = client.post(
        f"{base(fx)}/connections", headers=hdr(fx.editor_sub),
        json={"name": f"Preview source {uuid.uuid4().hex[:6]}", "source_type": "postgres",
              "scope": "project", "config": source_database,
              "secret": {"password": SOURCE_PASSWORD}},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def preview(client: TestClient, fx: Fixture, cid: str, table: str, schema: str = "public",
            sub: str | None = None):
    return client.post(
        f"{base(fx)}/connections/{cid}/preview",
        headers=hdr(sub or fx.editor_sub),
        json={"source_schema": schema, "source_table": table},
    )


# ---- p.143's sample ---------------------------------------------------------
def test_a_preview_returns_the_source_rows(client: TestClient, fx: Fixture, source: str) -> None:
    """p.142: "explore the source and the data it contains to preview syncs
    before they bring data into Foundry."

    The rows are compared as a *set*, because decision 0015 §5 says the sample
    is unordered — a test that asserted the order would be asserting something
    the implementation does not promise and would pass or fail by luck.
    """
    r = preview(client, fx, source, "orders")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["columns"] == ["id", "customer_email", "total_pence", "note"]
    emails = {row[1] for row in body["rows"]}
    assert emails == {"ada@example.com", "grace@example.com", "katherine@example.com"}
    assert body["more"] is False
    assert body["truncated_cells"] == 0


def test_a_null_stays_null_rather_than_becoming_a_blank(
    client: TestClient, fx: Fixture, source: str
) -> None:
    """Decision 0015 §4. "This column is empty" and "this column is missing"
    are the two answers somebody is reading a preview to tell apart, and a
    connector that stringified everything would erase the difference — `None`
    and `""` would both arrive as a blank cell."""
    r = preview(client, fx, source, "orders")
    by_id = {row[0]: row for row in r.json()["rows"]}
    assert by_id["1"][3] is None  # note
    assert by_id["2"][2] is None  # total_pence
    assert by_id["3"][3] == "note three"


def test_everything_else_is_a_string(client: TestClient, fx: Fixture, source: str) -> None:
    """Decision 0015 §4: a preview that preserved types would be a second type
    system that could disagree with `dataset_engine`'s, and the screen would
    show a number the sync would later store as text."""
    r = preview(client, fx, source, "orders")
    for row in r.json()["rows"]:
        assert row[0] in {"1", "2", "3"}
        assert all(cell is None or isinstance(cell, str) for cell in row)


# ---- the caps, both sides ---------------------------------------------------
def test_exactly_the_cap_is_not_reported_as_more(
    client: TestClient, fx: Fixture, source: str
) -> None:
    """The half a single `more` test would miss.

    A connector that asked for exactly `PREVIEW_ROWS` and inferred "there are
    more" from a full page would pass the test below and fail here — which is
    the inference decision 0015 §4 rejects, and the reason every connector asks
    for one row past the cap.
    """
    r = preview(client, fx, source, "exactly_fifty")
    body = r.json()
    assert len(body["rows"]) == connectors.PREVIEW_ROWS
    assert body["more"] is False


def test_one_row_past_the_cap_is_reported_as_more(
    client: TestClient, fx: Fixture, source: str
) -> None:
    r = preview(client, fx, source, "one_too_many")
    body = r.json()
    assert len(body["rows"]) == connectors.PREVIEW_ROWS
    assert body["more"] is True


def test_an_empty_table_previews_as_no_rows_rather_than_an_error(
    client: TestClient, fx: Fixture, source: str
) -> None:
    """An empty table is a legitimate answer and one somebody opens a preview
    to get — "the sync found nothing" and "the sync could not run" are the two
    outcomes this screen is meant to separate."""
    r = preview(client, fx, source, "empty_table")
    assert r.status_code == 200, r.text
    assert r.json() == {"columns": ["n"], "rows": [], "more": False, "truncated_cells": 0}


def test_a_long_value_is_shortened_and_counted(
    client: TestClient, fx: Fixture, source: str
) -> None:
    """Decision 0015 §4's one inexactness, and its mitigation.

    The count is what lets a screen say shortening happened at all — a
    truncated value and a real one ending in an ellipsis are indistinguishable
    on their own, which the decision states rather than hides.
    """
    r = preview(client, fx, source, "wide")
    body = r.json()
    assert body["truncated_cells"] == 1
    body_cell = body["rows"][0][1]
    assert len(body_cell) == connectors.PREVIEW_CELL + 1  # the cap plus the ellipsis
    assert body_cell.endswith("…")
    # The short cell beside it is untouched, so the cap is a cap and not a
    # blanket rewrite.
    assert body["rows"][0][0] == "1"


# ---- p.18: the permissions check that is the point --------------------------
def test_a_table_the_credential_cannot_read_says_so_and_names_it(
    client: TestClient, fx: Fixture, source: str
) -> None:
    """p.18: exploration is "most commonly used to check … that the correct
    permissions and credentials are being used to connect."

    So this sentence is the feature. It names the table rather than quoting a
    driver, and it must not leak the row it could not read.
    """
    r = preview(client, fx, source, "denied")
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert "cannot read public.denied" in detail
    assert "do not show this" not in r.text


def test_a_failed_read_does_not_mark_the_connection_broken(
    client: TestClient, fx: Fixture, source: str
) -> None:
    """**The pair the test above needs.**

    `test` and `discover` both record a failure on the connection, and copying
    that here would turn p.18's answer into its own false alarm: the source is
    reachable, the credential works, and one table is not readable. A source
    that went red every time somebody previewed the wrong table would be a
    status nobody could trust.
    """
    assert preview(client, fx, source, "orders").status_code == 200
    assert preview(client, fx, source, "denied").status_code == 422
    r = client.get(f"{base(fx)}/connections", headers=hdr(fx.editor_sub))
    row = next(c for c in r.json() if c["id"] == source)
    assert row["status"] == "ok"


def test_a_table_that_does_not_exist_is_a_sentence_not_a_500(
    client: TestClient, fx: Fixture, source: str
) -> None:
    r = preview(client, fx, source, "no_such_table")
    assert r.status_code == 422, r.text
    assert "does not exist" in r.json()["detail"]


# ---- decision 0015 §3: a preview of a table, never a query -------------------
@pytest.mark.parametrize(
    "table",
    [
        "orders; DROP TABLE orders",
        'orders" ; SELECT 1 --',
        "orders WHERE 1=1",
        "*",
    ],
)
def test_a_table_name_that_is_not_an_identifier_is_refused(
    client: TestClient, fx: Fixture, source: str, table: str
) -> None:
    """Decision 0015 §3. The endpoint takes a schema and a table and nothing
    that could shape the read, and `check_identifier` is what makes that true
    rather than intended — psycopg's `Identifier` would quote these safely, but
    a name that reaches the source at all is a name somebody chose."""
    r = preview(client, fx, source, table)
    assert r.status_code == 422, r.text
    assert "invalid identifier" in r.json()["detail"]


def test_a_schema_that_is_not_an_identifier_is_refused(
    client: TestClient, fx: Fixture, source: str
) -> None:
    """The schema is the argument the table's test cannot cover: they are
    checked on separate lines, and a guard removed from one of them leaves the
    other passing."""
    r = preview(client, fx, source, "orders", schema="public; DROP SCHEMA public")
    assert r.status_code == 422, r.text
    assert "invalid identifier" in r.json()["detail"]


# ---- decision 0015 §2: who may see it ---------------------------------------
def test_a_viewer_cannot_preview(client: TestClient, fx: Fixture, source: str) -> None:
    """Decision 0015 §2. A viewer can read the datasets a sync produced —
    those went through somebody's decision to bring them in. The source behind
    them did not."""
    assert preview(client, fx, source, "orders", sub=fx.viewer_sub).status_code == 403


def test_an_editor_can_preview(client: TestClient, fx: Fixture, source: str) -> None:
    """The pair, because a 403 alone passes against an endpoint that refuses
    everyone — which is what a copied `require_project_role("admin")` would
    have been."""
    assert preview(client, fx, source, "orders", sub=fx.editor_sub).status_code == 200


def test_an_outsider_gets_404(client: TestClient, fx: Fixture, source: str) -> None:
    assert preview(client, fx, source, "orders", sub=fx.outsider_sub).status_code == 404


# ---- what the audit log keeps ------------------------------------------------
def test_the_audit_records_the_table_and_never_the_rows(
    client: TestClient, fx: Fixture, source: str
) -> None:
    """An audit log that recorded what was previewed would be a second copy of
    the source's data, kept somewhere with different retention and no owner —
    and this platform's audit rows are readable by an organisation admin who
    may have no access to the project at all."""
    assert preview(client, fx, source, "orders").status_code == 200
    r = client.get("/api/org/audit?limit=200", headers=hdr(fx.admin_sub))
    assert r.status_code == 200, r.text
    previews = [e for e in r.json() if e["action"] == "connection.preview"]
    assert previews, "the preview was not audited"
    assert previews[0]["metadata"]["source_table"] == "orders"
    assert previews[0]["metadata"]["rows"] == len(ROWS)
    assert "ada@example.com" not in r.text
    assert SOURCE_PASSWORD not in r.text
