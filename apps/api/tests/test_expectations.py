"""Dataset expectations and data health (roadmap Datasets item 2, migration 0020).

Rules are checked against a real Parquet file written by the real upload path,
so a "fail" here means DuckDB actually counted bad rows rather than a stub
saying so.

The behaviours worth pinning, beyond "does each rule work":
  * `error` and `fail` are different outcomes - a rule that cannot run has not
    proven anything about the data.
  * severity decides what a failure *means* for the dataset overall.
  * a rule change invalidates the cached result, because a health badge that
    lags an edit is worse than one that takes a moment.
"""
from __future__ import annotations

import io
import os
import sys

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

ADMIN_DSN = os.environ["TEST_ADMIN_DSN"]

# email is missing one value and has a duplicate; age has one out-of-range
# value; code has one that does not match the pattern.
CSV = (
    "id,email,age,code\n"
    "1,a@example.com,34,AB-1\n"
    "2,b@example.com,29,AB-2\n"
    "3,,201,AB-3\n"
    "4,b@example.com,41,nope\n"
)


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("expectations-storage")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def base(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets"


def _upload(client: TestClient, fx: Fixture, name: str, body: str = CSV) -> str:
    r = client.post(
        f"{base(fx)}/upload",
        headers=hdr(fx.editor_sub),
        files={"file": (f"{name}.csv", io.BytesIO(body.encode()), "text/csv")},
        data={"name": name},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _add(
    client: TestClient, fx: Fixture, dataset_id: str, rule_type: str, column: str,
    config: dict | None = None, severity: str = "error", expect: int = 201,
):
    r = client.post(
        f"{base(fx)}/{dataset_id}/expectations",
        headers=hdr(fx.editor_sub),
        json={"rule_type": rule_type, "column_name": column,
              "config": config or {}, "severity": severity},
    )
    assert r.status_code == expect, r.text
    return r.json() if expect == 201 else r


def _health(client: TestClient, fx: Fixture, dataset_id: str, sub: str | None = None) -> dict:
    r = client.get(f"{base(fx)}/{dataset_id}/health", headers=hdr(sub or fx.viewer_sub))
    assert r.status_code == 200, r.text
    return r.json()


def _by_column(health: dict) -> dict[str, dict]:
    return {r["column_name"]: r for r in health["results"]}


# ---- no rules ----------------------------------------------------------------
def test_a_dataset_with_no_rules_is_none_not_passing(client: TestClient, fx: Fixture) -> None:
    """"Nothing is checked" and "everything checked out" are different facts
    and must not render the same."""
    dataset_id = _upload(client, fx, f"No rules {fx.tag}")
    health = _health(client, fx, dataset_id)
    assert health["status"] == "none"
    assert health["results"] == []


# ---- each rule type against real data ---------------------------------------
def test_each_rule_type_counts_real_failures(client: TestClient, fx: Fixture) -> None:
    dataset_id = _upload(client, fx, f"All rules {fx.tag}")
    _add(client, fx, dataset_id, "not_null", "email")
    _add(client, fx, dataset_id, "unique", "email")
    _add(client, fx, dataset_id, "value_in_range", "age", {"min": 0, "max": 130})
    _add(client, fx, dataset_id, "regex_match", "code", {"pattern": "^AB-[0-9]+$"})
    _add(client, fx, dataset_id, "column_exists", "id")

    health = _health(client, fx, dataset_id)
    results = {(r["rule_type"], r["column_name"]): r for r in health["results"]}

    assert results[("not_null", "email")]["status"] == "fail"
    assert results[("not_null", "email")]["failing_rows"] == 1

    # b@example.com twice: one row beyond the first occurrence.
    assert results[("unique", "email")]["status"] == "fail"
    assert results[("unique", "email")]["failing_rows"] == 1

    assert results[("value_in_range", "age")]["status"] == "fail"
    assert results[("value_in_range", "age")]["failing_rows"] == 1

    assert results[("regex_match", "code")]["status"] == "fail"
    assert results[("regex_match", "code")]["failing_rows"] == 1

    assert results[("column_exists", "id")]["status"] == "pass"
    assert health["status"] == "fail"
    assert all(r["rows_checked"] == 4 for r in health["results"])


def test_rules_that_hold_report_pass(client: TestClient, fx: Fixture) -> None:
    dataset_id = _upload(client, fx, f"Clean rules {fx.tag}")
    _add(client, fx, dataset_id, "not_null", "id")
    _add(client, fx, dataset_id, "unique", "id")
    _add(client, fx, dataset_id, "value_in_range", "id", {"min": 1, "max": 4})

    health = _health(client, fx, dataset_id)
    assert health["status"] == "pass"
    assert all(r["status"] == "pass" and r["failing_rows"] == 0 for r in health["results"])
    assert health["evaluated_at"] is not None


def test_nulls_do_not_count_against_uniqueness_or_range(
    client: TestClient, fx: Fixture
) -> None:
    """SQL uniqueness does not constrain nulls, and a missing value is out of
    no range - counting them here would double-report what not_null covers."""
    dataset_id = _upload(client, fx, f"Null semantics {fx.tag}", "id,val\n1,\n2,\n3,7\n")
    _add(client, fx, dataset_id, "unique", "val")
    _add(client, fx, dataset_id, "value_in_range", "val", {"min": 0, "max": 10})
    health = _health(client, fx, dataset_id)
    assert health["status"] == "pass", health["results"]


# ---- error is not fail -------------------------------------------------------
def test_a_rule_on_a_missing_column_errors_rather_than_failing(
    client: TestClient, fx: Fixture
) -> None:
    """The data has not been proven bad - the rule just could not run. Calling
    that a failure sends someone looking in the wrong place."""
    dataset_id = _upload(client, fx, f"Missing column {fx.tag}")
    _add(client, fx, dataset_id, "not_null", "no_such_column")

    health = _health(client, fx, dataset_id)
    result = health["results"][0]
    assert result["status"] == "error"
    assert "not in this version" in result["message"]
    # An unevaluatable rule degrades health to warn, not fail.
    assert health["status"] == "warn"


def test_column_exists_is_the_rule_that_does_fail_on_a_missing_column(
    client: TestClient, fx: Fixture
) -> None:
    dataset_id = _upload(client, fx, f"Column exists {fx.tag}")
    _add(client, fx, dataset_id, "column_exists", "not_here")
    health = _health(client, fx, dataset_id)
    assert health["results"][0]["status"] == "fail"
    assert health["status"] == "fail"


def test_a_range_check_on_text_errors_rather_than_failing(
    client: TestClient, fx: Fixture
) -> None:
    """A rule DuckDB cannot run against this column's type is a configuration
    problem, and one broken rule must not stop the others being evaluated."""
    dataset_id = _upload(client, fx, f"Bad range {fx.tag}", "id,name\n1,ada\n2,grace\n")
    _add(client, fx, dataset_id, "value_in_range", "name", {"min": 0, "max": 10})
    _add(client, fx, dataset_id, "not_null", "id")

    health = _health(client, fx, dataset_id)
    by_column = _by_column(health)
    assert by_column["name"]["status"] == "error"
    assert by_column["id"]["status"] == "pass", "the other rule still ran"


# ---- severity ----------------------------------------------------------------
def test_severity_decides_what_a_failure_means(client: TestClient, fx: Fixture) -> None:
    dataset_id = _upload(client, fx, f"Severity {fx.tag}")
    warn_rule = _add(client, fx, dataset_id, "not_null", "email", severity="warn")

    health = _health(client, fx, dataset_id)
    assert health["results"][0]["status"] == "fail"
    assert health["status"] == "warn", "a warn-severity failure must not condemn the dataset"

    # The same failure at error severity does.
    assert client.delete(
        f"{base(fx)}/{dataset_id}/expectations/{warn_rule['id']}",
        headers=hdr(fx.editor_sub),
    ).status_code == 204
    _add(client, fx, dataset_id, "not_null", "email", severity="error")
    assert _health(client, fx, dataset_id)["status"] == "fail"


# ---- caching and invalidation ------------------------------------------------
def _cached(dataset_id: str):
    with psycopg.connect(ADMIN_DSN) as conn:
        return conn.execute(
            "SELECT expectation_results FROM dataset_versions "
            "WHERE dataset_id=%s AND version_number=1",
            (dataset_id,),
        ).fetchone()[0]


def test_health_is_cached_and_a_rule_change_invalidates_it(
    client: TestClient, fx: Fixture
) -> None:
    dataset_id = _upload(client, fx, f"Cache health {fx.tag}")
    _add(client, fx, dataset_id, "not_null", "id")

    assert _cached(dataset_id) is None, "evaluation is lazy"
    first = _health(client, fx, dataset_id)
    assert first["status"] == "pass"
    assert _cached(dataset_id) is not None, "the first read caches"

    # Adding a rule must drop the cache - otherwise the badge would keep
    # reporting 'pass' against a rule set that now includes a failing check.
    _add(client, fx, dataset_id, "not_null", "email")
    assert _cached(dataset_id) is None, "a rule change invalidates the cache"

    second = _health(client, fx, dataset_id)
    assert second["status"] == "fail", "the new rule is reflected immediately"
    assert len(second["results"]) == 2


def test_deleting_a_rule_also_invalidates(client: TestClient, fx: Fixture) -> None:
    dataset_id = _upload(client, fx, f"Delete invalidates {fx.tag}")
    rule = _add(client, fx, dataset_id, "not_null", "email")
    assert _health(client, fx, dataset_id)["status"] == "fail"

    assert client.delete(
        f"{base(fx)}/{dataset_id}/expectations/{rule['id']}", headers=hdr(fx.editor_sub)
    ).status_code == 204
    assert _cached(dataset_id) is None
    assert _health(client, fx, dataset_id)["status"] == "none"


# ---- rule configuration ------------------------------------------------------
def test_bad_rule_configuration_is_refused_at_save_time(
    client: TestClient, fx: Fixture
) -> None:
    """A typo should be a 422 on the form the user is looking at, not a
    mystery on a later health read."""
    dataset_id = _upload(client, fx, f"Bad config {fx.tag}")
    for rule_type, config, expected in [
        ("regex_match", {"pattern": "["}, "invalid"),
        ("regex_match", {}, "needs a pattern"),
        ("value_in_range", {}, "needs a min"),
        ("value_in_range", {"min": 10, "max": 1}, "must not exceed"),
        ("value_in_range", {"min": "ten"}, "must be numbers"),
        ("teleport", {}, "unknown rule type"),
    ]:
        r = _add(client, fx, dataset_id, rule_type, "email", config, expect=422)
        assert expected in r.json()["detail"], (rule_type, config, r.json())


def test_the_same_rule_twice_on_a_column_is_a_conflict(
    client: TestClient, fx: Fixture
) -> None:
    dataset_id = _upload(client, fx, f"Duplicate rule {fx.tag}")
    _add(client, fx, dataset_id, "not_null", "email")
    r = _add(client, fx, dataset_id, "not_null", "email", expect=409)
    assert "already exists" in r.json()["detail"]


# ---- access ------------------------------------------------------------------
def test_role_floors_and_isolation(client: TestClient, fx: Fixture) -> None:
    dataset_id = _upload(client, fx, f"Roles {fx.tag}")
    # A viewer reads health and rules but cannot define them.
    assert client.get(
        f"{base(fx)}/{dataset_id}/expectations", headers=hdr(fx.viewer_sub)
    ).status_code == 200
    assert _health(client, fx, dataset_id, sub=fx.viewer_sub)["status"] == "none"
    assert client.post(
        f"{base(fx)}/{dataset_id}/expectations",
        headers=hdr(fx.viewer_sub),
        json={"rule_type": "not_null", "column_name": "email"},
    ).status_code == 403
    # An outsider sees nothing at all.
    assert client.get(
        f"{base(fx)}/{dataset_id}/health", headers=hdr(fx.outsider_sub)
    ).status_code == 404


def test_expectation_changes_are_audited(client: TestClient, fx: Fixture) -> None:
    r = client.get("/api/org/audit?limit=200", headers=hdr(fx.admin_sub))
    actions = {e["action"] for e in r.json()}
    assert {"dataset.expectation.create", "dataset.expectation.delete"} <= actions
