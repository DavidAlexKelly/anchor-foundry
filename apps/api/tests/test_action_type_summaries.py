"""Every action, as a picker offers it (§835).

`/action-type-summaries` is `/action-types` without the definitions: the
Workshop builder and an object type's related links loaded every parameter,
rule and criterion of every action to draw a label. It must say the same
things about the same actions, in the same order.
"""
from __future__ import annotations

import os
import sys
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import ADMIN_DSN, Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402

SUMMARY = ("id", "object_type_id", "interface_id", "subject_name", "api_name",
           "display_name", "status", "editable_properties")


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


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


@pytest.fixture(scope="module")
def actions(client: TestClient, fx: Fixture) -> list[str]:
    """Two object-type actions and one on an interface, whose subject is
    named by the interface and whose rules write a property of its own."""
    tag = uuid.uuid4().hex[:6]
    r = client.post(f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"Summ{tag}", "display_name": f"Summ {tag}",
        "properties": [{"api_name": "status", "data_type": "string"},
                       {"api_name": "owner", "data_type": "string"}]})
    assert r.status_code == 201, r.text
    type_id = r.json()["id"]
    made = []
    for name, props in ((f"close_{tag}", ["status"]), (f"assign_{tag}", ["owner", "status"])):
        r = client.post(f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub), json={
            "object_type_id": type_id, "api_name": name,
            "display_name": name.replace("_", " ").title(), "editable_properties": props})
        assert r.status_code == 201, r.text
        made.append(r.json()["id"])
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        interface = conn.execute(
            "INSERT INTO interfaces (workspace_id, api_name, display_name) "
            "VALUES (%s,%s,%s) RETURNING id",
            (fx.workspace, f"iface{tag}", f"Iface {tag}")).fetchone()[0]
        action = conn.execute(
            "INSERT INTO action_types (workspace_id, interface_id, api_name, display_name) "
            "VALUES (%s,%s,%s,%s) RETURNING id",
            (fx.workspace, interface, f"tag_{tag}", f"Tag {tag}")).fetchone()[0]
        conn.execute(
            "INSERT INTO action_rules (action_type_id, kind, config, sort_order) "
            "VALUES (%s,'modify_object','{\"property\": \"label\"}'::jsonb,0)", (action,))
    made.append(str(action))
    return made


def test_a_summary_is_the_full_listing_without_its_definitions(
    client: TestClient, fx: Fixture, actions: list[str]
) -> None:
    full = client.get(f"{wbase(fx)}/action-types", headers=hdr(fx.viewer_sub))
    summaries = client.get(f"{wbase(fx)}/action-type-summaries", headers=hdr(fx.viewer_sub))
    assert full.status_code == summaries.status_code == 200, summaries.text
    assert summaries.json() == [{k: a[k] for k in SUMMARY} for a in full.json()]
    # What that covers, said outright for the three made here.
    mine = {s["id"]: s for s in summaries.json() if s["id"] in actions}
    assert sorted(mine[actions[1]]["editable_properties"]) == ["owner", "status"]
    interface_action = mine[actions[2]]
    assert interface_action["object_type_id"] is None
    assert interface_action["subject_name"].startswith("Iface ")
    assert interface_action["editable_properties"] == ["label"]
    # And no definition rode along.
    assert "parameters" not in interface_action and "rules" not in interface_action


def test_only_a_workspace_member_reads_them(client: TestClient, fx: Fixture, actions) -> None:
    r = client.get(f"{wbase(fx)}/action-type-summaries", headers=hdr(fx.outsider_sub))
    assert r.status_code in (403, 404), r.text
