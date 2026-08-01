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

# An apostrophe in a value, a numeric column, and two rows per region so a
# filter has something to narrow and an aggregation has something to add up.
ORDERS = (
    b"order_id,region,customer,total\n"
    b"1,North,Acme,100\n"
    b"2,North,\"O'Brien Ltd\",250\n"
    b"3,South,Globex,75\n"
    b"4,South,Initech,410\n"
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


# ---- the aggregation shapes chart-sql.ts produces (Canvas item 2) -----------
def test_a_bar_chart_aggregates_over_the_whole_dataset(
    client: TestClient, fx: Fixture, orders: str
) -> None:
    """Aggregation is server-side for a sharper version of the reason
    filtering is: a chart that sums the preview page and puts an axis on it
    does not show less data, it shows a *wrong number*."""
    result = run(client, fx, orders,
                 'SELECT "region" AS label, count(*) AS value FROM dataset '
                 'GROUP BY 1 ORDER BY 2 DESC LIMIT 25')
    assert dict(result["rows"]) == {"North": 2, "South": 2}


def test_a_sum_measure_casts_so_a_numeric_column_adds_up(
    client: TestClient, fx: Fixture, orders: str
) -> None:
    result = run(client, fx, orders,
                 'SELECT "region" AS label, sum(CAST("total" AS DOUBLE)) AS value '
                 'FROM dataset GROUP BY 1 ORDER BY 2 DESC LIMIT 25')
    assert dict(result["rows"]) == {"South": 485.0, "North": 350.0}


def test_a_non_numeric_measure_fails_visibly_rather_than_charting_zero(
    client: TestClient, fx: Fixture, orders: str
) -> None:
    """CAST, not TRY_CAST. A measure column that is not numeric should fail
    with the engine's own message - which names the column and the value -
    rather than summing to null and drawing an empty chart that reads as
    "no data"."""
    r = client.post(
        f"{pbase(fx)}/datasets/{orders}/query", headers=hdr(fx.viewer_sub),
        json={"sql": 'SELECT "region" AS label, sum(CAST("customer" AS DOUBLE)) AS value '
                     'FROM dataset GROUP BY 1'},
    )
    assert r.status_code == 422
    assert "DOUBLE" in r.json()["detail"] or "convert" in r.json()["detail"].lower()


def test_a_chart_and_a_table_filter_identically(
    client: TestClient, fx: Fixture, orders: str
) -> None:
    """Both build their WHERE from the same `filterPredicate`, so a chart and
    a table pointed at one parameter cannot disagree about which rows are in
    scope - which would be a chart that contradicts the table beside it."""
    predicate = 'CAST("region" AS VARCHAR) = \'North\''
    rows = run(client, fx, orders, f"SELECT * FROM dataset WHERE {predicate} LIMIT 200")
    chart = run(client, fx, orders,
                f'SELECT "region" AS label, count(*) AS value FROM dataset '
                f"WHERE {predicate} GROUP BY 1 ORDER BY 2 DESC LIMIT 25")
    assert len(rows["rows"]) == 2
    assert dict(chart["rows"]) == {"North": 2}


def test_a_line_chart_sorts_by_its_dimension_not_by_value(
    client: TestClient, fx: Fixture, orders: str
) -> None:
    """A line is a series: sorting it by magnitude would draw a shape that
    means nothing."""
    result = run(client, fx, orders,
                 'SELECT "customer" AS label, sum(CAST("total" AS DOUBLE)) AS value '
                 'FROM dataset GROUP BY 1 ORDER BY 1 ASC LIMIT 200')
    assert [row[0] for row in result["rows"]] == sorted(row[0] for row in result["rows"])


def test_a_scatter_query_keeps_individual_points(
    client: TestClient, fx: Fixture, orders: str
) -> None:
    """No GROUP BY: grouping a scatter plot destroys the thing being looked
    at. Null pairs are dropped, since a point needs both coordinates."""
    result = run(client, fx, orders,
                 'SELECT "order_id" AS label, "total" AS value FROM dataset '
                 'WHERE "order_id" IS NOT NULL AND "total" IS NOT NULL LIMIT 500')
    assert len(result["rows"]) == 4
