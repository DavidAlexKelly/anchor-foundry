"""The readings of a union a Filter List needs (§687; `workshop` p.450).

> "The Filter List will allow the following filtering options: Common
> property: The properties that the different object types have in common…
> Single property: A unique property that exists on only one of the object
> types." (p.450)

Each reading asks every part the question one set is asked, and adds the
answers up. Two types here share `region`, `score` and `since`; `size` is the
Sites' alone.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.services import union_reads  # noqa: E402
from test_api import hdr  # noqa: E402
from test_object_set_traversal import (  # noqa: E402,F401
    _fresh_identity_cache, client, fx, pbase, wbase,
)


# ---- the merges -------------------------------------------------------------
def test_groups_add_up_by_value_commonest_first() -> None:
    shown, distinct, truncated = union_reads.merge_groups(
        [([("north", 2), ("south", 1)], 2), ([("north", 1), ("east", 1)], 2)], 20)
    assert shown == [("north", 3), ("east", 1), ("south", 1)]
    assert (distinct, truncated) == (3, False)


def test_a_merged_list_past_its_limit_is_truncated_and_says_how_many() -> None:
    shown, distinct, truncated = union_reads.merge_groups(
        [([("a", 2), ("b", 1)], 2), ([("c", 1)], 1)], 2)
    assert shown == [("a", 2), ("b", 1)]
    assert (distinct, truncated) == (3, True)


def test_a_part_cut_short_makes_the_total_a_floor() -> None:
    """A part with 40 values, of which 2 came back: at least 40 exist."""
    shown, distinct, truncated = union_reads.merge_groups([([("a", 9), ("b", 8)], 40)], 20)
    assert (distinct, truncated) == (40, True)
    assert shown == [("a", 9), ("b", 8)]


def test_times_add_up_by_start_in_order() -> None:
    jan, feb = datetime(2024, 1, 1), datetime(2024, 2, 1)
    assert union_reads.merge_times([[(feb, 1), (jan, 2)], [(jan, 1)]]) == [(jan, 3), (feb, 1)]


# ---- which parts are asked, against a store that records it ------------------
class FakeStore:
    """Answers per type, and a note of every question."""

    def __init__(self, groups=None, counts=None, times=None) -> None:
        self.groups, self.counts, self.times = groups or {}, counts or {}, times or {}
        self.asked: list[tuple] = []

    async def group_object_set(self, *, object_type_id, property_name, limit, **_):
        self.asked.append(("group", object_type_id))
        return self.groups[object_type_id]

    async def aggregate_object_set(self, *, object_type_id, filters, **_):
        values = [f.value[0] for f in filters if isinstance(f.value, list) and f.value]
        self.asked.append(("count", object_type_id, *values))
        return self.counts.get((object_type_id, *values), 0)

    async def time_series_object_set(self, *, object_type_id, interval, **_):
        self.asked.append(("times", object_type_id, interval))
        return self.times.get((object_type_id, interval), [])


def fake_parts(monkeypatch, store: FakeStore, declared: dict) -> None:
    from src.services import object_sets

    async def parts(conn, store_, prefix, workspace_id, definition):
        return [union_reads.Part(object_sets.ObjectSet(object_type_id=t, filters=()), (), d)
                for t, d in declared.items()]

    async def the_store(conn, workspace_id):
        return store, "prefix"

    monkeypatch.setattr(union_reads, "_parts", parts)
    monkeypatch.setattr(union_reads, "_store", the_store)


A, B, C = (uuid.UUID(int=n) for n in (1, 2, 3))


def test_a_recount_reorders_and_asks_only_what_it_must(monkeypatch) -> None:
    """A lists a and b of three values; B lists its one, c. Two are shown: a
    and c, both 5 - and A holds three more c past its cut, so c leads once A
    is asked. B listed everything, so is asked nothing more, and C, with no
    such property, is not asked at all."""
    store = FakeStore(groups={A: ([("a", 5, None), ("b", 4, None)], 3),
                              B: ([("c", 5, None)], 1)},
                      counts={(A, "c"): 3})
    fake_parts(monkeypatch, store, {A: {"region": "string"}, B: {"region": "string"},
                                    C: {"name": "string"}})
    shown, distinct, truncated = asyncio.run(
        union_reads.group(None, A, {}, "region", 2, "count"))
    assert shown == [("c", 8), ("a", 5)]
    assert (distinct, truncated) == (3, True)
    assert store.asked == [("group", A), ("group", B), ("count", A, "c")]


def test_auto_steps_past_an_interval_with_too_many_buckets(monkeypatch) -> None:
    """Four years of days is more than a series holds, and so are its weeks;
    months fit."""
    start, end = datetime(2020, 1, 1), datetime(2024, 1, 1)
    store = FakeStore(times={(A, i): [(start, 1), (end, 1)] for i in ("day", "week", "month")})
    fake_parts(monkeypatch, store, {A: {}})
    filled, interval, total = asyncio.run(union_reads.time_series(None, A, {}, None, "auto"))
    assert interval == "month" and len(filled) == 49 and total == 0


# ---- against real instances -------------------------------------------------
@pytest.fixture(scope="module")
def mixed(client, fx) -> dict:
    tag = uuid.uuid4().hex[:6]

    def a_type(name: str, properties: list[dict]) -> str:
        r = client.post(f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
                        json={"api_name": f"{name}_{tag}", "display_name": f"{name} {tag}",
                              "properties": properties})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def upload(name: str, csv: bytes, type_id: str, columns: list[str]) -> None:
        dataset = client.post(
            f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
            files={"file": (f"{name}.csv", csv, "text/csv")}, data={"name": name})
        assert dataset.status_code == 201, dataset.text
        source = client.post(
            f"{pbase(fx)}/object-type-sources", headers=hdr(fx.editor_sub),
            json={"object_type_id": type_id, "dataset_id": dataset.json()["id"],
                  "primary_key_column": "id", "column_mappings": {c: c for c in columns}})
        assert source.status_code == 201, source.text
        synced = client.post(f"{pbase(fx)}/object-type-sources/{source.json()['id']}/sync",
                             headers=hdr(fx.editor_sub), json={})
        assert synced.status_code == 200 and synced.json()["ok"], synced.text

    sites = a_type("sites", [
        {"api_name": "region", "data_type": "string"},
        {"api_name": "score", "data_type": "integer"},
        {"api_name": "since", "data_type": "date"},
        {"api_name": "size", "data_type": "integer"},
        {"api_name": "opened", "data_type": "date"},
    ])
    staff = a_type("staff", [
        {"api_name": "region", "data_type": "string"},
        {"api_name": "score", "data_type": "float"},
        {"api_name": "since", "data_type": "date"},
    ])
    upload(f"sites_{tag}", b"id,region,score,since,size,opened\n"
           b"S1,north,10,2024-01-05,1,2023-12-01\nS2,south,20,2024-01-20,2,2023-12-15\n"
           b"S3,north,30,2024-02-03,3,2024-01-10\n",
           sites, ["region", "score", "since", "size", "opened"])
    upload(f"staff_{tag}", b"id,region,score,since\n"
           b"P1,north,5.5,2024-01-06\nP2,east,40,2024-06-01\n",
           staff, ["region", "score", "since"])
    return {"union": [{"object_type_id": sites, "filters": []},
                      {"object_type_id": staff, "filters": []}]}


def post(client, fx, route: str, body: dict) -> dict:
    r = client.post(f"{wbase(fx)}/object-sets/{route}", headers=hdr(fx.editor_sub), json=body)
    return {"status": r.status_code, "body": r.json()}


def test_a_common_property_counts_every_type(client, fx, mixed) -> None:
    answer = post(client, fx, "group", {"definition": mixed, "property": "region"})
    assert answer["status"] == 200, answer
    assert answer["body"]["groups"] == [
        {"value": "north", "count": 3, "metric": None},
        {"value": "east", "count": 1, "metric": None},
        {"value": "south", "count": 1, "metric": None},
    ]
    assert (answer["body"]["distinct_total"], answer["body"]["truncated"]) == (3, False)


def test_a_single_property_counts_the_type_that_has_it(client, fx, mixed) -> None:
    answer = post(client, fx, "group", {"definition": mixed, "property": "size"})
    assert [g["value"] for g in answer["body"]["groups"]] == ["1", "2", "3"]


def test_a_value_past_one_types_own_cut_is_still_counted_there(client, fx, mixed) -> None:
    """With one value asked for, the Sites say north (2) and the Staff say
    east (1), before north (1) on the value. North is shown, and the Staff's
    north is counted, not taken to be none."""
    answer = post(client, fx, "group", {"definition": mixed, "property": "region", "limit": 1})
    assert answer["body"]["groups"] == [{"value": "north", "count": 3, "metric": None}]
    # Each type has two values, and which the other's are is not known past
    # its cut: at least two, of the three there are.
    assert (answer["body"]["distinct_total"], answer["body"]["truncated"]) == (2, True)


def test_a_union_is_grouped_by_count_only(client, fx, mixed) -> None:
    answer = post(client, fx, "group", {"definition": mixed, "property": "region",
                                        "aggregation": "sum", "aggregation_property": "score"})
    assert answer["status"] == 422
    assert "grouped by count" in answer["body"]["detail"]


def test_a_distribution_is_one_range_over_every_type(client, fx, mixed) -> None:
    answer = post(client, fx, "distribution",
                  {"definition": mixed, "property": "score", "buckets": 7})
    assert answer["status"] == 200, answer
    body = answer["body"]
    # One decimal among them, so the bars are ranges of decimals.
    assert body["integer"] is False
    assert body["buckets"][0]["low"] == 5.5 and body["buckets"][-1]["high"] == 40
    assert [b["count"] for b in body["buckets"]] == [2, 0, 1, 0, 1, 0, 1]
    assert (body["total"], body["missing"]) == (5, 0)


def test_a_distribution_of_one_types_number_counts_the_rest_as_missing(client, fx, mixed) -> None:
    body = post(client, fx, "distribution",
                {"definition": mixed, "property": "size", "buckets": 3})["body"]
    assert body["integer"] is True
    assert [b["count"] for b in body["buckets"]] == [1, 1, 1]
    assert (body["total"], body["missing"]) == (5, 2)


def test_a_timeline_adds_every_type_up_by_bucket(client, fx, mixed) -> None:
    answer = post(client, fx, "time-series",
                  {"definition": mixed, "interval": "month", "property": "since"})
    assert answer["status"] == 200, answer
    body = answer["body"]
    assert [p["count"] for p in body["points"]] == [3, 1, 0, 0, 0, 1]
    assert body["points"][0]["start"].startswith("2024-01-01")
    assert (body["interval"], body["total"], body["missing"]) == ("month", 5, 0)


def test_auto_picks_an_interval_that_fits_the_whole_union(client, fx, mixed) -> None:
    """The Sites alone span a month, which days fit; with the Staff it is five
    months, which they do not."""
    body = post(client, fx, "time-series", {"definition": mixed, "interval": "auto",
                                            "property": "since"})["body"]
    assert body["interval"] == "week"
    assert sum(p["count"] for p in body["points"]) == 5
    alone = {"union": mixed["union"][:1]}
    assert post(client, fx, "time-series", {"definition": alone, "interval": "auto",
                                            "property": "since"})["body"]["interval"] == "day"


def test_a_timeline_of_one_types_date_counts_the_rest_as_missing(client, fx, mixed) -> None:
    body = post(client, fx, "time-series", {"definition": mixed, "interval": "month",
                                            "property": "opened"})["body"]
    assert [p["count"] for p in body["points"]] == [2, 1]
    assert (body["total"], body["missing"]) == (5, 2)


def test_without_a_property_every_type_is_counted_by_when_it_changed(client, fx, mixed) -> None:
    body = post(client, fx, "time-series", {"definition": mixed, "interval": "month"})["body"]
    assert (sum(p["count"] for p in body["points"]), body["total"], body["missing"]) == (5, 5, 0)


def test_a_bad_interval_is_refused_for_a_union_too(client, fx, mixed) -> None:
    answer = post(client, fx, "time-series", {"definition": mixed, "interval": "fortnight"})
    assert answer["status"] == 422, answer
    assert answer["body"]["detail"] == (
        "unknown interval 'fortnight' (supported: day, week, month, auto)")


def test_a_part_naming_another_workspaces_type_is_not_found(client, fx, mixed) -> None:
    stranger = {"union": [*mixed["union"], {"object_type_id": str(uuid.uuid4()), "filters": []}]}
    assert post(client, fx, "group", {"definition": stranger, "property": "region"})[
        "status"] == 404


def test_a_union_narrowed_to_nothing_reads_as_empty(client, fx, mixed) -> None:
    nothing = {"union": [{**part, "filters": [
        {"property": "$primary_key", "op": "in", "value": []}]} for part in mixed["union"]]}
    assert post(client, fx, "group", {"definition": nothing, "property": "region"})[
        "body"]["groups"] == []
    body = post(client, fx, "distribution", {"definition": nothing, "property": "score"})["body"]
    assert (body["buckets"], body["total"]) == ([], 0)


@pytest.mark.parametrize("definition, said", [
    ({"union": []}, "holds at least one set"),
    ({"union": "sites"}, "holds at least one set"),
    ({"union": ["sites"]}, "an object set definition must be an object"),
])
def test_a_union_that_is_not_one_is_refused(client, fx, definition, said) -> None:
    answer = post(client, fx, "group", {"definition": definition, "property": "region"})
    assert answer["status"] == 422 and said in answer["body"]["detail"], answer
