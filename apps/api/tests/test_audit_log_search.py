"""The audit log, narrowed the way an investigation narrows it (§988).

Every change the platform makes is recorded (db 0004), and the only way to
read it was the newest fifty at a time, by offset, with nothing to say where
a request came from. These hold the filters - an action or a family of them,
a person, a resource, a workspace, a span of time - the cursor that pages
without rereading everything before it, and the address and agent each
entry was recorded with.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402

ADMIN_DSN = os.environ["TEST_ADMIN_DSN"]
NOW = datetime.now(timezone.utc)


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    auth_mw.configure_verifier(LocalVerifier())
    with TestClient(create_app(), raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


@pytest.fixture(scope="module")
def logged() -> dict:
    """An org's log: who did what, to what, where from, and when."""
    fx = Fixture()
    resource = uuid.uuid4()
    entries = [
        # (action, user, resource, days ago, address)
        ("dataset.create", fx.editor, resource, 9, "10.0.0.1"),
        ("dataset.export", fx.viewer, resource, 5, "10.0.0.2"),
        ("dataset.export", fx.editor, None, 3, "10.0.0.3"),
        ("model.run", fx.editor, None, 2, None),
        ("connection_sync", fx.admin, None, 1, "203.0.113.9"),
    ]
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        for action, user, rid, days, ip in entries:
            conn.execute(
                """INSERT INTO audit_log (organisation_id, user_id, action, resource_type,
                                          resource_id, workspace_id, ip_address, user_agent,
                                          created_at)
                   VALUES (%s, %s, %s, 'dataset', %s, %s, %s, 'curl/8.5', %s)""",
                (fx.org, user, action, rid, fx.workspace, ip, NOW - timedelta(days=days)))
    return {"fx": fx, "resource": resource}


def search(client: TestClient, fx: Fixture, **params) -> list[dict]:
    r = client.get("/api/org/audit", headers=hdr(fx.admin_sub), params=params)
    assert r.status_code == 200, r.text
    return r.json()


def actions(entries: list[dict]) -> list[str]:
    return [e["action"] for e in entries]


def test_an_action_or_a_family_of_them(client, logged) -> None:
    fx = logged["fx"]
    assert actions(search(client, fx, action="dataset.export")) == ["dataset.export"] * 2
    assert actions(search(client, fx, action="dataset.")) == [
        "dataset.export", "dataset.export", "dataset.create"]
    # A wildcard in what was typed is the character, not a wildcard.
    assert search(client, fx, action="connection_") == search(client, fx, action="connection_sync")
    assert search(client, fx, action="connection%") == []


def test_a_person_a_resource_a_workspace(client, logged) -> None:
    fx = logged["fx"]
    assert actions(search(client, fx, user_id=str(fx.viewer))) == ["dataset.export"]
    assert actions(search(client, fx, resource_id=str(logged["resource"]))) == [
        "dataset.export", "dataset.create"]
    assert len(search(client, fx, workspace_id=str(fx.workspace))) == 5
    assert search(client, fx, workspace_id=str(uuid.uuid4())) == []


def test_a_span_of_time(client, logged) -> None:
    fx = logged["fx"]
    got = search(client, fx, since=(NOW - timedelta(days=4)).isoformat(),
                 until=(NOW - timedelta(days=1, hours=12)).isoformat())
    assert actions(got) == ["model.run", "dataset.export"]


def test_pages_follow_one_another_by_cursor(client, logged) -> None:
    fx = logged["fx"]
    first = search(client, fx, limit=2)
    second = search(client, fx, limit=2, before_id=first[-1]["id"])
    third = search(client, fx, limit=2, before_id=second[-1]["id"])
    seen = [e["id"] for e in first + second + third]
    assert seen == sorted(seen, reverse=True) and len(set(seen)) == 5
    assert actions(first + second + third) == actions(search(client, fx))


def test_each_entry_says_where_it_came_from(client, logged) -> None:
    fx = logged["fx"]
    [entry] = search(client, fx, user_id=str(fx.admin))
    assert (entry["ip_address"], entry["user_agent"]) == ("203.0.113.9", "curl/8.5")
    [unknown] = search(client, fx, action="model.run")
    assert unknown["ip_address"] is None


def test_only_an_org_admin_reads_it(client, logged) -> None:
    fx = logged["fx"]
    r = client.get("/api/org/audit", headers=hdr(fx.editor_sub), params={"action": "dataset."})
    assert r.status_code == 403


# ---- the export (§989) ---------------------------------------------------------
def export(client: TestClient, fx: Fixture, who=None, **params):
    return client.get("/api/org/audit.csv", headers=hdr(who or fx.admin_sub), params=params)


def test_the_export_is_the_log_as_narrowed(client, logged) -> None:
    import csv
    import io

    fx = logged["fx"]
    r = export(client, fx, action="dataset.")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert 'filename="audit-log.csv"' in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert [row["action"] for row in rows] == ["dataset.export", "dataset.export", "dataset.create"]
    assert rows[0]["ip_address"] == "10.0.0.3" and rows[0]["user_agent"] == "curl/8.5"


def test_text_that_would_start_a_formula_is_read_not_run(client) -> None:
    """What an entry records was typed by people; a spreadsheet runs a cell
    that starts with `=`."""
    import csv
    import io

    fx = Fixture()
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            """INSERT INTO audit_log (organisation_id, user_id, action, resource_type, metadata,
                                      user_agent)
               VALUES (%s, %s, 'dataset.create', '=HYPERLINK("http://x")', '{"n": 1}', '+cmd')""",
            (fx.org, fx.editor))
    [row] = list(csv.DictReader(io.StringIO(export(client, fx).text)))
    assert row["resource_type"] == "'=HYPERLINK(\"http://x\")"
    assert row["user_agent"] == "'+cmd"
    assert row["metadata"] == '{"n": 1}'


def test_taking_a_copy_is_itself_recorded(client, logged) -> None:
    fx = logged["fx"]
    export(client, fx, action="model.")
    [entry] = search(client, fx, action="org.audit.export", limit=1)
    assert entry["metadata"] == {"entries": 1, "filters": {"action": "model."}}


def test_an_export_past_the_cap_is_refused_in_words(client, logged, monkeypatch) -> None:
    from src.services import orgs

    monkeypatch.setattr(orgs, "AUDIT_EXPORT_MAX", 2)
    r = export(client, logged["fx"], action="dataset.")
    assert r.status_code == 422
    assert r.json()["detail"] == "more than 2 entries match - narrow the search to export it"


def test_only_an_org_admin_takes_a_copy(client, logged) -> None:
    fx = logged["fx"]
    assert export(client, fx, who=fx.editor_sub).status_code == 403
