"""Link traversal inside an object set definition (parity
`docs/parity/ontology.md` §3, and the gap `workshop.md` §3.1 names).

> "Object set definition — object types, filters, link traversals"

**A hop compiles to an `in` filter.** That is the whole implementation and the
reason it needed no new store capability: `in` already means the same thing on
Postgres and OpenSearch, which is why it is in `OPERATORS` at all. The ordered
operators were refused for the opposite reason, and a traversal that invented
its own join would have walked straight into it.

The half that *did* need both stores taught is filtering on the **primary
key**: migration 0027's join is "the from side holds the foreign key", so
traversing towards the to side matches against that side's key. Without it a
traversal would work one way round and be refused the other, which is not a
feature but half of one.
"""
from __future__ import annotations

import uuid

import pytest

from src.services import object_sets
from src.services import ontology as ontology_service


def a_set(**extra):
    return {"object_type_id": str(uuid.uuid4()), **extra}


# ---- the shape -----------------------------------------------------------
def test_a_set_can_be_the_far_side_of_a_link() -> None:
    link = str(uuid.uuid4())
    base = a_set(filters=[{"property": "region", "op": "eq", "value": "north"}])
    parsed = object_sets.parse(a_set(via={"link_type_id": link, "base": base}))
    assert parsed.via is not None
    assert str(parsed.via.link_type_id) == link
    assert parsed.via.base.filters[0].property == "region"
    assert parsed.depth == 1


def test_a_set_without_a_hop_is_unchanged() -> None:
    parsed = object_sets.parse(a_set())
    assert parsed.via is None and parsed.depth == 0


def test_a_traversal_needs_a_link_and_a_base() -> None:
    with pytest.raises(ValueError, match="needs a link_type_id"):
        object_sets.parse(a_set(via={"base": a_set()}))
    with pytest.raises(ValueError, match="needs a base set"):
        object_sets.parse(a_set(via={"link_type_id": str(uuid.uuid4())}))
    with pytest.raises(ValueError, match="not a valid link type id"):
        object_sets.parse(a_set(via={"link_type_id": "nope", "base": a_set()}))


def test_depth_is_capped_because_each_hop_is_a_query() -> None:
    """Each hop evaluates the set below it, so depth is not free the way a
    filter is - a definition ten deep is ten queries a viewer never asked for
    and cannot see."""
    definition = a_set()
    for _ in range(object_sets.MAX_TRAVERSALS):
        definition = a_set(via={"link_type_id": str(uuid.uuid4()), "base": definition})
    assert object_sets.parse(definition).depth == object_sets.MAX_TRAVERSALS

    definition = a_set(via={"link_type_id": str(uuid.uuid4()), "base": definition})
    with pytest.raises(ValueError, match="at most 3 links"):
        object_sets.parse(definition)


def test_the_base_set_is_validated_like_any_other() -> None:
    """One parser, so a filter that would be refused at the top is refused a
    hop down - otherwise a traversal would be a way round every refusal."""
    with pytest.raises(ValueError, match="did not supply them"):
        object_sets.parse(a_set(via={
            "link_type_id": str(uuid.uuid4()),
            "base": a_set(filters=[{"property": "n", "op": "gt", "value": 3}]),
        }))


# ---- the join ------------------------------------------------------------
def test_a_hop_becomes_an_in_filter() -> None:
    f = object_sets.join_filter(far_property="customer_id", values=["C1", "C2"])
    assert f is not None
    assert (f.property, f.op) == ("customer_id", "in")
    assert f.value == ["C1", "C2"]


def test_an_empty_base_set_is_the_empty_answer_not_no_filter() -> None:
    """The silent-widening failure decision 0002 exists to remove: a base set
    with no members links to nothing, and an unfiltered read there would show
    *every* object of the far type."""
    assert object_sets.join_filter(far_property="customer_id", values=[]) is None


def test_objects_with_no_join_value_link_to_nothing() -> None:
    """Including them would match far-side rows whose property is also empty,
    which is not a link - it is two absences."""
    f = object_sets.join_filter(far_property="customer_id", values=[None, None])
    assert f is None
    f = object_sets.join_filter(far_property="customer_id", values=[None, "C1"])
    assert f is not None and f.value == ["C1"]


def test_values_are_deduplicated_and_ordered() -> None:
    """A hundred orders for one customer is one term, and the same set gives
    the same query - so a cache key over it means something."""
    f = object_sets.join_filter(far_property="c", values=["B", "A", "B", "A"])
    assert f is not None and f.value == ["A", "B"]


def test_too_many_join_values_is_refused_with_the_number() -> None:
    """Truncating would leave a set quietly missing its tail, which is the
    failure that looks like working software."""
    values = [f"C{i}" for i in range(object_sets.MAX_JOIN_VALUES + 1)]
    with pytest.raises(ValueError, match=f"limit is {object_sets.MAX_JOIN_VALUES}"):
        object_sets.join_filter(far_property="c", values=values)
    # And exactly at the cap is allowed, so the boundary is where it says.
    assert object_sets.join_filter(far_property="c", values=values[:-1]) is not None


# ---- the primary key, which half of every link lands on -------------------
def test_the_primary_key_can_be_filtered_on() -> None:
    """Migration 0027: "the *from* side holds the foreign key". So traversing
    towards the *to* side matches against that side's key rather than a
    property, and a filter vocabulary that could not address it would support
    link traversal in one direction only."""
    f = object_sets.join_filter(
        far_property=object_sets.PRIMARY_KEY_FILTER, values=["C1"]
    )
    assert f is not None and f.property == object_sets.PRIMARY_KEY_FILTER


def test_both_ends_use_the_same_name_for_the_primary_key() -> None:
    """Two spellings would mean a traversal that worked through the ontology's
    helper and not through a set definition, or the reverse."""
    assert object_sets.PRIMARY_KEY_FILTER == ontology_service.PRIMARY_KEY_REF


def test_postgres_filters_the_key_as_a_column_not_a_property() -> None:
    from src.services import instances as instances_service

    where, params = instances_service._set_predicate(
        uuid.uuid4(),
        (object_sets.Filter(object_sets.PRIMARY_KEY_FILTER, "in", ["C1", "C2"]),),
    )
    assert "i.primary_key" in where, where
    assert "jsonb_extract_path_text" not in where, where
    assert list(params.values())[-1] == ["C1", "C2"]


def test_opensearch_filters_the_key_as_its_own_field() -> None:
    from src.services.instance_store import OpenSearchInstanceStore

    clauses = OpenSearchInstanceStore._set_clauses(
        uuid.uuid4(),
        (object_sets.Filter(object_sets.PRIMARY_KEY_FILTER, "in", ["C1"]),),
    )
    terms = [c for c in clauses["filter"] if "terms" in c]
    assert terms and "primary_key" in terms[0]["terms"], clauses
    assert "properties.$primary_key" not in str(clauses), clauses


def test_an_ordinary_property_is_still_a_property_on_both_stores() -> None:
    """The guard on the special case: a sentinel that swallowed every filter
    would make every set read the key."""
    from src.services import instances as instances_service
    from src.services.instance_store import OpenSearchInstanceStore

    where, _ = instances_service._set_predicate(
        uuid.uuid4(), (object_sets.Filter("region", "eq", "north"),)
    )
    assert "jsonb_extract_path_text" in where, where
    clauses = OpenSearchInstanceStore._set_clauses(
        uuid.uuid4(), (object_sets.Filter("region", "eq", "north"),)
    )
    assert "properties.region" in str(clauses), clauses


# ---- end to end, against real instances -----------------------------------
import os  # noqa: E402
import sys  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402


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


@pytest.fixture(scope="module")
def linked(client: TestClient, fx: Fixture) -> dict:
    """Customers and their orders, joined the way migration 0027 describes:
    the *from* side (Order) holds the foreign key.

    Two customers so a traversal can be wrong in a visible way - a hop that
    ignored its base set would return both customers' orders.
    """
    tag = uuid.uuid4().hex[:6]
    customers = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"cust_{tag}", "display_name": f"Cust {tag}",
              "properties": [{"api_name": "region", "data_type": "string"}]},
    )
    assert customers.status_code == 201, customers.text
    orders = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"ord_{tag}", "display_name": f"Ord {tag}",
              "properties": [
                  {"api_name": "customer_id", "data_type": "string"},
                  {"api_name": "total", "data_type": "integer"},
                  {"api_name": "placed", "data_type": "date"},
              ]},
    )
    assert orders.status_code == 201, orders.text
    customer_type, order_type = customers.json()["id"], orders.json()["id"]

    link = client.post(
        f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub),
        json={
            "api_name": f"placed_by_{tag}", "display_name": "Placed by",
            "from_type_id": order_type, "to_type_id": customer_type,
            "cardinality": "one_to_many",
            "from_property": "customer_id", "to_property": "$primary_key",
        },
    )
    assert link.status_code == 201, link.text

    def upload(name: str, csv: bytes, type_id: str, mappings: dict) -> None:
        dataset = client.post(
            f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
            files={"file": (f"{name}.csv", csv, "text/csv")}, data={"name": name},
        )
        assert dataset.status_code == 201, dataset.text
        source = client.post(
            f"{pbase(fx)}/object-type-sources", headers=hdr(fx.editor_sub),
            json={"object_type_id": type_id, "dataset_id": dataset.json()["id"],
                  "primary_key_column": "id", "column_mappings": mappings},
        )
        assert source.status_code == 201, source.text
        synced = client.post(
            f"{pbase(fx)}/object-type-sources/{source.json()['id']}/sync",
            headers=hdr(fx.editor_sub), json={},
        )
        assert synced.status_code == 200 and synced.json()["ok"], synced.text

    # C3 has no orders, so p.451's Has link has someone to leave out (§545).
    upload(f"customers_{tag}", b"id,region\nC1,north\nC2,south\nC3,east\n",
           customer_type, {"region": "region"})
    upload(f"orders_{tag}",
           b"id,customer_id,total,placed\nO1,C1,10,2024-01-10\nO2,C1,20,2024-02-10\n"
           b"O3,C2,30,2024-03-10\n",
           order_type, {"customer_id": "customer_id", "total": "total", "placed": "placed"})
    return {"customer_type": customer_type, "order_type": order_type,
            "link": link.json()["id"]}


def evaluate(client, fx, definition) -> dict:
    r = client.post(
        f"{wbase(fx)}/object-sets/evaluate", headers=hdr(fx.editor_sub),
        json={"definition": definition, "limit": 50, "offset": 0},
    )
    return {"status": r.status_code, "body": r.json()}


def test_a_traversal_returns_only_the_linked_objects(client, fx, linked) -> None:
    """The claim the whole unit makes: the orders of the *northern* customers,
    not every order. Two customers exist, so a hop that ignored its base set
    would return three rows instead of two."""
    answer = evaluate(client, fx, {
        "object_type_id": linked["order_type"],
        "via": {
            "link_type_id": linked["link"],
            "base": {"object_type_id": linked["customer_type"],
                     "filters": [{"property": "region", "op": "eq", "value": "north"}]},
        },
    })
    assert answer["status"] == 200, answer
    keys = sorted(i["primary_key"] for i in answer["body"]["instances"])
    assert keys == ["O1", "O2"], answer["body"]
    assert answer["body"]["total"] == 2


def test_a_traversal_the_other_way_lands_on_the_primary_key(client, fx, linked) -> None:
    """The direction that needed both stores taught to filter on the key: from
    orders to the customers who placed them."""
    answer = evaluate(client, fx, {
        "object_type_id": linked["customer_type"],
        "via": {
            "link_type_id": linked["link"],
            "base": {"object_type_id": linked["order_type"],
                     "filters": [{"property": "total", "op": "eq", "value": "30"}]},
        },
    })
    assert answer["status"] == 200, answer
    keys = [i["primary_key"] for i in answer["body"]["instances"]]
    assert keys == ["C2"], answer["body"]


def test_the_far_set_can_be_filtered_as_well(client, fx, linked) -> None:
    """A traversal is a *source* of members, not a replacement for filtering -
    the set's own filters still apply on top."""
    answer = evaluate(client, fx, {
        "object_type_id": linked["order_type"],
        "filters": [{"property": "total", "op": "eq", "value": "20"}],
        "via": {
            "link_type_id": linked["link"],
            "base": {"object_type_id": linked["customer_type"],
                     "filters": [{"property": "region", "op": "eq", "value": "north"}]},
        },
    })
    assert [i["primary_key"] for i in answer["body"]["instances"]] == ["O2"], answer["body"]


def test_a_base_set_that_matches_nothing_gives_nothing(client, fx, linked) -> None:
    """Not *everything*, which is what an unfiltered read would give - the
    silent widening decision 0002 exists to remove."""
    answer = evaluate(client, fx, {
        "object_type_id": linked["order_type"],
        "via": {
            "link_type_id": linked["link"],
            "base": {"object_type_id": linked["customer_type"],
                     "filters": [{"property": "region", "op": "eq", "value": "atlantis"}]},
        },
    })
    assert answer["status"] == 200, answer
    assert answer["body"]["instances"] == [] and answer["body"]["total"] == 0


def test_a_link_that_does_not_touch_the_base_type_is_refused(client, fx, linked) -> None:
    """"Your definition is wrong" and "there are no matches" look identical in
    an empty table, so this is a refusal rather than an empty answer."""
    answer = evaluate(client, fx, {
        "object_type_id": linked["order_type"],
        "via": {"link_type_id": str(uuid.uuid4()),
                "base": {"object_type_id": linked["customer_type"]}},
    })
    assert answer["status"] == 422, answer
    assert "does not connect" in str(answer["body"]), answer


def test_a_traversal_landing_on_another_type_is_refused(client, fx, linked) -> None:
    """The link decides where a hop lands. A definition claiming otherwise
    would return rows of a type its widgets are not configured for."""
    answer = evaluate(client, fx, {
        "object_type_id": linked["customer_type"],
        "via": {"link_type_id": linked["link"],
                "base": {"object_type_id": linked["customer_type"]}},
    })
    assert answer["status"] == 422, answer


# ---- every reading of a set honours its hop -----------------------------------
def northern_orders(linked: dict) -> dict:
    return {
        "object_type_id": linked["order_type"],
        "via": {"link_type_id": linked["link"], "base": {
            "object_type_id": linked["customer_type"],
            "filters": [{"property": "region", "op": "eq", "value": "north"}]}},
    }


def test_a_count_of_a_traversed_set_counts_the_linked_objects(client, fx, linked) -> None:
    r = client.post(f"{wbase(fx)}/object-sets/aggregate", headers=hdr(fx.editor_sub),
                    json={"definition": northern_orders(linked), "aggregation": "count"})
    assert r.status_code == 200, r.text
    assert r.json()["value"] == 2, r.json()


def test_a_grouping_of_a_traversed_set_groups_the_linked_objects(client, fx, linked) -> None:
    r = client.post(f"{wbase(fx)}/object-sets/group", headers=hdr(fx.editor_sub),
                    json={"definition": northern_orders(linked), "property": "customer_id"})
    assert r.status_code == 200, r.text
    assert [(g["value"], g["count"]) for g in r.json()["groups"]] == [("C1", 2)], r.json()


def post(client, fx, route: str, body: dict) -> dict:
    r = client.post(f"{wbase(fx)}/object-sets/{route}", headers=hdr(fx.editor_sub), json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_a_distribution_of_a_traversed_set_spans_the_linked_objects(client, fx, linked) -> None:
    # The northern orders total 10 and 20; C2's 30 is not among them.
    body = post(client, fx, "distribution",
                {"definition": northern_orders(linked), "property": "total", "buckets": 2})
    assert body["total"] == 2, body
    assert (body["buckets"][0]["low"], body["buckets"][-1]["high"]) == (10, 21), body
    assert sum(b["count"] for b in body["buckets"]) == 2, body


def test_a_cross_tab_of_a_traversed_set_crosses_the_linked_objects(client, fx, linked) -> None:
    body = post(client, fx, "cross-tab", {
        "definition": northern_orders(linked),
        "row_property": "customer_id", "column_property": "total"})
    assert [r["value"] for r in body["rows"]] == ["C1"], body
    assert sorted(c["value"] for c in body["columns"]) == ["10", "20"], body


def test_a_time_series_of_a_traversed_set_counts_the_linked_objects(client, fx, linked) -> None:
    body = post(client, fx, "time-series", {
        "definition": northern_orders(linked), "interval": "month", "property": "placed"})
    assert sum(p["count"] for p in body["points"]) == 2, body


def test_a_set_linked_to_nothing_reads_as_nothing_everywhere(client, fx, linked) -> None:
    """The base matches no customer, so the set holds no orders - and every
    reading says so in its own empty, rather than reading the type unfiltered
    (decision 0002's silent widening)."""
    nobody = northern_orders(linked)
    nobody["via"]["base"]["filters"] = [{"property": "region", "op": "eq", "value": "west"}]
    assert post(client, fx, "aggregate", {"definition": nobody, "aggregation": "count"})[
        "value"] == 0
    assert post(client, fx, "group", {"definition": nobody, "property": "customer_id"})[
        "groups"] == []


def test_a_hop_that_does_not_join_is_refused_by_a_count_too(client, fx, linked) -> None:
    wrong = northern_orders(linked)
    wrong["via"]["base"]["object_type_id"] = linked["order_type"]
    r = client.post(f"{wbase(fx)}/object-sets/aggregate", headers=hdr(fx.editor_sub),
                    json={"definition": wrong, "aggregation": "count"})
    assert r.status_code == 422, r.text


# ---- p.451's filters on linked objects (§545) --------------------------------
def with_link(linked: dict, type_key: str, filters: list | None = None) -> dict:
    return {"object_type_id": linked[type_key], "filters": [
        {"property": linked["link"], "op": "has_link", "value": {"filters": filters or []}}]}


def keys_of(client, fx, definition) -> list[str]:
    answer = evaluate(client, fx, definition)
    assert answer["status"] == 200, answer
    return sorted(i["primary_key"] for i in answer["body"]["instances"])


def test_has_link_keeps_the_objects_with_a_link(client, fx, linked) -> None:
    """p.451's own example, "all Tasks that have a link to Person": here the
    customers who have placed an order. C3 has none."""
    assert keys_of(client, fx, with_link(linked, "customer_type")) == ["C1", "C2"]


def test_a_linked_filter_narrows_by_the_linked_objects(client, fx, linked) -> None:
    # The customers with an order over 15: C1's 20 and C2's 30, not C1's 10 alone.
    over = [{"property": "total", "op": "gt", "value": 15}]
    assert keys_of(client, fx, with_link(linked, "customer_type", over)) == ["C1", "C2"]
    only_ten = [{"property": "total", "op": "eq", "value": "10"}]
    assert keys_of(client, fx, with_link(linked, "customer_type", only_ten)) == ["C1"]


def test_a_linked_filter_works_from_the_other_end(client, fx, linked) -> None:
    """From orders, the link's far end is the customer's primary key."""
    north = [{"property": "region", "op": "eq", "value": "north"}]
    assert keys_of(client, fx, with_link(linked, "order_type", north)) == ["O1", "O2"]


def test_a_linked_filter_combines_with_the_others(client, fx, linked) -> None:
    definition = with_link(linked, "customer_type")
    definition["filters"].append({"property": "region", "op": "eq", "value": "south"})
    assert keys_of(client, fx, definition) == ["C2"]


def test_linked_objects_that_match_nothing_leave_nothing(client, fx, linked) -> None:
    none = [{"property": "total", "op": "eq", "value": "999"}]
    assert keys_of(client, fx, with_link(linked, "customer_type", none)) == []
    body = post(client, fx, "aggregate", {
        "definition": with_link(linked, "customer_type", none), "aggregation": "count"})
    assert body["value"] == 0, body


def test_every_reading_of_a_set_resolves_its_linked_filters(client, fx, linked) -> None:
    body = post(client, fx, "group", {
        "definition": with_link(linked, "customer_type"), "property": "region"})
    assert sorted(g["value"] for g in body["groups"]) == ["north", "south"], body


@pytest.mark.parametrize("filters, says", [
    ([{"property": "not-a-uuid", "op": "has_link", "value": {}}], "by id"),
    ([{"property": str(uuid.uuid4()), "op": "has_link", "value": "x"}], "filters"),
    ([{"property": str(uuid.uuid4()), "op": "has_link",
       "value": {"filters": [{"property": str(uuid.uuid4()), "op": "has_link", "value": {}}]}}],
     "cannot itself follow a link"),
    ([{"property": str(uuid.uuid4()), "op": "has_link", "value": {"filters": [
        {"property": "x", "op": "eq", "value": "y"}] * (object_sets.MAX_FILTERS + 1)}}],
     "at most"),
])
def test_a_linked_filter_is_refused_when_malformed(filters, says) -> None:
    with pytest.raises(ValueError, match=says):
        object_sets.parse(a_set(filters=filters))


def test_a_link_that_does_not_touch_the_type_is_refused(client, fx, linked) -> None:
    definition = {"object_type_id": linked["customer_type"], "filters": [
        {"property": str(uuid.uuid4()), "op": "has_link", "value": {}}]}
    answer = evaluate(client, fx, definition)
    assert answer["status"] == 422, answer
    assert "does not touch" in answer["body"]["detail"], answer


def test_a_hop_and_a_linked_filter_hold_together(client, fx, linked) -> None:
    """The customers of orders O2 and O3 (C1 and C2), of whom the one with an
    order of exactly 10: C1. The hop is resolved and then the link."""
    definition = {
        "object_type_id": linked["customer_type"],
        "via": {"link_type_id": linked["link"], "base": {
            "object_type_id": linked["order_type"],
            "filters": [{"property": object_sets.PRIMARY_KEY_FILTER, "op": "in",
                         "value": ["O2", "O3"]}]}},
        "filters": [{"property": linked["link"], "op": "has_link", "value": {"filters": [
            {"property": "total", "op": "eq", "value": "10"}]}}],
    }
    assert keys_of(client, fx, definition) == ["C1"]
