"""p.393's Linked event set (§654; `workshop` p.393).

    "Linked event set: Create an event set from linked objects in the
     Ontology by traversing object relationships and specifying which
     properties hold the start and end timestamps." (p.393)

Pumps and their maintenance jobs: each job links to its pump by `pump_id`, and
starts and finishes at two timestamps. P1's jobs are the event set asked for
from P1.
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
from src.routes import objects as object_routes  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

PUMPS = b"pump_id,name\nP1,Pump one\nP2,Pump two\n"
# J3 finishes before it starts; J4 has no start; J2 has no finish; J0, first
# by key, is last in time, and names its zones.
JOBS = (
    b"job_id,pump_id,started,finished,due,note\n"
    b"J0,P1,2026-01-10T00:00:00Z,2026-01-10T04:00:00+02:00,,late\n"
    b"J1,P1,2026-01-02T00:00:00,2026-01-03T12:00:00,2026-01-02,seal\n"
    b"J2,P1,2026-01-05T06:00:00,,2026-01-05,check\n"
    b"J3,P1,2026-01-08T00:00:00,2026-01-07T00:00:00,,swap\n"
    b"J4,P1,,2026-01-09T00:00:00,,none\n"
    b"J5,P2,2026-01-01T00:00:00,2026-01-01T01:00:00,,other\n"
)


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("linked-events"))))
    with TestClient(create_app(), raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


def pbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


def _upload(client: TestClient, fx: Fixture, name: str, csv: bytes) -> str:
    r = client.post(f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
                    data={"name": name}, files={"file": ("d.csv", io.BytesIO(csv), "text/csv")})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _type(client: TestClient, fx: Fixture, api_name: str, props: dict[str, str]) -> str:
    r = client.post(f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
                    json={"api_name": api_name, "display_name": api_name.title(),
                          "properties": [{"api_name": p, "data_type": t} for p, t in props.items()]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _sync(client: TestClient, fx: Fixture, type_id: str, dataset: str, pk: str, cols: list[str]) -> None:
    r = client.post(f"{pbase(fx)}/object-type-sources", headers=hdr(fx.editor_sub),
                    json={"object_type_id": type_id, "dataset_id": dataset,
                          "primary_key_column": pk, "column_mappings": {c: c for c in cols}})
    assert r.status_code == 201, r.text
    r = client.post(f"{pbase(fx)}/object-type-sources/{r.json()['id']}/sync",
                    headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text


@pytest.fixture(scope="module")
def pumps(client: TestClient, fx: Fixture) -> dict:
    tag = uuid.uuid4().hex[:6]
    pump = _type(client, fx, f"pump_{tag}", {"name": "string"})
    job = _type(client, fx, f"job_{tag}", {"pump_id": "string", "started": "timestamp",
                                           "finished": "timestamp", "due": "date",
                                           "note": "string"})
    _sync(client, fx, pump, _upload(client, fx, f"Pumps {tag}", PUMPS), "pump_id", ["name"])
    _sync(client, fx, job, _upload(client, fx, f"Jobs {tag}", JOBS), "job_id",
          ["pump_id", "started", "finished", "due", "note"])
    r = client.post(f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub),
                    json={"api_name": f"serviced_{tag}", "display_name": "Serviced",
                          "from_type_id": job, "to_type_id": pump, "cardinality": "one_to_many",
                          "from_property": "pump_id", "to_property": "$primary_key"})
    assert r.status_code == 201, r.text
    r2 = client.get(f"{wbase(fx)}/object-types/{pump}/instances", headers=hdr(fx.viewer_sub))
    ids = {i["primary_key"]: i["id"] for i in r2.json()["items"]}
    return {"pump": pump, "job": job, "link": r.json()["id"], "P1": ids["P1"], "P2": ids["P2"]}


def events(client: TestClient, fx: Fixture, pumps: dict, pump: str = "P1", **params):
    query = {"link": pumps["link"], "direction": "inbound", "start": "started",
             "end": "finished", **params}
    return client.get(
        f"{wbase(fx)}/object-types/{pumps['pump']}/instances/{pumps[pump]}/linked-events",
        headers=hdr(fx.viewer_sub), params={k: v for k, v in query.items() if v is not None})


def spans(body: dict) -> list[tuple[str, str]]:
    return [(e["start"][:16], e["end"][:16]) for e in body["events"]]


def test_each_linked_object_is_an_event_from_its_start_to_its_end(client, fx, pumps) -> None:
    r = events(client, fx, pumps)
    assert r.status_code == 200, r.text
    body = r.json()
    # In time order; J2's blank finish makes it a moment, J3's pair is read
    # as the span it names, and J4 with no start is no event.
    assert spans(body) == [("2026-01-02T00:00", "2026-01-03T12:00"),
                           ("2026-01-05T06:00", "2026-01-05T06:00"),
                           ("2026-01-07T00:00", "2026-01-08T00:00"),
                           ("2026-01-10T00:00", "2026-01-10T02:00")]
    assert (body["total"], body["truncated"], body["unreadable"]) == (5, False, 1)
    # A moment with no zone is UTC, so a browser anywhere reads the same one.
    assert body["events"][0]["start"] == "2026-01-02T00:00:00Z"
    # One with a zone is the same moment: four o'clock two hours ahead is two
    # UTC.
    assert body["events"][-1]["end"] == "2026-01-10T02:00:00Z"
    # Another pump's jobs are its own.
    assert spans(events(client, fx, pumps, pump="P2").json()) == [
        ("2026-01-01T00:00", "2026-01-01T01:00")]


def test_without_an_end_each_event_is_a_moment_and_a_date_is_its_midnight(client, fx, pumps) -> None:
    body = events(client, fx, pumps, start="due", end=None).json()
    assert spans(body) == [("2026-01-02T00:00", "2026-01-02T00:00"),
                           ("2026-01-05T00:00", "2026-01-05T00:00")]
    assert body["unreadable"] == 3


def test_the_linked_objects_read_are_bounded(client, fx, pumps, monkeypatch) -> None:
    monkeypatch.setattr(object_routes, "MAX_LINKED_EVENTS", 2)
    body = events(client, fx, pumps).json()
    assert (body["total"], body["truncated"]) == (5, True)
    assert len(body["events"]) + body["unreadable"] == 2


@pytest.mark.parametrize("params, status, said", [
    ({"start": "note"}, 422, "the start is a timestamp or date property of"),
    ({"end": "pump_id"}, 422, "the end is a timestamp or date property of"),
    ({"start": "gone"}, 422, "'gone' is not one"),
    ({"direction": "sideways"}, 422, "the direction is outbound or inbound"),
    # The job links *to* the pump, so from the pump it runs inbound.
    ({"direction": "outbound"}, 404, "link from this object type"),
])
def test_what_cannot_be_read_as_events_is_said(client, fx, pumps, params, status, said) -> None:
    r = events(client, fx, pumps, **params)
    assert r.status_code == status, r.text
    assert said in r.json()["detail"]


def test_an_unknown_link_or_object_is_not_found(client, fx, pumps) -> None:
    assert events(client, fx, {**pumps, "link": str(uuid.uuid4())}).status_code == 404
    assert events(client, fx, {**pumps, "P1": str(uuid.uuid4())}).status_code == 404


def test_a_link_that_cannot_be_followed_is_said(client, fx, pumps, monkeypatch) -> None:
    """A join-table link whose table has changed (§552) says why, rather than
    reading as a pump with no jobs."""
    async def broken(*_args):
        return None, [], 0, "the join table has no column 'pump'"
    monkeypatch.setattr(object_routes, "_follow_link", broken)
    r = events(client, fx, pumps)
    assert r.status_code == 422 and r.json()["detail"] == "the join table has no column 'pump'"
