"""Many-to-many link types backed by a join table dataset (§552; db 0115;
`object-link-types` p.200, p.197).

    "Join table dataset: For "many-to-many" cardinality link types. This option
     allows you to use a join table dataset to back the link." (p.197)

    "In a many-to-many cardinality, select a datasource that includes all
     combinations of links between the primary key of the first object type
     (Aircraft in our example) and the second object type (Flight in our
     example)." (p.200)

p.200's own example. Flight F2 was flown by two aircraft, which is the thing a
foreign key cannot say; A3 flew nothing, so Has link has one to leave out.
The join table's aircraft column is an integer, as an upload infers it, while
the aircraft keys are text everywhere else - so the pairs are compared as text
or the link follows to nothing.
"""
from __future__ import annotations

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

ADMIN_DSN = os.environ.get(
    "TEST_ADMIN_DSN",
    "postgresql://platform:devpass@localhost:5432/platform?sslmode=disable",
)


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


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


def pbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


def upload(client, fx, name: str, csv: bytes) -> str:
    r = client.post(
        f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        files={"file": (f"{name}.csv", csv, "text/csv")}, data={"name": name},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def object_type(client, fx, name: str, csv: bytes, properties: list[str]) -> str:
    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": name, "display_name": name,
              "properties": [{"api_name": p, "data_type": "string"} for p in properties]},
    )
    assert r.status_code == 201, r.text
    type_id = r.json()["id"]
    source = client.post(
        f"{pbase(fx)}/object-type-sources", headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "dataset_id": upload(client, fx, name, csv),
              "primary_key_column": "id", "column_mappings": {p: p for p in properties}},
    )
    assert source.status_code == 201, source.text
    synced = client.post(
        f"{pbase(fx)}/object-type-sources/{source.json()['id']}/sync",
        headers=hdr(fx.editor_sub), json={},
    )
    assert synced.status_code == 200 and synced.json()["ok"], synced.text
    return type_id


PAIRS = b"flight,aircraft\nF1,1\nF2,1\nF2,2\nF3,2\n"


@pytest.fixture(scope="module")
def world(client: TestClient, fx: Fixture) -> dict:
    tag = uuid.uuid4().hex[:6]
    aircraft = object_type(client, fx, f"aircraft_{tag}",
                           b"id,tail\n1,G-AAAA\n2,G-BBBB\n3,G-CCCC\n", ["tail"])
    flights = object_type(client, fx, f"flight_{tag}",
                          b"id,route\nF1,LHR-JFK\nF2,JFK-SFO\nF3,SFO-LHR\nF4,LHR-CDG\n",
                          ["route"])
    pairs = upload(client, fx, f"flown_{tag}", PAIRS)
    r = client.post(f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"flown_by_{tag}", "display_name": "Flown by",
        "from_type_id": flights, "to_type_id": aircraft, "cardinality": "many_to_many",
        "join_dataset_id": pairs, "join_from_column": "flight",
        "join_to_column": "aircraft",
    })
    assert r.status_code == 201, r.text
    return {"aircraft": aircraft, "flights": flights, "pairs": pairs,
            "link": r.json()["id"], "tag": tag}


def instance(client, fx, type_id: str, key: str) -> dict:
    r = client.get(f"{wbase(fx)}/object-types/{type_id}/instances",
                   headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return next(i for i in r.json()["items"] if i["primary_key"] == key)


def links_of(client, fx, type_id: str, key: str) -> dict:
    thing = instance(client, fx, type_id, key)
    r = client.get(f"{wbase(fx)}/object-types/{type_id}/instances/{thing['id']}/links",
                   headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return {g["link_type_id"]: g for g in r.json()}


def keys_of(client, fx, definition: dict) -> list[str]:
    r = client.post(f"{wbase(fx)}/object-sets/evaluate", headers=hdr(fx.editor_sub),
                    json={"definition": definition, "limit": 50, "offset": 0})
    assert r.status_code == 200, r.text
    return sorted(i["primary_key"] for i in r.json()["instances"])


def key_is(type_id: str, *keys: str) -> dict:
    return {"object_type_id": type_id,
            "filters": [{"property": "$primary_key", "op": "in", "value": list(keys)}]}


# ---- defining one ------------------------------------------------------------

def test_the_link_type_names_its_join_table(client, fx, world) -> None:
    r = client.get(f"{wbase(fx)}/link-types", headers=hdr(fx.viewer_sub))
    link = next(lt for lt in r.json() if lt["id"] == world["link"])
    assert (link["join_dataset_id"], link["join_from_column"], link["join_to_column"],
            link["from_property"]) == (world["pairs"], "flight", "aircraft", None), link


def refused(client, fx, world, **changes) -> str:
    body = {"api_name": f"x_{uuid.uuid4().hex[:6]}", "display_name": "X",
            "from_type_id": world["flights"], "to_type_id": world["aircraft"],
            "cardinality": "many_to_many", "join_dataset_id": world["pairs"],
            "join_from_column": "flight", "join_to_column": "aircraft", **changes}
    r = client.post(f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub), json=body)
    assert r.status_code in (404, 422), r.text
    return r.json()["detail"] if isinstance(r.json()["detail"], str) else str(r.json())


@pytest.mark.parametrize("changes, says", [
    # p.197: "Join table dataset: For "many-to-many" cardinality link types."
    ({"cardinality": "one_to_many"}, "a join table backs a many-to-many link"),
    ({"from_property": "route", "to_property": "$primary_key"}, "not both"),
    ({"join_to_column": "wing"}, "no column 'wing' (its columns: flight, aircraft)"),
    # p.200: "A column can only be mapped to one primary key."
    ({"join_to_column": "flight"}, "its own column"),
    ({"join_to_column": None}, "one column cannot pair anything"),
    ({"join_dataset_id": None}, "one column cannot pair anything"),
])
def test_a_join_table_is_checked_when_it_is_defined(client, fx, world, changes, says) -> None:
    assert says in refused(client, fx, world, **changes)


def test_a_join_table_in_no_dataset_is_not_found(client, fx, world) -> None:
    r = client.post(f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"y_{uuid.uuid4().hex[:6]}", "display_name": "Y",
        "from_type_id": world["flights"], "to_type_id": world["aircraft"],
        "cardinality": "many_to_many", "join_dataset_id": str(uuid.uuid4()),
        "join_from_column": "flight", "join_to_column": "aircraft"})
    assert r.status_code == 404, r.text


def test_the_type_lists_it_from_both_ends_by_primary_key(client, fx, world) -> None:
    for type_id in (world["flights"], world["aircraft"]):
        r = client.get(f"{wbase(fx)}/object-types/{type_id}/links", headers=hdr(fx.viewer_sub))
        link = next(lt for lt in r.json() if lt["link_type_id"] == world["link"])
        assert (link["join_table"], link["near_property"], link["far_property"]) == (
            True, "$primary_key", "$primary_key"), link


# ---- following one -----------------------------------------------------------

def test_an_object_shows_what_its_join_table_pairs_it_with(client, fx, world) -> None:
    """The flight two aircraft flew, from the flight; and from an aircraft,
    back the other way through the same pairs."""
    group = links_of(client, fx, world["flights"], "F2")[world["link"]]
    assert sorted(i["primary_key"] for i in group["items"]) == ["1", "2"]
    assert (group["total"], group["join_table"], group["problem"]) == (2, True, None)
    group = links_of(client, fx, world["aircraft"], "1")[world["link"]]
    assert sorted(i["primary_key"] for i in group["items"]) == ["F1", "F2"]
    assert links_of(client, fx, world["aircraft"], "3")[world["link"]]["total"] == 0


def test_a_hop_through_the_join_table(client, fx, world) -> None:
    flights_of_1 = {"object_type_id": world["flights"],
                    "via": {"link_type_id": world["link"], "base": key_is(world["aircraft"], "1")}}
    assert keys_of(client, fx, flights_of_1) == ["F1", "F2"]
    aircraft_of = {"object_type_id": world["aircraft"],
                   "via": {"link_type_id": world["link"],
                           "base": key_is(world["flights"], "F1", "F3")}}
    assert keys_of(client, fx, aircraft_of) == ["1", "2"]
    # A base with nothing paired - F4 flew with no aircraft - is the empty set.
    nobody = {"object_type_id": world["aircraft"],
              "via": {"link_type_id": world["link"], "base": key_is(world["flights"], "F4")}}
    assert keys_of(client, fx, nobody) == []


def test_filters_on_linked_objects_go_through_it_backwards(client, fx, world) -> None:
    """p.451's Has link, and a linked filter, read back through the pairs."""
    def linked(type_id: str, filters: list) -> dict:
        return {"object_type_id": type_id, "filters": [
            {"property": world["link"], "op": "has_link", "value": {"filters": filters}}]}
    assert keys_of(client, fx, linked(world["aircraft"], [])) == ["1", "2"]
    assert keys_of(client, fx, linked(world["flights"], [])) == ["F1", "F2", "F3"]
    assert keys_of(client, fx, linked(world["aircraft"], [
        {"property": "route", "op": "eq", "value": "SFO-LHR"}])) == ["2"]


def test_a_derived_property_counts_through_it(client, fx, world) -> None:
    """A derivation's hops are a traversal (§406), so a join-table link is one
    it can follow - the check that refuses an unjoined link lets it through."""
    r = client.get(f"{wbase(fx)}/object-types/{world['aircraft']}", headers=hdr(fx.editor_sub))
    detail = r.json()
    keep = [dict(p) for p in detail["properties"] if p["derivation"] is None]
    r = client.patch(f"{wbase(fx)}/object-types/{world['aircraft']}", headers=hdr(fx.editor_sub),
                     json={"display_name": detail["display_name"],
                           "title_property": detail.get("title_property"),
                           "properties": keep + [{
                               "api_name": "flights_flown", "display_name": "Flights flown",
                               "data_type": "integer",
                               "derivation": {"links": [world["link"]], "aggregate": "count"}}]})
    assert r.status_code == 200, r.text
    got = instance(client, fx, world["aircraft"], "2")
    r = client.get(f"{wbase(fx)}/object-types/{world['aircraft']}/instances/{got['id']}",
                   headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    assert r.json()["properties"]["flights_flown"] == 2, r.json()


# ---- when the join table changes --------------------------------------------

def test_a_column_gone_is_said_in_its_own_group(client, fx, world) -> None:
    """A join table rebuilt without the column the link names: that group says
    so, and the object's other links are unaffected."""
    with psycopg.connect(ADMIN_DSN, autocommit=True) as db:
        db.execute("UPDATE link_types SET join_from_column = 'flight_no' WHERE id = %s",
                   (world["link"],))
        try:
            group = links_of(client, fx, world["flights"], "F2")[world["link"]]
            r = client.post(f"{wbase(fx)}/object-sets/evaluate", headers=hdr(fx.editor_sub),
                            json={"definition": {"object_type_id": world["aircraft"], "via": {
                                "link_type_id": world["link"],
                                "base": key_is(world["flights"], "F2")}},
                                "limit": 50, "offset": 0})
        finally:
            db.execute("UPDATE link_types SET join_from_column = 'flight' WHERE id = %s",
                       (world["link"],))
    assert group["total"] == 0 and "no column 'flight_no'" in group["problem"], group
    assert r.status_code == 422 and "no column 'flight_no'" in r.json()["detail"], r.text


def test_a_patch_moves_a_link_between_a_join_table_and_a_pair(client, fx, world) -> None:
    tag = uuid.uuid4().hex[:6]
    made = client.post(f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"moved_{tag}", "display_name": "Moved", "from_type_id": world["flights"],
        "to_type_id": world["aircraft"], "cardinality": "many_to_many"}).json()
    r = client.patch(f"{wbase(fx)}/link-types/{made['id']}", headers=hdr(fx.editor_sub), json={
        "join_dataset_id": world["pairs"], "join_from_column": "flight",
        "join_to_column": "aircraft"})
    assert r.status_code == 200 and r.json()["join_to_column"] == "aircraft", r.text
    group = links_of(client, fx, world["flights"], "F3")[made["id"]]
    assert [i["primary_key"] for i in group["items"]] == ["2"]
    r = client.patch(f"{wbase(fx)}/link-types/{made['id']}", headers=hdr(fx.editor_sub), json={
        "from_property": "route", "to_property": "tail"})
    assert r.status_code == 200, r.text
    assert (r.json()["join_dataset_id"], r.json()["from_property"]) == (None, "route")


def test_an_import_keeps_the_join_table_its_file_cannot_name(client, fx, world) -> None:
    """An ontology file carries no dataset ids (§326), so importing it over a
    join-table link must leave the join table be rather than clear it."""
    r = client.get(f"{wbase(fx)}/ontology-export", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    document = r.json()
    # Changed, so the import writes this link rather than skipping it as it
    # skips an unchanged one.
    link = next(lt for lt in document["link_types"]
                if lt["api_name"] == f"flown_by_{world['tag']}")
    link["to_side_name"] = "Aircraft flown"
    r = client.post(f"{wbase(fx)}/ontology-import", headers=hdr(fx.editor_sub),
                    json={"document": document})
    assert r.status_code == 200, r.text
    r = client.get(f"{wbase(fx)}/link-types", headers=hdr(fx.viewer_sub))
    assert next(lt for lt in r.json() if lt["id"] == world["link"])["to_side_name"] == (
        "Aircraft flown")
    group = links_of(client, fx, world["flights"], "F2")[world["link"]]
    assert group["total"] == 2, group


def test_deleting_the_dataset_leaves_the_link_untraversable(client, fx, world) -> None:
    """db 0115: the link is still a statement about the ontology; its columns
    stay, saying what it was joined on, and it is not followed."""
    tag = uuid.uuid4().hex[:6]
    spare = upload(client, fx, f"spare_{tag}", PAIRS)
    made = client.post(f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"spare_{tag}", "display_name": "Spare", "from_type_id": world["flights"],
        "to_type_id": world["aircraft"], "cardinality": "many_to_many",
        "join_dataset_id": spare, "join_from_column": "flight",
        "join_to_column": "aircraft"}).json()
    r = client.delete(f"{pbase(fx)}/datasets/{spare}", headers=hdr(fx.editor_sub))
    assert r.status_code == 204, r.text
    r = client.get(f"{wbase(fx)}/link-types", headers=hdr(fx.viewer_sub))
    link = next(lt for lt in r.json() if lt["id"] == made["id"])
    assert (link["join_dataset_id"], link["join_from_column"]) == (None, "flight"), link
    assert made["id"] not in links_of(client, fx, world["flights"], "F2")


# ---- the reading, without a database ----------------------------------------

def pairs_file(tmp_path, rows: str) -> str:
    import duckdb
    path = str(tmp_path / "pairs.parquet")
    duckdb.sql(f"COPY (SELECT * FROM (VALUES {rows}) t(f, a)) TO '{path}' (FORMAT parquet)")
    return path


def test_a_pair_with_an_empty_side_links_nothing(tmp_path) -> None:
    from src.services import dataset_engine as engine
    path = pairs_file(tmp_path, "(1, 'a'), (1, NULL), (NULL, 'b')")
    assert engine.join_keys(path, "f", "a", ["1"], 10) == ["a"]
    assert engine.join_keys(path, "a", "f", ["b"], 10) == []


def test_a_repeated_pair_does_not_count_against_the_limit(tmp_path) -> None:
    """At the cap the traversal is refused; a duplicate counted towards it
    would return a prefix instead."""
    from src.services import dataset_engine as engine
    path = pairs_file(tmp_path, "(1, 'a'), (1, 'a'), (1, 'a'), (1, 'b')")
    assert sorted(engine.join_keys(path, "f", "a", ["1"], 2)) == ["a", "b"]
    assert len(engine.join_keys(path, "f", "a", ["1"], 1)) == 1


def test_a_traversal_past_the_cap_is_refused_before_the_table_is_read() -> None:
    import anyio
    from src.services import link_join_tables, object_sets

    class Untouchable:
        async def execute(self, *a, **k):  # pragma: no cover - the claim
            raise AssertionError("read the join table for a traversal it should refuse")

    keys = [str(i) for i in range(object_sets.MAX_JOIN_VALUES + 1)]
    join = {"dataset_id": str(uuid.uuid4()), "near_column": "f", "far_column": "a"}
    with pytest.raises(ValueError, match=f"limit is {object_sets.MAX_JOIN_VALUES}"):
        anyio.run(link_join_tables.follow, Untouchable(), join, keys)


def test_a_join_table_the_reader_cannot_see_is_said(client, fx, world) -> None:
    """RLS keeps the dataset from a reader outside its project; the link's
    group says why it cannot be followed rather than showing no objects."""
    tag = uuid.uuid4().hex[:6]
    with psycopg.connect(ADMIN_DSN, autocommit=True) as db:
        hidden = db.execute(
            "INSERT INTO projects (workspace_id, name, slug, created_by, permission_mode) "
            "VALUES (%s, %s, %s, %s, 'custom') RETURNING id",
            (fx.workspace, f"Hidden {tag}", f"hidden-{tag}", fx.owner),
        ).fetchone()[0]
    r = client.post(
        f"{wbase(fx)}/projects/{hidden}/datasets/upload", headers=hdr(fx.admin_sub),
        files={"file": ("pairs.csv", PAIRS, "text/csv")}, data={"name": f"hidden_{tag}"},
    )
    assert r.status_code == 201, r.text
    made = client.post(f"{wbase(fx)}/link-types", headers=hdr(fx.admin_sub), json={
        "api_name": f"hidden_{tag}", "display_name": "Hidden", "from_type_id": world["flights"],
        "to_type_id": world["aircraft"], "cardinality": "many_to_many",
        "join_dataset_id": r.json()["id"], "join_from_column": "flight",
        "join_to_column": "aircraft"})
    assert made.status_code == 201, made.text
    group = links_of(client, fx, world["flights"], "F2")[made.json()["id"]]
    assert group["total"] == 0 and "a dataset you cannot read" in group["problem"], group
