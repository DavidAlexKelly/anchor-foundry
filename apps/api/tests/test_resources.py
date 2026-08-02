"""The resource registry (ROADMAP.md phase 2, section 0 item 1).

What these tests are actually about is the *invariant*, not the endpoint:
every resource is registered, exactly once, without anybody remembering to do
it, and the registry stops describing a resource at the moment it stops
existing. Migration 0032 puts that in triggers rather than in the API
precisely so it cannot be forgotten - so the tests create rows through the
existing per-kind endpoints and check the registry noticed, which is the only
version of this test that would fail if the trigger were dropped.

The second thing under test is isolation. This table holds resource *names*
across every project in a workspace, which is the metadata a project boundary
exists to keep private; a registry that leaked it would leak it uniformly, for
every kind at once.
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

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402

ADMIN_DSN = os.environ["TEST_ADMIN_DSN"]


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client() -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def base(fx: Fixture, project_id: str | None = None) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{project_id or fx.project}/resources"


@pytest.fixture(scope="module")
def empty_project(fx: Fixture) -> str:
    """A project of its own, so counts and listings are exact rather than
    'at least'. Every other project in this database is shared with whatever
    else the suite created."""
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        pid = conn.execute(
            """INSERT INTO projects (workspace_id, name, slug, created_by)
               VALUES (%s,%s,%s,%s) RETURNING id""",
            (fx.workspace, f"Registry {fx.tag}", f"registry-{fx.tag}", fx.owner),
        ).fetchone()[0]
    return str(pid)


CSV = b"id,email\n1,a@example.com\n2,b@example.com\n"


def make_dataset(client: TestClient, fx: Fixture, project_id: str, name: str) -> str:
    """Upload is the only way to create a dataset from nothing - the others
    fork or sync from something that already exists."""
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{project_id}/datasets/upload",
        headers=hdr(fx.owner_sub),
        data={"name": name},
        files={"file": ("rows.csv", io.BytesIO(CSV), "text/csv")},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def make_model(client: TestClient, fx: Fixture, project_id: str, name: str) -> str:
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{project_id}/models",
        headers=hdr(fx.owner_sub),
        json={"name": name, "language": "sql", "code": "SELECT 1"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def listing(client: TestClient, fx: Fixture, project_id: str, **params) -> dict:
    r = client.get(base(fx, project_id), headers=hdr(fx.owner_sub), params=params)
    assert r.status_code == 200, r.text
    return r.json()


# ---- registration happens without anybody asking for it ----------------------
def test_creating_a_resource_through_its_own_endpoint_registers_it(
    client: TestClient, fx: Fixture, empty_project: str
) -> None:
    """The point of putting registration in a trigger: the datasets endpoint
    knows nothing about the registry, and the registry is still right."""
    assert listing(client, fx, empty_project)["total"] == 0

    make_dataset(client, fx, empty_project, f"Sales {fx.tag}")
    make_model(client, fx, empty_project, f"Rollup {fx.tag}")

    result = listing(client, fx, empty_project)
    assert result["total"] == 2
    assert {r["kind"] for r in result["resources"]} == {"dataset", "model"}
    assert {r["name"] for r in result["resources"]} == {f"Sales {fx.tag}", f"Rollup {fx.tag}"}


def test_renaming_a_resource_renames_it_in_the_registry(
    client: TestClient, fx: Fixture, empty_project: str
) -> None:
    """Two writable copies of a name is a guarantee of drift; the kind table
    is the only writer and this is what proves the mirror follows it."""
    dataset_id = make_dataset(client, fx, empty_project, f"Before {fx.tag}")
    r = client.patch(
        f"/api/workspaces/{fx.workspace}/projects/{empty_project}/datasets/{dataset_id}",
        headers=hdr(fx.owner_sub),
        json={"name": f"After {fx.tag}"},
    )
    assert r.status_code == 200, r.text

    names = {x["name"] for x in listing(client, fx, empty_project)["resources"]}
    assert f"After {fx.tag}" in names
    assert f"Before {fx.tag}" not in names


def test_deleting_a_resource_removes_it_from_the_registry(
    client: TestClient, fx: Fixture, empty_project: str
) -> None:
    """A registry that outlives what it describes is worse than no registry:
    the browser would offer a link to something that is gone."""
    dataset_id = make_dataset(client, fx, empty_project, f"Doomed {fx.tag}")
    before = listing(client, fx, empty_project)["total"]

    r = client.delete(
        f"/api/workspaces/{fx.workspace}/projects/{empty_project}/datasets/{dataset_id}",
        headers=hdr(fx.owner_sub),
    )
    assert r.status_code in (200, 204), r.text
    assert listing(client, fx, empty_project)["total"] == before - 1


def test_every_kind_table_carries_a_registry_row(fx: Fixture) -> None:
    """The invariant stated directly, against the whole database rather than
    against rows this test made: NOT NULL on resource_id means a kind row
    without a registry row cannot be written, and this fails loudly if a
    future migration adds a kind table without wiring it up."""
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        for table in ("connections", "datasets", "models", "object_types",
                      "canvas_apps", "code_repos"):
            missing = conn.execute(
                f"SELECT count(*) FROM {table} t "  # noqa: S608 - fixed list above
                "LEFT JOIN resources r ON r.id = t.resource_id WHERE r.id IS NULL"
            ).fetchone()[0]
            assert missing == 0, f"{table} has {missing} unregistered rows"


# ---- what the browser needs --------------------------------------------------
def test_kind_filter_and_counts_agree_with_each_other(
    client: TestClient, fx: Fixture, empty_project: str
) -> None:
    counts = client.get(
        f"{base(fx, empty_project)}/counts", headers=hdr(fx.owner_sub)
    ).json()["counts"]
    # Every kind present, including the ones with nothing in them - the UI
    # should not have to tell "none of these" from "no such kind".
    assert set(counts) == {"connection", "dataset", "model", "object_type",
                           "canvas_app", "code_repo"}
    for kind, expected in counts.items():
        assert listing(client, fx, empty_project, kind=kind)["total"] == expected, kind


def test_search_matches_a_substring_and_treats_underscore_literally(
    client: TestClient, fx: Fixture, empty_project: str
) -> None:
    """`_` is a single-character wildcard in LIKE. A search box that quietly
    matched more than it was asked for would be wrong in the direction nobody
    checks."""
    make_dataset(client, fx, empty_project, f"quarterly_report {fx.tag}")
    make_dataset(client, fx, empty_project, f"quarterlyXreport {fx.tag}")

    hits = listing(client, fx, empty_project, search="quarterly_report")["resources"]
    assert [h["name"] for h in hits] == [f"quarterly_report {fx.tag}"]


def test_paging_is_stable_across_pages(
    client: TestClient, fx: Fixture, empty_project: str
) -> None:
    """Rows created in the same transaction share a timestamp to the
    microsecond; without a tiebreak in the ORDER BY, page two repeats a row
    from page one and drops another entirely."""
    for i in range(5):
        make_dataset(client, fx, empty_project, f"Page {i} {fx.tag}")

    first = listing(client, fx, empty_project, limit=3, offset=0)
    second = listing(client, fx, empty_project, limit=3, offset=3)
    ids = [r["id"] for r in first["resources"]] + [r["id"] for r in second["resources"]]
    assert len(ids) == len(set(ids)), "a row appeared on two pages"
    assert len(ids) == min(6, first["total"])


def test_an_unknown_sort_or_kind_is_refused_in_a_sentence(
    client: TestClient, fx: Fixture, empty_project: str
) -> None:
    for params, expected in [
        ({"sort": "whatever"}, "sort by"),
        ({"kind": "sql_query"}, "unknown resource kind"),
        ({"direction": "sideways"}, "asc"),
    ]:
        r = client.get(base(fx, empty_project), headers=hdr(fx.owner_sub), params=params)
        assert r.status_code == 422, (params, r.text)
        detail = r.json()["detail"]
        assert isinstance(detail, str), detail
        assert expected in detail


def test_workspace_level_resources_are_opt_in(
    client: TestClient, fx: Fixture, empty_project: str
) -> None:
    """Object types belong to the workspace, not to any project. Mixing them
    into a project listing by default is exactly the mistake that made the
    first-run checklist tick a step in an empty project (STATUS.md §44)."""
    r = client.post(
        f"/api/workspaces/{fx.workspace}/object-types",
        headers=hdr(fx.owner_sub),
        json={"api_name": f"Widget{fx.tag}", "display_name": f"Widget {fx.tag}"},
    )
    assert r.status_code == 201, r.text

    without = listing(client, fx, empty_project)
    assert all(x["kind"] != "object_type" for x in without["resources"])

    with_ws = listing(client, fx, empty_project, include_workspace_level=True, kind="object_type")
    assert with_ws["total"] >= 1
    assert all(x["project_id"] is None for x in with_ws["resources"])


# ---- isolation ---------------------------------------------------------------
def test_the_registry_does_not_leak_names_across_projects(
    client: TestClient, fx: Fixture, empty_project: str
) -> None:
    """A resource in another project must not be listable, and must not be
    reachable by asking for that project directly."""
    make_dataset(client, fx, empty_project, f"Secret {fx.tag}")

    other = client.get(base(fx, fx.project), headers=hdr(fx.owner_sub)).json()
    assert all(x["name"] != f"Secret {fx.tag}" for x in other["resources"])

    denied = client.get(base(fx, empty_project), headers=hdr(fx.outsider_sub))
    assert denied.status_code in (403, 404), denied.text


def test_a_foreign_tenant_sees_nothing(client: TestClient, fx: Fixture, empty_project: str) -> None:
    r = client.get(base(fx, empty_project), headers=hdr(fx.foreign_sub))
    assert r.status_code in (403, 404), r.text


def test_a_viewer_can_read_the_registry(
    client: TestClient, fx: Fixture, empty_project: str
) -> None:
    """Viewer is the floor for every other project-scoped read; a browser the
    read-only members of a project cannot open would make the project
    unnavigable for them."""
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO project_members (project_id, user_id, role) VALUES (%s,%s,'viewer')",
            (uuid.UUID(empty_project), fx.viewer),
        )
    r = client.get(base(fx, empty_project), headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text


# ---- resolution by id alone --------------------------------------------------
def test_a_resource_resolves_by_id_with_enough_to_draw_a_breadcrumb(
    client: TestClient, fx: Fixture, empty_project: str
) -> None:
    """The reason resource ids exist: a link built from workspace and project
    slugs stops working the moment somebody renames either."""
    model_id = make_model(client, fx, empty_project, f"Resolvable {fx.tag}")
    r = client.get(f"/api/resources/{model_id}", headers=hdr(fx.owner_sub))
    assert r.status_code == 404, "the kind row's id is not the resource id"

    listed = listing(client, fx, empty_project, search=f"Resolvable {fx.tag}")["resources"]
    resource_id = listed[0]["id"]
    r = client.get(f"/api/resources/{resource_id}", headers=hdr(fx.owner_sub))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "model" and body["name"] == f"Resolvable {fx.tag}"
    assert body["project_slug"] and body["workspace_slug"]
    assert body["trashed"] is False


def test_a_renamed_resource_keeps_the_same_id(
    client: TestClient, fx: Fixture, empty_project: str
) -> None:
    """Stable for life, surviving renames, is the whole promise of the id."""
    dataset_id = make_dataset(client, fx, empty_project, f"Renameable {fx.tag}")
    found = listing(client, fx, empty_project, search=f"Renameable {fx.tag}")["resources"]
    resource_id = found[0]["id"]

    client.patch(
        f"/api/workspaces/{fx.workspace}/projects/{empty_project}/datasets/{dataset_id}",
        headers=hdr(fx.owner_sub),
        json={"name": f"Renamed {fx.tag}"},
    )
    r = client.get(f"/api/resources/{resource_id}", headers=hdr(fx.owner_sub))
    assert r.status_code == 200, r.text
    assert r.json()["name"] == f"Renamed {fx.tag}"


def test_resolving_someone_elses_resource_is_a_flat_404(
    client: TestClient, fx: Fixture, empty_project: str
) -> None:
    """Indistinguishable from "no such resource" on purpose: a 403 here would
    confirm that an id belongs to something, which is the one bit an id-only
    endpoint must not leak."""
    make_model(client, fx, empty_project, f"Private {fx.tag}")
    resource_id = listing(client, fx, empty_project, search=f"Private {fx.tag}")["resources"][0]["id"]

    for sub in (fx.outsider_sub, fx.foreign_sub):
        r = client.get(f"/api/resources/{resource_id}", headers=hdr(sub))
        assert r.status_code == 404, (sub, r.text)
        assert isinstance(r.json()["detail"], str)
