"""Tags, and the resources that carry them (§511; db 0105).

> "About: Information including … tags, and more." (`dataset-preview` p.3)

> "You can create and manage tags from the Tags section of Platform Settings.
> Once they are created, they can be added to a promoted app on the promotion
> UI, as well as in the filesystem." (`app-building` p.35)
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

from test_api import ADMIN_DSN, Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("tags-storage"))))
    with TestClient(create_app(), raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def tags_url(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/tags"


def on_url(fx: Fixture, rid: str, tid: str | None = None) -> str:
    return f"/api/workspaces/{fx.workspace}/resource-tags/{rid}" + (f"/{tid}" if tid else "")


def make_tag(client, fx, name: str, category: str = "") -> dict:
    r = client.post(tags_url(fx), headers=hdr(fx.admin_sub), json={"name": name, "category": category})
    assert r.status_code == 201, r.text
    return r.json()


def dataset_resource(client, fx) -> str:
    r = client.post(f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets/upload",
                    headers=hdr(fx.editor_sub), data={"name": f"Tagged {uuid.uuid4().hex[:6]}"},
                    files={"file": ("rows.csv", io.BytesIO(b"id\n1\n"), "text/csv")})
    assert r.status_code == 201, r.text
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        return str(conn.execute("SELECT resource_id FROM datasets WHERE id = %s",
                                (r.json()["id"],)).fetchone()[0])


def names(tags: list[dict]) -> list[tuple[str, str]]:
    return [(t["category"], t["name"]) for t in tags]


def test_an_admin_makes_tags_and_everybody_sees_them(client, fx) -> None:
    tag = uuid.uuid4().hex[:6]
    made = make_tag(client, fx, f"  Gold   {tag} ", "Quality")
    # Spaces are tidied, so " Gold " and "Gold" are one tag.
    assert (made["category"], made["name"], made["uses"]) == ("Quality", f"Gold {tag}", 0)
    listed = client.get(tags_url(fx), headers=hdr(fx.viewer_sub))
    assert listed.status_code == 200
    assert ("Quality", f"Gold {tag}") in names(listed.json())
    # Making one is the administrator's (p.35's Platform Settings).
    for sub in (fx.editor_sub, fx.viewer_sub):
        r = client.post(tags_url(fx), headers=hdr(sub), json={"name": f"Nope {tag}"})
        assert r.status_code == 403, r.text
    assert client.get(tags_url(fx), headers=hdr(fx.outsider_sub)).status_code in (403, 404)


def test_tags_list_by_category_then_name_ignoring_case(client, fx) -> None:
    tag = uuid.uuid4().hex[:6]
    for category, name in (("zeta", f"b {tag}"), ("", f"B2 {tag}"), ("Alpha", f"c {tag}"),
                           ("alpha", f"A {tag}")):
        make_tag(client, fx, name, category)
    mine = [t for t in names(client.get(tags_url(fx), headers=hdr(fx.viewer_sub)).json())
            if t[1].endswith(tag)]
    assert mine == [("", f"B2 {tag}"), ("alpha", f"A {tag}"), ("Alpha", f"c {tag}"),
                    ("zeta", f"b {tag}")]


def test_one_name_per_category_whatever_the_case(client, fx) -> None:
    tag = uuid.uuid4().hex[:6]
    make_tag(client, fx, f"PII {tag}", "Sensitivity")
    r = client.post(tags_url(fx), headers=hdr(fx.admin_sub),
                    json={"name": f"pii {tag}", "category": "sensitivity"})
    assert r.status_code == 409
    assert r.json()["detail"] == f"there is already a tag called 'pii {tag}' in 'sensitivity'"
    r = client.post(tags_url(fx), headers=hdr(fx.admin_sub), json={"name": f"pii {tag}"})
    assert r.status_code == 201, "another category is another tag"
    r = client.post(tags_url(fx), headers=hdr(fx.admin_sub), json={"name": f"PII {tag}"})
    assert r.json()["detail"] == f"there is already a tag called 'PII {tag}'"
    # And the connection is still usable after the refusal.
    assert client.get(tags_url(fx), headers=hdr(fx.viewer_sub)).status_code == 200


def test_a_blank_name_is_refused(client, fx) -> None:
    r = client.post(tags_url(fx), headers=hdr(fx.admin_sub), json={"name": "   "})
    assert r.status_code == 422


def test_tagging_a_resource_and_counting_its_uses(client, fx) -> None:
    tag = uuid.uuid4().hex[:6]
    gold, silver = make_tag(client, fx, f"Gold {tag}"), make_tag(client, fx, f"Silver {tag}")
    rid = dataset_resource(client, fx)
    r = client.put(on_url(fx, rid, silver["id"]), headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    r = client.put(on_url(fx, rid, gold["id"]), headers=hdr(fx.editor_sub))
    assert names(r.json()) == [("", f"Gold {tag}"), ("", f"Silver {tag}")]
    # Twice is the same tag.
    r = client.put(on_url(fx, rid, gold["id"]), headers=hdr(fx.editor_sub))
    assert len(r.json()) == 2
    assert names(client.get(on_url(fx, rid), headers=hdr(fx.viewer_sub)).json()) == names(r.json())
    uses = {t["name"]: t["uses"] for t in client.get(tags_url(fx), headers=hdr(fx.viewer_sub)).json()}
    assert (uses[f"Gold {tag}"], uses[f"Silver {tag}"]) == (1, 1)

    r = client.delete(on_url(fx, rid, gold["id"]), headers=hdr(fx.editor_sub))
    assert r.status_code == 200 and names(r.json()) == [("", f"Silver {tag}")]


def test_applying_a_tag_is_an_editor_s(client, fx) -> None:
    tag = make_tag(client, fx, f"Guarded {uuid.uuid4().hex[:6]}")
    rid = dataset_resource(client, fx)
    r = client.put(on_url(fx, rid, tag["id"]), headers=hdr(fx.viewer_sub))
    assert r.status_code == 403 and r.json()["detail"] == "project editor role required"
    client.put(on_url(fx, rid, tag["id"]), headers=hdr(fx.editor_sub))
    r = client.delete(on_url(fx, rid, tag["id"]), headers=hdr(fx.viewer_sub))
    assert r.status_code == 403
    assert len(client.get(on_url(fx, rid), headers=hdr(fx.viewer_sub)).json()) == 1


def test_a_workspace_level_resource_needs_a_workspace_editor(client, fx) -> None:
    tag = make_tag(client, fx, f"Types {uuid.uuid4().hex[:6]}")
    r = client.post(f"/api/workspaces/{fx.workspace}/object-types", headers=hdr(fx.editor_sub),
                    json={"api_name": f"Thing{uuid.uuid4().hex[:6]}", "display_name": "Thing",
                          "properties": [{"api_name": "note", "data_type": "string"}]})
    assert r.status_code == 201, r.text
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        rid = str(conn.execute("SELECT resource_id FROM object_types WHERE id = %s",
                               (r.json()["id"],)).fetchone()[0])
    r = client.put(on_url(fx, rid, tag["id"]), headers=hdr(fx.viewer_sub))
    assert r.status_code == 403 and r.json()["detail"] == "workspace editor role required"
    assert client.put(on_url(fx, rid, tag["id"]), headers=hdr(fx.editor_sub)).status_code == 200


def test_a_tag_or_resource_from_elsewhere_is_not_found(client, fx) -> None:
    other = Fixture()
    foreign_tag = client.post(f"/api/workspaces/{other.workspace}/tags", headers=hdr(other.admin_sub),
                              json={"name": "Theirs"}).json()
    rid = dataset_resource(client, fx)
    r = client.put(on_url(fx, rid, foreign_tag["id"]), headers=hdr(fx.editor_sub))
    assert r.status_code == 404 and r.json()["detail"] == "tag not found"
    assert client.put(on_url(fx, rid, str(uuid.uuid4())), headers=hdr(fx.editor_sub)).status_code == 404
    mine = make_tag(client, fx, f"Mine {uuid.uuid4().hex[:6]}")
    assert client.put(on_url(fx, str(uuid.uuid4()), mine["id"]),
                      headers=hdr(fx.editor_sub)).status_code == 404
    # A resource in a workspace the caller can see, reached through another's path.
    their_rid = dataset_resource(client, other)
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("INSERT INTO workspace_members (workspace_id, user_id, role) VALUES (%s, %s, 'editor')",
                     (other.workspace, fx.editor))
    r = client.put(on_url(fx, their_rid, mine["id"]), headers=hdr(fx.editor_sub))
    assert r.status_code == 404 and r.json()["detail"] == "resource not found"
    assert client.get(on_url(fx, their_rid), headers=hdr(fx.editor_sub)).status_code == 404


def test_renaming_a_tag_renames_it_everywhere(client, fx) -> None:
    tag = uuid.uuid4().hex[:6]
    made = make_tag(client, fx, f"Draft {tag}")
    rid = dataset_resource(client, fx)
    client.put(on_url(fx, rid, made["id"]), headers=hdr(fx.editor_sub))
    r = client.patch(f"{tags_url(fx)}/{made['id']}", headers=hdr(fx.admin_sub),
                     json={"name": f"Final {tag}", "category": "State"})
    assert r.status_code == 200, r.text
    assert (r.json()["category"], r.json()["name"], r.json()["uses"]) == ("State", f"Final {tag}", 1)
    assert names(client.get(on_url(fx, rid), headers=hdr(fx.viewer_sub)).json()) == [
        ("State", f"Final {tag}")]
    make_tag(client, fx, f"Taken {tag}", "State")
    r = client.patch(f"{tags_url(fx)}/{made['id']}", headers=hdr(fx.admin_sub),
                     json={"name": f"taken {tag}", "category": "state"})
    assert r.status_code == 409
    assert client.patch(f"{tags_url(fx)}/{uuid.uuid4()}", headers=hdr(fx.admin_sub),
                        json={"name": "x"}).status_code == 404
    assert client.patch(f"{tags_url(fx)}/{made['id']}", headers=hdr(fx.editor_sub),
                        json={"name": "x"}).status_code == 403


def test_deleting_a_tag_takes_it_off_everything(client, fx) -> None:
    made = make_tag(client, fx, f"Gone {uuid.uuid4().hex[:6]}")
    rid = dataset_resource(client, fx)
    client.put(on_url(fx, rid, made["id"]), headers=hdr(fx.editor_sub))
    assert client.delete(f"{tags_url(fx)}/{made['id']}", headers=hdr(fx.editor_sub)).status_code == 403
    assert client.delete(f"{tags_url(fx)}/{made['id']}", headers=hdr(fx.admin_sub)).status_code == 204
    assert client.get(on_url(fx, rid), headers=hdr(fx.viewer_sub)).json() == []
    assert client.delete(f"{tags_url(fx)}/{made['id']}", headers=hdr(fx.admin_sub)).status_code == 404


def test_a_tag_is_changed_only_through_its_own_workspace(client, fx) -> None:
    """The org admin sees both workspaces, so only the path keeps a tag in
    one from being renamed or deleted through the other."""
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        wid = uuid.uuid4()
        conn.execute(
            """INSERT INTO workspaces (id, organisation_id, name, slug, s3_prefix, pg_schema,
                                       search_prefix, created_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (wid, fx.org, f"Second {wid.hex[:6]}", f"second-{wid.hex[:6]}",
             f"workspaces/second-{wid.hex[:6]}/", f"ws_{wid.hex[:12]}", f"ws-{wid.hex[:12]}-",
             fx.owner))
    r = client.post(f"/api/workspaces/{wid}/tags", headers=hdr(fx.admin_sub), json={"name": "Theirs"})
    assert r.status_code == 201, r.text
    theirs = r.json()["id"]
    assert client.patch(f"{tags_url(fx)}/{theirs}", headers=hdr(fx.admin_sub),
                        json={"name": "Hijacked"}).status_code == 404
    assert client.delete(f"{tags_url(fx)}/{theirs}", headers=hdr(fx.admin_sub)).status_code == 404
    listed = client.get(f"/api/workspaces/{wid}/tags", headers=hdr(fx.admin_sub)).json()
    assert [t["name"] for t in listed] == ["Theirs"]


def test_a_rename_is_tidied_like_a_new_tag(client, fx) -> None:
    made = make_tag(client, fx, f"Rough {uuid.uuid4().hex[:6]}")
    r = client.patch(f"{tags_url(fx)}/{made['id']}", headers=hdr(fx.admin_sub),
                     json={"name": "  Smooth   now ", "category": " Finish  line "})
    assert (r.json()["category"], r.json()["name"]) == ("Finish line", "Smooth now")
