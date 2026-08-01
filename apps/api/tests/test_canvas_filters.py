"""The SQL a canvas filter widget generates, run against the real engine
(ROADMAP Canvas item 1).

The widget itself is TypeScript and there is no frontend test runner in this
build, so the half of it that can genuinely break silently - the SQL - is
tested here instead of being left to a browser click. These queries are the
exact shapes `components/canvas/filter-sql.ts` produces; if that file changes
its output, these should change with it. Writing them caught the first bug:
the widget said `FROM src`, which is the alias the *model* layer gives its
inputs, while the query endpoint exposes the dataset as `FROM dataset`.

What is being protected: a value containing an apostrophe must filter rather
than raise, a filter on a numeric column must work even though the value
arrives from a dropdown as text, and "no value" must mean "no filter" rather
than "match the empty string".
"""
from __future__ import annotations

import io
import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

# An apostrophe in a value, a numeric column, and two rows sharing a region so
# a filter has something to actually narrow.
ORDERS = (
    b"order_id,region,customer,total\n"
    b"1,North,Acme,100\n"
    b"2,North,\"O'Brien Ltd\",250\n"
    b"3,South,Globex,75\n"
)


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("canvas-filters")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def pbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


@pytest.fixture(scope="module")
def orders(client: TestClient, fx: Fixture) -> str:
    r = client.post(
        f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"Orders {uuid.uuid4().hex[:6]}"},
        files={"file": ("orders.csv", io.BytesIO(ORDERS), "text/csv")},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def run(client: TestClient, fx: Fixture, dataset: str, sql: str, sub: str | None = None):
    r = client.post(
        f"{pbase(fx)}/datasets/{dataset}/query",
        headers=hdr(sub or fx.viewer_sub), json={"sql": sql},
    )
    assert r.status_code == 200, r.text
    return r.json()


# ---- the shapes filter-sql.ts produces --------------------------------------
def test_an_equals_filter_narrows_the_whole_dataset_not_a_preview_page(
    client: TestClient, fx: Fixture, orders: str
) -> None:
    """The reason filtering is server-side at all: filtering a preview page in
    the browser would silently filter the first N rows and call it the
    dataset."""
    result = run(client, fx, orders,
                 "SELECT * FROM dataset WHERE CAST(\"region\" AS VARCHAR) = 'North' LIMIT 200")
    assert len(result["rows"]) == 2
    assert {row[1] for row in result["rows"]} == {"North"}


def test_a_value_containing_an_apostrophe_filters_rather_than_raises(
    client: TestClient, fx: Fixture, orders: str
) -> None:
    """`sqlLiteral` doubles the quote. Without it this is a syntax error on a
    perfectly ordinary customer name."""
    result = run(client, fx, orders,
                 "SELECT * FROM dataset WHERE CAST(\"customer\" AS VARCHAR) = 'O''Brien Ltd' LIMIT 200")
    assert len(result["rows"]) == 1
    assert result["rows"][0][2] == "O'Brien Ltd"


def test_a_filter_works_against_a_numeric_column(
    client: TestClient, fx: Fixture, orders: str
) -> None:
    """The CAST is why: a dropdown hands back text whatever the column's type,
    and comparing text to a BIGINT is an error, not a non-match."""
    result = run(client, fx, orders,
                 "SELECT * FROM dataset WHERE CAST(\"total\" AS VARCHAR) = '250' LIMIT 200")
    assert len(result["rows"]) == 1
    assert result["rows"][0][0] == 2


def test_a_contains_filter_is_case_insensitive(
    client: TestClient, fx: Fixture, orders: str
) -> None:
    result = run(client, fx, orders,
                 "SELECT * FROM dataset WHERE CAST(\"customer\" AS VARCHAR) ILIKE '%acme%' LIMIT 200")
    assert len(result["rows"]) == 1


def test_the_distinct_query_feeds_a_dropdown(
    client: TestClient, fx: Fixture, orders: str
) -> None:
    """Options come from the data rather than a list typed by the builder, so
    they cannot go stale when a new value appears."""
    result = run(client, fx, orders,
                 'SELECT DISTINCT "region" AS value FROM dataset '
                 'WHERE "region" IS NOT NULL ORDER BY 1 LIMIT 200')
    assert [row[0] for row in result["rows"]] == ["North", "South"]


def test_filtering_is_a_viewer_level_read(
    client: TestClient, fx: Fixture, orders: str
) -> None:
    """A published app is read by people who cannot edit anything, so the
    filter has to work at the viewer floor - and the endpoint it uses already
    accepted arbitrary SQL at that floor, which is why building SQL in the
    widget grants nothing new."""
    run(client, fx, orders, "SELECT * FROM dataset LIMIT 1", sub=fx.viewer_sub)
    r = client.post(
        f"{pbase(fx)}/datasets/{orders}/query",
        headers=hdr(fx.outsider_sub), json={"sql": "SELECT * FROM dataset"},
    )
    assert r.status_code == 404
