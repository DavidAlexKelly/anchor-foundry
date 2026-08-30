"""Link traversal tests (ROADMAP Objects item 3).

The feature's whole claim is that a link type stops being a type-level
statement and starts answering an instance-level question, so these tests are
written against the data shape the answer has to survive:

  * codes that are prefixes of each other (ENG / ENGW), because the store
    already had a `phrase_prefix` search and reusing it would have quietly
    returned the wrong objects;
  * a join whose two sides arrive with different types (an integer manager_id
    against a text primary key), because the two sides of a link are two
    independently-mapped datasets;
  * a null join value, which points at nothing rather than at everything
    whose value is also null;
  * a self-link, where outbound and inbound are genuinely different questions.

Every traversal assertion runs twice - once on Postgres, once on the
OpenSearch gateway over a real socket - because a link that traverses
differently depending on which store is configured is a link that is wrong on
one of them.
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import time
import urllib.request
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services import instance_store  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

PORT = 9211  # its own port: test_instance_store.py owns 9209
BASE = f"http://127.0.0.1:{PORT}"

PEOPLE = (
    b"employee_id,full_name,department,manager_id\n"
    b"1,Ada,ENG,\n"
    b"2,Grace,RES,1\n"
    b"3,Alan,ENG,1\n"
)
# ENGW exists to make "does the join match exactly" a real question: ENG is a
# prefix of ENGW, so a prefix or substring match would pull it in.
DEPARTMENTS = b"code,label\nENG,Engineering\nRES,Research\nENGW,Engineering West\n"


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("link-traversal")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


# ---- the OpenSearch half's fixture server -----------------------------------
@pytest.fixture(scope="module")
def opensearch() -> str:
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "opensearch_fixture_server.py")
    proc = subprocess.Popen([sys.executable, script, str(PORT)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            urllib.request.urlopen(f"{BASE}/", timeout=0.5).read()
            break
        except Exception:
            time.sleep(0.1)
    else:
        proc.terminate()
        pytest.fail("the OpenSearch fixture server did not start")
    yield BASE
    proc.terminate()
    proc.wait(timeout=5)


def _reset(base: str) -> None:
    urllib.request.urlopen(
        urllib.request.Request(f"{base}/__reset", method="POST", data=b""), timeout=2
    ).read()


@pytest.fixture(params=["postgres", "opensearch"])
def store(request: pytest.FixtureRequest):
    """Parametrised so every traversal assertion below runs against both
    stores without the test bodies knowing which one is behind them - which
    is the point of the gateway Protocol."""
    if request.param == "postgres":
        yield "postgres"
        return
    base = request.getfixturevalue("opensearch")
    _reset(base)
    instance_store.configure_instance_store(
        instance_store.OpenSearchInstanceStore(base, "admin", "admin")
    )
    yield "opensearch"
    instance_store.configure_instance_store(None)


# ---- ontology + data --------------------------------------------------------
def _wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


def _pbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


def _upload(client: TestClient, fx: Fixture, name: str, csv: bytes) -> str:
    r = client.post(
        f"{_pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": name}, files={"file": ("d.csv", io.BytesIO(csv), "text/csv")},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _type(client: TestClient, fx: Fixture, api_name: str, display: str, props: list[str]) -> str:
    r = client.post(
        f"{_wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": api_name, "display_name": display,
              "properties": [{"api_name": p, "data_type": "string"} for p in props]},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _map_and_sync(
    client: TestClient, fx: Fixture, type_id: str, dataset: str, pk: str, cols: dict[str, str]
) -> str:
    r = client.post(
        f"{_pbase(fx)}/object-type-sources", headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "dataset_id": dataset,
              "primary_key_column": pk, "column_mappings": cols},
    )
    assert r.status_code == 201, r.text
    source_id = r.json()["id"]
    r = client.post(
        f"{_pbase(fx)}/object-type-sources/{source_id}/sync", headers=hdr(fx.editor_sub)
    )
    assert r.status_code == 200, r.text
    return source_id


@pytest.fixture()
def ontology(client: TestClient, fx: Fixture, store: str) -> dict:
    """Person + Department, synced into whichever store is configured, plus
    the two link types the traversal tests use.

    Function-scoped rather than module-scoped: the store fixture flips the
    process-wide gateway per test, and instances synced into Postgres are not
    visible to OpenSearch or the reverse - a shared fixture would be
    populating one store and reading from another.
    """
    tag = uuid.uuid4().hex[:6]
    people_ds = _upload(client, fx, f"People {tag}", PEOPLE)
    depts_ds = _upload(client, fx, f"Departments {tag}", DEPARTMENTS)

    person = _type(client, fx, f"person_{tag}", f"Person {tag}",
                   ["full_name", "department", "manager_id"])
    dept = _type(client, fx, f"dept_{tag}", f"Department {tag}", ["label"])

    _map_and_sync(client, fx, person, people_ds, "employee_id", {
        "full_name": "full_name", "department": "department", "manager_id": "manager_id",
    })
    _map_and_sync(client, fx, dept, depts_ds, "code", {"label": "label"})

    works_in = client.post(
        f"{_wbase(fx)}/link-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"works_in_{tag}", "display_name": "Works in",
              "from_type_id": person, "to_type_id": dept, "cardinality": "one_to_many",
              "from_property": "department", "to_property": "$primary_key"},
    )
    assert works_in.status_code == 201, works_in.text

    reports_to = client.post(
        f"{_wbase(fx)}/link-types", headers=hdr(fx.editor_sub),
        # **A self-link with two names** (Foundry `object-link-types` p.192's
        # own example, Direct Report <-> Manager). The two directions are the
        # whole reason per-side names exist: one label cannot mean both "my
        # manager" and "my reports".
        json={"api_name": f"reports_to_{tag}", "display_name": "Reports to",
              "from_type_id": person, "to_type_id": person, "cardinality": "one_to_many",
              "from_property": "manager_id", "to_property": "$primary_key",
              "from_side_name": "Direct reports", "to_side_name": "Manager"},
    )
    assert reports_to.status_code == 201, reports_to.text

    return {
        "tag": tag, "person": person, "dept": dept,
        "works_in": works_in.json()["id"], "reports_to": reports_to.json()["id"],
    }


def _instances(client: TestClient, fx: Fixture, type_id: str) -> dict[str, dict]:
    r = client.get(f"{_wbase(fx)}/object-types/{type_id}/instances",
                   headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return {i["primary_key"]: i for i in r.json()["items"]}


def _links(client: TestClient, fx: Fixture, type_id: str, instance_id: str) -> dict[str, dict]:
    r = client.get(
        f"{_wbase(fx)}/object-types/{type_id}/instances/{instance_id}/links",
        headers=hdr(fx.viewer_sub),
    )
    assert r.status_code == 200, r.text
    return {f"{g['api_name']}:{g['direction']}": g for g in r.json()}


# ---- definition -------------------------------------------------------------
def test_a_join_must_name_properties_that_exist(client: TestClient, fx: Fixture) -> None:
    tag = uuid.uuid4().hex[:6]
    person = _type(client, fx, f"p_{tag}", f"P {tag}", ["dept"])
    dept = _type(client, fx, f"d_{tag}", f"D {tag}", ["label"])

    def create(**join):
        return client.post(
            f"{_wbase(fx)}/link-types", headers=hdr(fx.editor_sub),
            json={"api_name": f"l_{tag}", "display_name": "L", "from_type_id": person,
                  "to_type_id": dept, "cardinality": "one_to_many", **join},
        )

    r = create(from_property="nonexistent", to_property="$primary_key")
    assert r.status_code == 422, r.text
    assert "not a property" in r.json()["detail"]

    # Half a join is not a weaker join, it is an unanswerable question.
    r = create(from_property="dept")
    assert r.status_code == 422, r.text
    assert "both ends" in r.json()["detail"]

    # The other end is checked against the *other* type's properties.
    r = create(from_property="dept", to_property="dept")
    assert r.status_code == 422, r.text

    r = create(from_property="dept", to_property="$primary_key")
    assert r.status_code == 201, r.text
    assert r.json()["from_property"] == "dept"
    assert r.json()["to_property"] == "$primary_key"


def test_a_link_defined_before_0027_can_be_mapped_in_place(
    client: TestClient, fx: Fixture
) -> None:
    """The upgrade path: every link type that already existed has no join, and
    delete-and-recreate must not be the only way to give it one."""
    tag = uuid.uuid4().hex[:6]
    person = _type(client, fx, f"p_{tag}", f"P {tag}", ["dept"])
    dept = _type(client, fx, f"d_{tag}", f"D {tag}", ["label"])
    r = client.post(
        f"{_wbase(fx)}/link-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"l_{tag}", "display_name": "L", "from_type_id": person,
              "to_type_id": dept, "cardinality": "one_to_many"},
    )
    assert r.status_code == 201, r.text
    link_id = r.json()["id"]
    assert r.json()["from_property"] is None and r.json()["to_property"] is None

    patch = f"{_wbase(fx)}/link-types/{link_id}"
    assert client.patch(patch, headers=hdr(fx.viewer_sub),
                        json={"from_property": "dept",
                              "to_property": "$primary_key"}).status_code == 403

    r = client.patch(patch, headers=hdr(fx.editor_sub),
                     json={"from_property": "dept", "to_property": "$primary_key"})
    assert r.status_code == 200, r.text
    assert r.json()["from_property"] == "dept"

    # And back to definition-only.
    r = client.patch(patch, headers=hdr(fx.editor_sub),
                     json={"from_property": None, "to_property": None})
    assert r.status_code == 200, r.text
    assert r.json()["from_property"] is None

    r = client.patch(patch, headers=hdr(fx.editor_sub), json={"from_property": "bogus"})
    assert r.status_code == 422, r.text


# ---- traversal (both stores) -------------------------------------------------
def test_outbound_traversal_matches_exactly_not_by_prefix(
    client: TestClient, fx: Fixture, ontology: dict
) -> None:
    people = _instances(client, fx, ontology["person"])
    groups = _links(client, fx, ontology["person"], people["1"]["id"])

    works_in = groups[f"works_in_{ontology['tag']}:outbound"]
    assert works_in["total"] == 1, "ENG, and not the ENGW whose code it is a prefix of"
    assert works_in["items"][0]["primary_key"] == "ENG"
    assert works_in["items"][0]["properties"]["label"] == "Engineering"
    assert works_in["matched_value"] == "ENG"
    assert works_in["far_type_display_name"] == f"Department {ontology['tag']}"


def test_inbound_traversal_answers_the_reverse_question(
    client: TestClient, fx: Fixture, ontology: dict
) -> None:
    depts = _instances(client, fx, ontology["dept"])
    groups = _links(client, fx, ontology["dept"], depts["ENG"]["id"])

    works_in = groups[f"works_in_{ontology['tag']}:inbound"]
    assert works_in["direction"] == "inbound"
    assert works_in["near_property"] == "$primary_key"
    assert works_in["far_property"] == "department"
    assert {i["properties"]["full_name"] for i in works_in["items"]} == {"Ada", "Alan"}
    assert works_in["total"] == 2

    # ENGW has the same prefix and nobody in it.
    empty = _links(client, fx, ontology["dept"], depts["ENGW"]["id"])
    assert empty[f"works_in_{ontology['tag']}:inbound"]["total"] == 0


def test_a_self_link_answers_both_directions_separately(
    client: TestClient, fx: Fixture, ontology: dict
) -> None:
    """Person -> Person by manager: outbound is "my manager", inbound is "my
    reports". Returning one group for both would answer neither."""
    people = _instances(client, fx, ontology["person"])
    key = f"reports_to_{ontology['tag']}"

    ada = _links(client, fx, ontology["person"], people["1"]["id"])
    # Ada's manager_id is blank upstream: a null join value points at nothing,
    # not at every other person whose manager is also unset.
    assert ada[f"{key}:outbound"]["total"] == 0
    assert ada[f"{key}:outbound"]["matched_value"] is None
    assert {i["properties"]["full_name"] for i in ada[f"{key}:inbound"]["items"]} == {
        "Grace", "Alan"
    }

    grace = _links(client, fx, ontology["person"], people["2"]["id"])
    # manager_id arrives as an integer, the primary key is text: the join is on
    # the text form of the value, so this is a match rather than a near miss.
    assert grace[f"{key}:outbound"]["total"] == 1
    assert grace[f"{key}:outbound"]["items"][0]["properties"]["full_name"] == "Ada"
    assert grace[f"{key}:inbound"]["total"] == 0


def test_an_unmapped_link_type_is_not_traversable(
    client: TestClient, fx: Fixture, ontology: dict
) -> None:
    """It stays a valid ontology statement; it just cannot answer an
    instance-level question, so it is absent rather than present-and-empty -
    "no links found" and "this link has no join" are different facts."""
    patch = f"{_wbase(fx)}/link-types/{ontology['works_in']}"
    assert client.patch(patch, headers=hdr(fx.editor_sub),
                        json={"from_property": None, "to_property": None}).status_code == 200

    people = _instances(client, fx, ontology["person"])
    groups = _links(client, fx, ontology["person"], people["1"]["id"])
    assert f"works_in_{ontology['tag']}:outbound" not in groups
    assert f"reports_to_{ontology['tag']}:outbound" in groups, "the mapped one still works"

    # It is still listed as a link type - the ontology did not lose anything.
    r = client.get(f"{_wbase(fx)}/link-types", headers=hdr(fx.viewer_sub))
    assert any(lt["id"] == ontology["works_in"] for lt in r.json())


def test_traversal_needs_a_real_instance_and_a_visible_type(
    client: TestClient, fx: Fixture, ontology: dict
) -> None:
    r = client.get(
        f"{_wbase(fx)}/object-types/{ontology['person']}/instances/{uuid.uuid4()}/links",
        headers=hdr(fx.viewer_sub),
    )
    assert r.status_code == 404

    r = client.get(
        f"{_wbase(fx)}/object-types/{uuid.uuid4()}/instances/{uuid.uuid4()}/links",
        headers=hdr(fx.viewer_sub),
    )
    assert r.status_code == 404

    people = _instances(client, fx, ontology["person"])
    r = client.get(
        f"{_wbase(fx)}/object-types/{ontology['person']}"
        f"/instances/{people['1']['id']}/links",
        headers=hdr(fx.outsider_sub),
    )
    assert r.status_code == 404, "outside the workspace: 404, never 403"


# ---- per-side names (parity ontology.md §2; object-link-types p.192) ---------
def test_a_self_links_two_directions_read_differently(
    client: TestClient, fx: Fixture, ontology: dict
) -> None:
    """`ontology.md` §8: "a self-link between Employee and Employee renders both
    directions with distinct names."

    The traversal already returned a self-link twice, once per direction — what
    it could not do was say which was which, because both rows carried the
    link's single `display_name`. Asserting on `side_name` is asserting the
    thing that was actually missing.
    """
    people = _instances(client, fx, ontology["person"])
    groups = _links(client, fx, ontology["person"], people["1"]["id"])
    tag = ontology["tag"]

    outbound = groups[f"reports_to_{tag}:outbound"]
    inbound = groups[f"reports_to_{tag}:inbound"]
    assert outbound["side_name"] == "Manager", "traversing to the `to` side"
    assert inbound["side_name"] == "Direct reports", "and back the other way"
    # The link's own name is still there and still the same on both, which is
    # exactly why it could not do this job.
    assert outbound["display_name"] == inbound["display_name"] == "Reports to"


def test_a_link_with_no_side_names_falls_back_to_its_own(
    client: TestClient, fx: Fixture, ontology: dict
) -> None:
    """Every link type that existed before sides could be named keeps the label
    it had — which is what makes migration 0043 invisible."""
    people = _instances(client, fx, ontology["person"])
    groups = _links(client, fx, ontology["person"], people["1"]["id"])
    works_in = groups[f"works_in_{ontology['tag']}:outbound"]
    assert works_in["side_name"] == "Works in" == works_in["display_name"]


# ---- links from a type, with no object in hand (parity workshop.md §212) -----
def _type_links(client: TestClient, fx: Fixture, type_id: str) -> dict[str, dict]:
    r = client.get(f"{_wbase(fx)}/object-types/{type_id}/links",
                   headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return {f"{g['api_name']}:{g['direction']}": g for g in r.json()}


def test_a_type_lists_its_links_without_an_instance(
    client: TestClient, fx: Fixture, ontology: dict
) -> None:
    """A builder configuring a widget chooses between link types before there
    is any data to traverse.

    Answering that with the instance endpoint would make the set of
    configurable links depend on whether the bound object set happens to be
    empty — a widget that could not be configured on a Monday and could on a
    Tuesday.
    """
    tag = ontology["tag"]
    links = _type_links(client, fx, ontology["person"])

    works_in = links[f"works_in_{tag}:outbound"]
    assert works_in["far_type_display_name"] == f"Department {tag}"
    assert works_in["near_property"] == "department"
    assert works_in["far_property"] == "$primary_key"
    assert works_in["far_type_id"] == ontology["dept"]
    # This link names no sides, so `side_name` and `display_name` are the same
    # string here and neither can stand in for the other — the assertion that
    # separates them is the self-link's, below.
    assert works_in["side_name"] == works_in["display_name"] == "Works in"
    # **The id is checked against the traversal's**, not against itself: every
    # other id in this row is also a uuid, so an assertion that it is one would
    # hold if the far type's had been sent instead.
    people = _instances(client, fx, ontology["person"])
    traversed = _links(client, fx, ontology["person"], people["1"]["id"])
    assert works_in["link_type_id"] == traversed[f"works_in_{tag}:outbound"]["link_type_id"]
    assert works_in["link_type_id"] != works_in["far_type_id"]
    # No traversal happened, so there is nothing about *this* object here.
    assert "items" not in works_in and "total" not in works_in


def test_a_self_link_is_listed_once_per_end(
    client: TestClient, fx: Fixture, ontology: dict
) -> None:
    """The reason a configured link is keyed on the pair, not the id.

    Both rows carry the same `link_type_id`; only `direction` and `side_name`
    tell "my manager" apart from "my direct reports".
    """
    tag = ontology["tag"]
    links = _type_links(client, fx, ontology["person"])
    outbound = links[f"reports_to_{tag}:outbound"]
    inbound = links[f"reports_to_{tag}:inbound"]

    assert outbound["link_type_id"] == inbound["link_type_id"]
    assert outbound["side_name"] == "Manager"
    assert inbound["side_name"] == "Direct reports"
    assert outbound["near_property"] == "manager_id"
    assert inbound["near_property"] == "$primary_key"


def test_listing_a_types_links_needs_a_visible_type(
    client: TestClient, fx: Fixture, ontology: dict
) -> None:
    r = client.get(f"{_wbase(fx)}/object-types/{uuid.uuid4()}/links",
                   headers=hdr(fx.viewer_sub))
    assert r.status_code == 404

    r = client.get(f"{_wbase(fx)}/object-types/{ontology['person']}/links",
                   headers=hdr(fx.outsider_sub))
    assert r.status_code == 404, "outside the workspace: 404, never 403"
