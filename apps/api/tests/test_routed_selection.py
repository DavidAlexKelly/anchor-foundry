"""A picked object, restored from a link (§416; `workshop` p.199).

> "Object set variables are limited to single objects, specified by their RID"
> (p.199)

`test_object_refs.py` covers the format. This covers the half only a database
can answer: that a reference in `values` becomes the object again, through the
same read the click that selected it would have made — and that everything
which does not resolve arrives at "nothing picked" rather than at an error.
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

SITES = b"site_id,name,region\nS1,North Depot,north\nS2,South Depot,south\n"

#: A well-formed ref naming nothing.
NOWHERE = f"{uuid.UUID(int=0xAB)}:{uuid.UUID(int=0xCD)}"


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("routed-storage")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


def pbase(fx: Fixture) -> str:
    return f"{wbase(fx)}/projects/{fx.project}"


@pytest.fixture(scope="module")
def world(client: TestClient, fx: Fixture) -> dict:
    """A type with two rows, and a module whose selection is routed."""
    r = client.post(
        f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"Sites{fx.tag}"},
        files={"file": ("sites.csv", io.BytesIO(SITES), "text/csv")},
    )
    assert r.status_code == 201, r.text
    dataset = r.json()["id"]

    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"site_{fx.tag}", "display_name": "Site",
              "properties": [{"api_name": "name", "data_type": "string"},
                             {"api_name": "region", "data_type": "string"}]},
    )
    assert r.status_code == 201, r.text
    type_id = r.json()["id"]

    r = client.post(
        f"{pbase(fx)}/object-type-sources", headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "dataset_id": dataset,
              "primary_key_column": "site_id",
              "column_mappings": {"name": "name", "region": "region"}},
    )
    assert r.status_code == 201, r.text
    source = r.json()["id"]
    r = client.post(f"{pbase(fx)}/object-type-sources/{source}/sync",
                    headers=hdr(fx.editor_sub), json={})
    assert r.status_code == 200, r.text

    r = client.get(f"{wbase(fx)}/object-types/{type_id}/instances",
                   headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    rows = {i["primary_key"]: i for i in r.json()["items"]}

    r = client.post(f"{pbase(fx)}/canvas-apps", headers=hdr(fx.editor_sub),
                    json={"name": f"Routed {uuid.uuid4().hex[:8]}"})
    assert r.status_code == 201, r.text
    app_id = r.json()["id"]
    r = client.put(
        f"{pbase(fx)}/canvas-apps/{app_id}/definition", headers=hdr(fx.editor_sub),
        json={"definition": {
            "format": 2, "layout": {}, "events": {},
            "routing": {"enabled": True},
            "variables": {
                "v_sel": {
                    "id": "v_sel", "kind": "single_object", "label": "Picked site",
                    "external_id": "selected", "interface": True,
                    "url_behavior": "always",
                },
                "v_name": {
                    "id": "v_name", "kind": "string", "label": "Picked name",
                    "derivation": {"transform": "object_property",
                                   "inputs": ["v_sel"], "config": {"property": "name"}},
                },
            },
        }},
    )
    assert r.status_code == 200, r.text
    return {"type_id": type_id, "rows": rows, "app_id": app_id}


def resolve(client, fx, world, values, sub=None):
    r = client.post(
        f"{pbase(fx)}/canvas-apps/{world['app_id']}/variables/evaluate",
        headers=hdr(sub or fx.editor_sub), json={"values": values},
    )
    assert r.status_code == 200, r.text
    return r.json()["values"]


def ref_to(world, key: str) -> str:
    return f"{world['type_id']}:{world['rows'][key]['id']}"


def test_a_reference_becomes_the_object_again(client, fx, world) -> None:
    """The whole unit. A link carries two ids; what comes back is the object,
    with the properties a widget reads — and `v_name` proves it, because a
    derived property cannot be read off a string."""
    values = resolve(client, fx, world, {"v_sel": ref_to(world, "S1")})
    picked = values["v_sel"]
    assert picked["primary_key"] == "S1", picked
    assert picked["properties"]["name"] == "North Depot", picked
    assert picked["object_type_id"] == world["type_id"]
    assert values["v_name"] == "North Depot"


def test_the_reference_is_not_a_snapshot(client, fx, world) -> None:
    """p.199 says RID, and this is the consequence: the link carries no
    properties, so what a recipient sees is the object *now* rather than the
    object as it was when the link was written."""
    ref = ref_to(world, "S2")
    assert "South" not in ref
    values = resolve(client, fx, world, {"v_sel": ref})
    assert values["v_sel"]["properties"]["name"] == "South Depot"


def test_a_reference_to_nothing_is_nothing_picked(client, fx, world) -> None:
    """Not an error. A deleted object, or one this viewer cannot see, leaves
    the module in the state a detail panel is in before the first click — which
    every widget already draws. The alternative loses the rest of the shared
    view to an error page."""
    values = resolve(client, fx, world, {"v_sel": NOWHERE})
    assert values["v_sel"] is None
    assert values["v_name"] is None


def test_a_string_that_was_never_a_reference_is_nothing_picked(client, fx, world) -> None:
    """Somebody typed the link. `?selected=banana` is not a lookup to attempt
    and not a reason to refuse the whole resolve."""
    for junk in ("banana", "", f"{world['type_id']}:", "a:b"):
        values = resolve(client, fx, world, {"v_sel": junk})
        assert values["v_sel"] is None, junk


def test_an_object_still_arrives_whole(client, fx, world) -> None:
    """**The click's own path has to keep working**, because a row click sends
    the object itself rather than a reference. An expansion that swallowed a
    real value would break every selection in the product to fix links."""
    row = world["rows"]["S1"]
    sent = {"id": row["id"], "object_type_id": world["type_id"],
            "primary_key": "S1", "properties": row["properties"]}
    values = resolve(client, fx, world, {"v_sel": sent})
    assert values["v_sel"] == sent
    assert values["v_name"] == "North Depot"


def test_a_routed_selection_is_refused_to_somebody_who_cannot_see_the_type(
    client, fx, world
) -> None:
    """The read is the one the click would have made, so a link cannot show its
    recipient an object they could not have opened themselves. The outsider
    holds no workspace role, so the type does not exist for them — and the
    answer is the same "nothing picked" a deleted object gets, because telling
    the two apart is exactly what a link must not do."""
    r = client.post(
        f"{pbase(fx)}/canvas-apps/{world['app_id']}/variables/evaluate",
        headers=hdr(fx.outsider_sub), json={"values": {"v_sel": ref_to(world, "S1")}},
    )
    # The module itself is out of reach first, which is the stronger answer.
    assert r.status_code == 404, r.text
