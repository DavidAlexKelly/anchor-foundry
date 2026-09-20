"""The watching half of auto-refresh (Foundry `workshop` p.576-579).

> "With auto-refresh, you can register object sets within a module to be
> watched for updates from anywhere in Foundry." (p.576)

The refreshing half is the browser's and already existed. This is the question
it asks: when did this object type last change, and how many objects does it
have. **Both numbers, because a delete lowers the maximum rather than raising
it** — a watcher comparing only the newest timestamp would see the watermark
move backwards and have to decide whether that counts.
"""
from __future__ import annotations

import io
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

ROWS = b"widget_id,name\nW1,First\nW2,Second\n"
MORE = b"widget_id,name\nW3,Third\nW4,Fourth\n"


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("freshness-storage")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


def dbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets"


def sbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/object-type-sources"


@pytest.fixture(scope="module")
def world(client: TestClient, fx: Fixture) -> dict:
    r = client.post(
        f"{dbase(fx)}/upload", headers=hdr(fx.editor_sub),
        data={"name": f"FreshWidgets{fx.tag}"},
        files={"file": ("w.csv", io.BytesIO(ROWS), "text/csv")},
    )
    assert r.status_code == 201, r.text
    dataset = r.json()["id"]

    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"FreshWidget{fx.tag}", "display_name": "Fresh widget",
              "properties": [{"api_name": "name", "data_type": "string"}]},
    )
    assert r.status_code == 201, r.text
    type_id = r.json()["id"]

    r = client.post(
        sbase(fx), headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "dataset_id": dataset,
              "primary_key_column": "widget_id", "column_mappings": {"name": "name"}},
    )
    assert r.status_code == 201, r.text
    source = r.json()["id"]
    r = client.post(f"{sbase(fx)}/{source}/sync", headers=hdr(fx.editor_sub), json={})
    assert r.status_code == 200, r.text
    return {"type": type_id, "dataset": dataset, "source": source}


def ask(client, fx, ids) -> list[dict]:
    r = client.post(
        f"{wbase(fx)}/object-types/freshness", headers=hdr(fx.viewer_sub),
        json={"object_type_ids": ids},
    )
    assert r.status_code == 200, r.text
    return r.json()["types"]


def add_source(client, fx, world: dict, label: str, body: bytes) -> None:
    """More objects on the same type, from a second dataset.

    p.576's second example of an update source: *"edits from an upstream data
    integration"*. A second source rather than a re-upload because `/upload`
    always creates a dataset and refuses a name it already has, and there is
    no route that repoints or removes a source — so this is the write path a
    test can actually drive.
    """
    r = client.post(
        f"{dbase(fx)}/upload", headers=hdr(fx.editor_sub),
        data={"name": f"FreshWidgets{label}{fx.tag}"},
        files={"file": ("w.csv", io.BytesIO(body), "text/csv")},
    )
    assert r.status_code == 201, r.text
    dataset = r.json()["id"]
    r = client.post(
        sbase(fx), headers=hdr(fx.editor_sub),
        json={"object_type_id": world["type"], "dataset_id": dataset,
              "primary_key_column": "widget_id", "column_mappings": {"name": "name"}},
    )
    assert r.status_code == 201, r.text
    r = client.post(
        f"{sbase(fx)}/{r.json()['id']}/sync", headers=hdr(fx.editor_sub), json={},
    )
    assert r.status_code == 200, r.text


def test_a_watched_type_reports_a_watermark(client: TestClient, fx: Fixture, world: dict) -> None:
    got = ask(client, fx, [world["type"]])
    assert len(got) == 1, got
    assert got[0]["object_type_id"] == world["type"]
    assert got[0]["count"] == 2, got
    assert got[0]["updated_at"], got


def test_the_watermark_is_stable_when_nothing_changes(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """**The half that decides whether the feature is usable.** A watermark
    that moved on its own would refresh every watching module every ten
    seconds, which is p.577's cost warning realised as a bug."""
    first = ask(client, fx, [world["type"]])[0]
    second = ask(client, fx, [world["type"]])[0]
    assert first == second, (first, second)


def test_a_write_moves_the_watermark(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """p.576: an update "from anywhere in Foundry" has to be visible here, or
    nothing downstream can notice it."""
    before = ask(client, fx, [world["type"]])[0]
    add_source(client, fx, world, "More", MORE)
    after = ask(client, fx, [world["type"]])[0]
    assert after != before, (before, after)
    assert after["count"] > before["count"], (before, after)


def test_the_count_is_reported_beside_the_timestamp(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """**The half the maximum cannot cover, and why the answer is a pair.**

    A delete does not raise the newest `updated_at` — it usually lowers it —
    so a watcher comparing only the timestamp would either miss the write or
    see the watermark move backwards and have to guess whether that counts.
    The count moves on every insert and every delete.

    Asserted here as *reported*; that a count-only change is treated as a
    change is the browser comparator's claim and is pinned in
    `auto-refresh.test.ts`, which is also the only place a delete can be
    expressed — this platform writes instances through Actions and sync, and
    has no route that removes a source.
    """
    got = ask(client, fx, [world["type"]])[0]
    assert set(got) == {"object_type_id", "updated_at", "count"}, got
    assert isinstance(got["count"], int), got


def test_an_empty_type_is_not_an_error(client: TestClient, fx: Fixture) -> None:
    """A type nobody has synced has no objects and no index. That is "nothing
    yet", not a broken store, and a module watching it should render."""
    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"FreshEmpty{fx.tag}", "display_name": "Fresh empty",
              "properties": [{"api_name": "name", "data_type": "string"}]},
    )
    assert r.status_code == 201, r.text
    got = ask(client, fx, [r.json()["id"]])
    assert got[0]["count"] == 0, got
    assert got[0]["updated_at"] is None, got


def test_asking_about_nothing_is_answered_rather_than_refused(
    client: TestClient, fx: Fixture
) -> None:
    """A module with auto-refresh on and nothing registered yet. An error here
    would make a half-configured module look broken rather than unfinished."""
    assert ask(client, fx, []) == []


def test_a_type_that_is_gone_is_left_out_rather_than_failing_the_call(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """A module can outlive the ontology it was built against. A deleted type
    should stop the module refreshing, not stop it rendering — so the answer
    names the types that still exist and says nothing about the rest."""
    import uuid as _uuid
    got = ask(client, fx, [world["type"], str(_uuid.uuid4())])
    assert [t["object_type_id"] for t in got] == [world["type"]], got


def test_a_viewer_may_ask(client: TestClient, fx: Fixture, world: dict) -> None:
    """Auto-refresh runs for whoever is reading the module, which is usually
    somebody who cannot edit anything."""
    r = client.post(
        f"{wbase(fx)}/object-types/freshness", headers=hdr(fx.viewer_sub),
        json={"object_type_ids": [world["type"]]},
    )
    assert r.status_code == 200, r.text
