"""Saved time series analyses (§662; `workshop` p.397, migration 0131).

> "Enable analysis saving: Save and share analyses for future reference.
>  Analyses can be saved as either Private or Public." (p.397)

A viewer saves an analysis of their own; private, it is theirs alone, and
public, the project's to open - but only its author saves over or deletes it.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.services import series_analyses as service  # noqa: E402


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client() -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    with TestClient(create_app(), raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def base(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/series-analyses"


STATE = {"plots": [{"id": "root:1", "label": "Pump 1", "canvas": 1}], "canvases": 1}


def save(client: TestClient, fx: Fixture, sub: str, **body):
    body.setdefault("name", f"Analysis {uuid.uuid4().hex[:6]}")
    body.setdefault("state", STATE)
    return client.post(base(fx), headers=hdr(sub), json=body)


def names(client: TestClient, fx: Fixture, sub: str) -> set[str]:
    r = client.get(base(fx), headers=hdr(sub))
    assert r.status_code == 200, r.text
    return {a["name"] for a in r.json()}


def test_a_private_analysis_is_its_author_s_alone(client, fx) -> None:
    r = save(client, fx, fx.viewer_sub, name="Mine alone")
    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["visibility"], body["mine"], body["state"]) == ("private", True, STATE)
    assert body["created_by_name"]
    assert "Mine alone" in names(client, fx, fx.viewer_sub)
    assert "Mine alone" not in names(client, fx, fx.editor_sub)
    assert client.get(f"{base(fx)}/{body['id']}", headers=hdr(fx.editor_sub)).status_code == 404
    got = client.get(f"{base(fx)}/{body['id']}", headers=hdr(fx.viewer_sub))
    assert got.status_code == 200 and got.json()["state"] == STATE


def test_a_public_analysis_is_the_project_s_to_open_but_its_author_s_to_change(client, fx) -> None:
    made = save(client, fx, fx.viewer_sub, name="Shared", visibility="public").json()
    assert "Shared" in names(client, fx, fx.editor_sub)
    seen = client.get(f"{base(fx)}/{made['id']}", headers=hdr(fx.editor_sub)).json()
    assert (seen["mine"], seen["visibility"]) == (False, "public")
    said = "only its author saves over or deletes an analysis - save your own copy"
    r = client.put(f"{base(fx)}/{made['id']}", headers=hdr(fx.editor_sub), json={"state": {}})
    assert r.status_code == 403 and r.json()["detail"] == said
    r = client.delete(f"{base(fx)}/{made['id']}", headers=hdr(fx.editor_sub))
    assert r.status_code == 403 and r.json()["detail"] == said
    # Their own copy, under the same name.
    assert save(client, fx, fx.editor_sub, name="Shared").status_code == 201


def test_the_author_saves_over_it_and_deletes_it(client, fx) -> None:
    made = save(client, fx, fx.viewer_sub, name="Revised").json()
    later = {"plots": [], "canvases": 2}
    r = client.put(f"{base(fx)}/{made['id']}", headers=hdr(fx.viewer_sub),
                   json={"state": later, "visibility": "public"})
    assert r.status_code == 200, r.text
    assert (r.json()["state"], r.json()["visibility"], r.json()["name"]) == (later, "public", "Revised")
    assert r.json()["updated_at"] >= made["updated_at"]
    assert client.delete(f"{base(fx)}/{made['id']}", headers=hdr(fx.viewer_sub)).status_code == 204
    assert client.get(f"{base(fx)}/{made['id']}", headers=hdr(fx.viewer_sub)).status_code == 404


def test_one_name_per_author(client, fx) -> None:
    assert save(client, fx, fx.viewer_sub, name="Twice").status_code == 201
    r = save(client, fx, fx.viewer_sub, name="Twice")
    assert r.status_code == 409
    assert r.json()["detail"] == "you already have an analysis called 'Twice' in this project"


@pytest.mark.parametrize("body, said", [
    ({"state": {"plots": {}}}, "an analysis's plots are a list"),
    ({"state": {"plots": [{"id": "a"}]}}, "each plot has an id and a label"),
    ({"state": {"plots": ["a"]}}, "each plot has an id and a label"),
    ({"state": {"plots": [{"id": str(n), "label": "p"} for n in range(service.MAX_PLOTS + 1)]}},
     f"an analysis has at most {service.MAX_PLOTS} plots"),
    ({"state": {"note": "x" * service.MAX_STATE_BYTES}},
     f"an analysis is at most {service.MAX_STATE_BYTES:,} bytes saved"),
    ({"visibility": "everyone"}, "an analysis is private or public"),
])
def test_what_cannot_be_saved_is_said(client, fx, body, said) -> None:
    r = save(client, fx, fx.viewer_sub, **body)
    assert r.status_code == 422, r.text
    assert said in str(r.json()["detail"])


def test_a_full_widget_is_saved(client, fx) -> None:
    full = {"plots": [{"id": str(n), "label": "p"} for n in range(service.MAX_PLOTS)]}
    assert save(client, fx, fx.viewer_sub, state=full).status_code == 201


def test_a_stranger_to_the_project_finds_nothing(client, fx) -> None:
    assert client.get(base(fx), headers=hdr(fx.outsider_sub)).status_code == 404
    assert save(client, fx, fx.outsider_sub).status_code == 404


def test_the_state_must_be_an_object() -> None:
    with pytest.raises(service.AnalysisError, match="an analysis is saved as an object"):
        service.parse([])


def test_an_analysis_is_found_by_its_rid_alone(client, fx) -> None:
    """p.397: "loaded into the Workshop widget using its RID" (§663)."""
    shared = save(client, fx, fx.viewer_sub, name="By RID", visibility="public").json()
    private = save(client, fx, fx.viewer_sub, name="By RID private").json()
    rid = lambda a: f"/api/workspaces/{fx.workspace}/series-analyses/{a['id']}"  # noqa: E731
    r = client.get(rid(shared), headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    assert (r.json()["name"], r.json()["project_id"]) == ("By RID", str(fx.project))
    assert client.get(rid(private), headers=hdr(fx.viewer_sub)).status_code == 200
    assert client.get(rid(private), headers=hdr(fx.editor_sub)).status_code == 404
    assert client.get(rid({"id": uuid.uuid4()}), headers=hdr(fx.viewer_sub)).status_code == 404
    assert client.get(rid(shared), headers=hdr(fx.outsider_sub)).status_code == 404


def test_an_rid_names_an_analysis_in_this_workspace_only(client, fx) -> None:
    """Asked for through another workspace's address, an analysis is not
    found, even by a reader who could open it in its own."""
    import psycopg

    shared = save(client, fx, fx.viewer_sub, name="Elsewhere", visibility="public").json()
    other = uuid.uuid4()
    with psycopg.connect(os.environ["TEST_ADMIN_DSN"], autocommit=True) as db:
        org = db.execute("SELECT organisation_id FROM workspaces WHERE id = %s", (fx.workspace,)).fetchone()[0]
        db.execute(
            """INSERT INTO workspaces (id, organisation_id, name, slug, s3_prefix, pg_schema, search_prefix,
                                       created_by)
               SELECT %s, %s, %s, %s, %s, %s, %s, created_by FROM workspaces WHERE id = %s""",
            (other, org, f"Other {other.hex[:6]}", f"other-{other.hex[:6]}", f"workspaces/o-{other.hex[:6]}/",
             f"ws_{other.hex[:12]}", f"ws-{other.hex[:12]}-", fx.workspace))
        db.execute("INSERT INTO workspace_members (workspace_id, user_id, role) VALUES (%s, %s, 'viewer')",
                   (other, fx.viewer))
    r = client.get(f"/api/workspaces/{other}/series-analyses/{shared['id']}", headers=hdr(fx.viewer_sub))
    assert r.status_code == 404
