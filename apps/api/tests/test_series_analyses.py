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
