"""Object sets over an interface (Foundry `ontology` p.61-62; §254).

> "Target the interface directly. A single workflow covers all implementing
> types." (p.61)

> "Build actions, functions, and applications against interfaces where
> possible." (p.62, item 3)

§251 built the interface, §252 made it findable and §253 gave it screens. All
three are metadata, which p.61 blesses in as many words - *"even where current
platform tooling does not fully support interface-backed workflows, designing
with interfaces establishes a foundation that pays off as support expands"*.
This is the first thing that **reads** an interface, and it is what the row's
last ○ was about.

**Most of this file needs no database**, because the whole of an interface set
that could be wrong is name translation and a merge - and both are functions
over data. What needs one is the end-to-end claim: that a page of `Inspectable`
holds Vehicles and Facilities, keyed by the interface's names, in one order.
"""
from __future__ import annotations

import io
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.services import instance_store  # noqa: E402
from src.services import interface_sets  # noqa: E402
from src.services import object_sets  # noqa: E402


def member(mapping: dict[str, str]) -> interface_sets.Member:
    return interface_sets.Member(
        object_type_id=uuid.uuid4(), property_mapping=mapping
    )


INSPECTABLE = {"last_inspection_date": "date", "inspection_status": "string"}


# ---- the restated constants (§191's shape) ----------------------------------
def test_the_sorts_are_the_object_set_sorts() -> None:
    """Restated so `interface_sets` keeps importing nothing, and asserted equal
    so the restatement cannot become a second vocabulary for four orderings
    that already have names."""
    assert interface_sets.SORTS == object_sets.SORTS


def test_the_paging_ceiling_is_one_store_page() -> None:
    """Not a policy - a hard ceiling. Both stores clamp a read to
    `INSTANCE_PAGE_SIZE`, so a merge that asked one type for more than that
    would silently drop real members off the end of the order."""
    assert interface_sets.MAX_DEPTH == instance_store.INSTANCE_PAGE_SIZE


def test_every_sort_has_a_key_to_merge_on() -> None:
    """The vacuity guard on the two above: a sort on the offered list with no
    entry in `_SORT_KEYS` is a `KeyError` inside `merge`, at read time."""
    assert set(interface_sets.SORTS) == set(interface_sets._SORT_KEYS)


# ---- the fan-out ------------------------------------------------------------
def test_the_browser_knows_the_same_paging_ceiling() -> None:
    """§190's pattern: a guard on the browser's copy, read from the file.

    A Next button cannot wait for a round trip to decide whether to be
    disabled, so `lib/interface-set.ts` restates `MAX_DEPTH` - and a
    restatement that drifted would offer a page whose only outcome is the
    server's refusal, which is §214's control that cannot work.
    """
    import re

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    source = open(
        os.path.join(root, "web", "src", "lib", "interface-set.ts"), encoding="utf-8"
    ).read()
    found = re.search(r"export const MAX_DEPTH = (\d+);", source)
    assert found, "MAX_DEPTH not found in interface-set.ts - has it been renamed?"
    assert int(found.group(1)) == interface_sets.MAX_DEPTH


def test_an_interface_nothing_implements_has_no_objects() -> None:
    with pytest.raises(interface_sets.InterfaceSetError) as exc:
        interface_sets.check_fan_out([], interface_name="Inspectable")
    assert "nothing implements Inspectable" in str(exc.value)


def test_a_wide_interface_is_refused_rather_than_truncated() -> None:
    """An interface set that silently covered the first ten of thirty types
    would be the wrong answer with no way to tell it was wrong."""
    many = [member({}) for _ in range(interface_sets.MAX_IMPLEMENTATIONS + 1)]
    with pytest.raises(interface_sets.InterfaceSetError) as exc:
        interface_sets.check_fan_out(many, interface_name="Inspectable")
    assert str(interface_sets.MAX_IMPLEMENTATIONS) in str(exc.value)
    # And the one below it is fine, which is what stops this passing against a
    # `check_fan_out` that refused everything.
    interface_sets.check_fan_out(many[:-1], interface_name="Inspectable")


def test_a_page_past_the_ceiling_is_refused_rather_than_clamped() -> None:
    interface_sets.check_depth(limit=25, offset=25)
    with pytest.raises(interface_sets.InterfaceSetError) as exc:
        interface_sets.check_depth(limit=25, offset=26)
    assert str(interface_sets.MAX_DEPTH) in str(exc.value)


# ---- sorting ----------------------------------------------------------------
def test_the_default_ordering_is_the_object_set_default() -> None:
    assert interface_sets.parse_sort(None) == object_sets.DEFAULT_SORT


def test_a_property_sort_is_refused_with_what_it_would_take() -> None:
    """Ordering by a property means comparing in that property's declared type
    (§221), which the stores implement - and which this module would have to
    re-implement to merge two types' pages into one order."""
    with pytest.raises(interface_sets.InterfaceSetError) as exc:
        interface_sets.parse_sort("capacity")
    assert "declared type" in str(exc.value)


# ---- translating filters ----------------------------------------------------
def test_a_filter_is_rewritten_onto_the_type_s_own_property() -> None:
    """p.66's mapping, which is the whole reason an interface is not a name
    match: a Vehicle whose column is `last_checked` is still Inspectable."""
    out = interface_sets.translate_filters(
        [{"property": "last_inspection_date", "op": "eq", "value": "2026-01-04"}],
        member=member({"last_inspection_date": "last_checked"}),
        declared=INSPECTABLE, interface_name="Inspectable",
    )
    assert out == [
        {"property": "last_checked", "op": "eq", "value": "2026-01-04"}
    ]


def test_a_filter_the_interface_does_not_declare_is_refused() -> None:
    """Passing it through would let a workflow written against `Inspectable`
    reach a Vehicle's `mileage` on the types that have one and match nothing on
    the types that do not - a set whose membership depends on which type a row
    came from."""
    with pytest.raises(interface_sets.InterfaceSetError) as exc:
        interface_sets.translate_filters(
            [{"property": "mileage", "op": "eq", "value": 10}],
            member=member({"mileage": "mileage"}),
            declared=INSPECTABLE, interface_name="Inspectable",
        )
    assert "does not declare 'mileage'" in str(exc.value)
    # The refusal names what it *does* declare, so the next attempt is informed.
    assert "last_inspection_date" in str(exc.value)


def test_filtering_an_optional_property_a_type_answers_nothing_to() -> None:
    """`None` means "no object of this type can match", not "no filter".

    Returning an empty filter list would return **every** object of that type,
    which is decision 0002's silent widening: more rows than were asked for,
    because something was unset. p.62's capability interfaces make this an
    ordinary shape rather than an edge case.
    """
    answer = interface_sets.filters_for(
        [{"property": "inspection_status", "op": "eq", "value": "due"}],
        member=member({"last_inspection_date": "last_checked"}),
        declared=INSPECTABLE, interface_name="Inspectable",
    )
    assert answer is None


def test_an_unmapped_property_that_is_not_filtered_on_is_not_a_problem() -> None:
    """The other half: a type that answers nothing to an optional property is
    still in the set, it just contributes no value for that property."""
    assert interface_sets.filters_for(
        [{"property": "last_inspection_date", "op": "eq", "value": "x"}],
        member=member({"last_inspection_date": "last_checked"}),
        declared=INSPECTABLE, interface_name="Inspectable",
    ) == [{"property": "last_checked", "op": "eq", "value": "x"}]


def test_no_filters_is_every_object_of_every_type() -> None:
    assert interface_sets.filters_for(
        [], member=member({}), declared=INSPECTABLE, interface_name="Inspectable"
    ) == []


def test_a_filter_that_is_not_an_object_is_refused() -> None:
    with pytest.raises(interface_sets.InterfaceSetError):
        interface_sets.translate_filters(
            ["last_inspection_date"], member=member({}),
            declared=INSPECTABLE, interface_name="Inspectable",
        )


def test_a_filter_with_no_property_is_refused() -> None:
    with pytest.raises(interface_sets.InterfaceSetError):
        interface_sets.translate_filters(
            [{"op": "eq", "value": 1}], member=member({}),
            declared=INSPECTABLE, interface_name="Inspectable",
        )


# ---- projecting rows --------------------------------------------------------
def test_a_row_comes_back_keyed_by_the_interface_s_names() -> None:
    out = interface_sets.project(
        {"last_checked": "2026-01-04", "state": "due", "mileage": 41000},
        member=member({"last_inspection_date": "last_checked",
                       "inspection_status": "state"}),
        declared=INSPECTABLE,
    )
    assert out == {"last_inspection_date": "2026-01-04", "inspection_status": "due"}


def test_everything_the_interface_does_not_declare_is_dropped() -> None:
    """The feature rather than a limitation. A workflow written against
    `Inspectable` must not get a Vehicle's `mileage` on some rows and a
    Facility's `capacity` on others - p.61's single workflow is defined against
    exactly that."""
    out = interface_sets.project(
        {"last_checked": "2026-01-04", "mileage": 41000},
        member=member({"last_inspection_date": "last_checked"}),
        declared=INSPECTABLE,
    )
    assert "mileage" not in out


def test_an_unanswered_optional_property_is_absent_rather_than_null() -> None:
    """Absent is what "this object has no such value" already means everywhere
    else that reads a property bag; a null would be a value."""
    out = interface_sets.project(
        {"last_checked": "2026-01-04"},
        member=member({"last_inspection_date": "last_checked",
                       "inspection_status": "state"}),
        declared=INSPECTABLE,
    )
    assert out == {"last_inspection_date": "2026-01-04"}


# ---- merging ----------------------------------------------------------------
def row(key: str, when: datetime) -> dict:
    return {"primary_key": key, "updated_at": when}


NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def test_two_types_pages_become_one_order() -> None:
    """The claim p.61 makes: one workflow over all implementing types. A page
    that concatenated the types would put every Vehicle before every Facility
    whatever their dates say."""
    vehicles = [row("V1", NOW), row("V2", NOW - timedelta(days=2))]
    facilities = [row("F1", NOW - timedelta(days=1))]
    merged = interface_sets.merge(
        [vehicles, facilities], sort="recent", limit=10, offset=0
    )
    assert [r["primary_key"] for r in merged] == ["V1", "F1", "V2"]


def test_oldest_reverses_it() -> None:
    vehicles = [row("V1", NOW), row("V2", NOW - timedelta(days=2))]
    facilities = [row("F1", NOW - timedelta(days=1))]
    merged = interface_sets.merge(
        [vehicles, facilities], sort="oldest", limit=10, offset=0
    )
    assert [r["primary_key"] for r in merged] == ["V2", "F1", "V1"]


def test_the_key_sorts_order_by_the_primary_key() -> None:
    merged = interface_sets.merge(
        [[row("V2", NOW)], [row("F1", NOW)]], sort="key", limit=10, offset=0
    )
    assert [r["primary_key"] for r in merged] == ["F1", "V2"]
    merged = interface_sets.merge(
        [[row("V2", NOW)], [row("F1", NOW)]], sort="-key", limit=10, offset=0
    )
    assert [r["primary_key"] for r in merged] == ["V2", "F1"]


def test_a_tie_is_broken_by_the_primary_key() -> None:
    """Two objects updated in the same transaction must not swap places between
    two reads of the same page. Without this the order is only as stable as
    each store's own tie-breaking, which is two answers on two stores."""
    first = interface_sets.merge(
        [[row("V9", NOW)], [row("F1", NOW)], [row("E5", NOW)]],
        sort="recent", limit=10, offset=0,
    )
    second = interface_sets.merge(
        [[row("E5", NOW)], [row("V9", NOW)], [row("F1", NOW)]],
        sort="recent", limit=10, offset=0,
    )
    assert [r["primary_key"] for r in first] == ["E5", "F1", "V9"]
    assert first == second


def test_the_page_is_taken_after_the_merge_not_before() -> None:
    """The reason every type is asked for `offset + limit` rows: the second
    page of the combined order is not the second page of any one type's."""
    a = [row("A1", NOW), row("A2", NOW - timedelta(days=3))]
    b = [row("B1", NOW - timedelta(days=1)), row("B2", NOW - timedelta(days=2))]
    page = interface_sets.merge([a, b], sort="recent", limit=2, offset=1)
    assert [r["primary_key"] for r in page] == ["B1", "B2"]


def test_a_missing_key_sorts_last_rather_than_raising() -> None:
    """A row with no `updated_at` should not take a whole page down with it.
    Nothing produces one today; this is about what happens when something
    does."""
    merged = interface_sets.merge(
        [[row("A", NOW)], [{"primary_key": "B"}]],
        sort="recent", limit=10, offset=0,
    )
    assert [r["primary_key"] for r in merged] == ["A", "B"]


# ---- end to end -------------------------------------------------------------
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


def _upload(client: TestClient, fx: Fixture, name: str, csv: bytes) -> str:
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets/upload",
        headers=hdr(fx.editor_sub),
        data={"name": name}, files={"file": ("d.csv", io.BytesIO(csv), "text/csv")},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _map_and_sync(
    client: TestClient, fx: Fixture, type_id: str, dataset: str, pk: str,
    cols: dict[str, str],
) -> None:
    base = f"/api/workspaces/{fx.workspace}/projects/{fx.project}"
    r = client.post(
        f"{base}/object-type-sources", headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "dataset_id": dataset,
              "primary_key_column": pk, "column_mappings": cols},
    )
    assert r.status_code == 201, r.text
    r = client.post(
        f"{base}/object-type-sources/{r.json()['id']}/sync", headers=hdr(fx.editor_sub)
    )
    assert r.status_code == 200, r.text


def test_a_page_of_an_interface_holds_two_types_keyed_alike(
    client: TestClient, fx: Fixture
) -> None:
    """The whole claim, end to end: two object types with differently named
    columns, one interface, one page, one vocabulary.

    Seeded through the dataset sync, because that is the only way an instance
    exists here - mark-and-sweep re-materialises every instance from its source
    on every sync, so a row written any other way is a row the next sync
    deletes.
    """
    tag = uuid.uuid4().hex[:6]
    interface = client.post(
        f"{wbase(fx)}/interfaces", headers=hdr(fx.editor_sub),
        json={"api_name": f"Inspectable{tag}", "display_name": f"Inspectable {tag}",
              "properties": [
                  {"api_name": "last_inspection_date", "display_name": "Last inspection",
                   "data_type": "date"},
              ]},
    )
    assert interface.status_code == 201, interface.text
    interface = interface.json()

    made = []
    for name, column in (("vehicle", "last_checked"), ("facility", "surveyed_on")):
        created = client.post(
            f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
            json={"api_name": f"{name}_{tag}", "display_name": f"{name.title()} {tag}",
                  "properties": [
                      {"api_name": "id", "display_name": "Id", "data_type": "string"},
                      {"api_name": column, "display_name": "When", "data_type": "date"},
                  ],
                  "title_property": "id"},
        )
        assert created.status_code == 201, created.text
        kind = created.json()
        assert client.put(
            f"{wbase(fx)}/object-types/{kind['id']}/interfaces",
            headers=hdr(fx.editor_sub),
            json=[{"interface_id": interface["id"],
                   "property_mapping": {"last_inspection_date": column}}],
        ).status_code == 200
        csv = f"id,{column}\n{name}-1,2026-01-04\n".encode()
        dataset = _upload(client, fx, f"{name} {tag}", csv)
        _map_and_sync(client, fx, kind["id"], dataset, "id", {column: column})
        made.append((kind, column))

    r = client.post(
        f"{wbase(fx)}/interfaces/{interface['id']}/evaluate",
        headers=hdr(fx.viewer_sub), json={},
    )
    assert r.status_code == 200, r.text
    page = r.json()
    assert page["total"] == 2, page
    assert len(page["instances"]) == 2
    # **One vocabulary, two types.** The columns are `last_checked` and
    # `surveyed_on`; neither name appears in the answer.
    for row_out in page["instances"]:
        assert set(row_out["properties"]) == {"last_inspection_date"}, row_out
        assert row_out["properties"]["last_inspection_date"] == "2026-01-04"
    assert {row_out["object_type_name"] for row_out in page["instances"]} == {
        kind["display_name"] for kind, _ in made
    }
    assert sorted(page["object_types"]) == sorted(
        kind["display_name"] for kind, _ in made
    )


def test_a_filter_written_against_the_interface_reaches_both_types(
    client: TestClient, fx: Fixture
) -> None:
    """p.66's mapping doing the work it exists for: one filter, two column
    names, and neither type's name in the request."""
    tag = uuid.uuid4().hex[:6]
    interface = client.post(
        f"{wbase(fx)}/interfaces", headers=hdr(fx.editor_sub),
        json={"api_name": f"Tagged{tag}", "display_name": f"Tagged {tag}",
              "properties": [{"api_name": "tag", "display_name": "Tag",
                              "data_type": "string"}]},
    ).json()

    for name, column, values in (
        ("alpha", "label", ["keep", "drop"]),
        ("beta", "marker", ["keep"]),
    ):
        kind = client.post(
            f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
            json={"api_name": f"{name}_{tag}", "display_name": f"{name.title()} {tag}",
                  "properties": [
                      {"api_name": "id", "display_name": "Id", "data_type": "string"},
                      {"api_name": column, "display_name": "L", "data_type": "string"},
                  ],
                  "title_property": "id"},
        ).json()
        assert client.put(
            f"{wbase(fx)}/object-types/{kind['id']}/interfaces",
            headers=hdr(fx.editor_sub),
            json=[{"interface_id": interface["id"],
                   "property_mapping": {"tag": column}}],
        ).status_code == 200
        rows = "".join(f"{name}-{i},{v}\n" for i, v in enumerate(values))
        csv = f"id,{column}\n{rows}".encode()
        _map_and_sync(
            client, fx, kind["id"], _upload(client, fx, f"{name} {tag}", csv),
            "id", {column: column},
        )

    r = client.post(
        f"{wbase(fx)}/interfaces/{interface['id']}/evaluate",
        headers=hdr(fx.viewer_sub),
        json={"filters": [{"property": "tag", "op": "eq", "value": "keep"}]},
    )
    assert r.status_code == 200, r.text
    page = r.json()
    assert page["total"] == 2, page
    assert {i["primary_key"] for i in page["instances"]} == {"alpha-0", "beta-0"}


def test_a_type_that_answers_nothing_to_a_filtered_property_is_not_read(
    client: TestClient, fx: Fixture
) -> None:
    """p.62's capability interfaces make this ordinary: one mandatory field and
    two optional ones, and a type that implements the capability without the
    optional part.

    Filtering on the part it does not answer must exclude it - and the answer
    says so, because "no Facility matched" and "Facility was never consulted"
    are different facts about the same empty result.
    """
    tag = uuid.uuid4().hex[:6]
    interface = client.post(
        f"{wbase(fx)}/interfaces", headers=hdr(fx.editor_sub),
        json={"api_name": f"Noted{tag}", "display_name": f"Noted {tag}",
              "properties": [
                  {"api_name": "code", "display_name": "Code", "data_type": "string"},
                  {"api_name": "note", "display_name": "Note",
                   "data_type": "string", "required": False},
              ]},
    ).json()

    kinds = {}
    for name, mapping in (
        ("full", {"code": "code", "note": "note"}),
        ("bare", {"code": "code"}),
    ):
        columns = ["code", "note"] if name == "full" else ["code"]
        kind = client.post(
            f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
            json={"api_name": f"{name}_{tag}", "display_name": f"{name.title()} {tag}",
                  "properties": [
                      {"api_name": c, "display_name": c, "data_type": "string"}
                      for c in columns
                  ],
                  "title_property": "code"},
        ).json()
        assert client.put(
            f"{wbase(fx)}/object-types/{kind['id']}/interfaces",
            headers=hdr(fx.editor_sub),
            json=[{"interface_id": interface["id"], "property_mapping": mapping}],
        ).status_code == 200
        header = ",".join(columns)
        row = ",".join(["x"] * len(columns))
        csv = f"{header}\n{row}\n".encode()
        _map_and_sync(
            client, fx, kind["id"], _upload(client, fx, f"{name} {tag}", csv),
            "code", {c: c for c in columns},
        )
        kinds[name] = kind

    # Unfiltered: both types are read, both rows come back.
    everything = client.post(
        f"{wbase(fx)}/interfaces/{interface['id']}/evaluate",
        headers=hdr(fx.viewer_sub), json={},
    ).json()
    assert everything["total"] == 2
    assert sorted(everything["object_types"]) == sorted(
        k["display_name"] for k in kinds.values()
    )

    # Filtered on the optional property: only the type that answers it.
    narrowed = client.post(
        f"{wbase(fx)}/interfaces/{interface['id']}/evaluate",
        headers=hdr(fx.viewer_sub),
        json={"filters": [{"property": "note", "op": "eq", "value": "x"}]},
    )
    assert narrowed.status_code == 200, narrowed.text
    narrowed = narrowed.json()
    assert narrowed["total"] == 1, narrowed
    assert narrowed["object_types"] == [kinds["full"]["display_name"]], narrowed


def test_the_second_page_is_the_second_page_of_the_merged_order(
    client: TestClient, fx: Fixture
) -> None:
    """Every type is asked for `offset + limit` rows from the top, because the
    second page of the combined order is not the second page of any one type's.

    Sorted by primary key, which is the one ordering this test can predict
    without knowing which row the sync happened to touch last.
    """
    tag = uuid.uuid4().hex[:6]
    interface = client.post(
        f"{wbase(fx)}/interfaces", headers=hdr(fx.editor_sub),
        json={"api_name": f"Keyed{tag}", "display_name": f"Keyed {tag}",
              "properties": [{"api_name": "code", "display_name": "Code",
                              "data_type": "string"}]},
    ).json()

    # **Keys chosen so the merged order interleaves.** The first attempt used
    # a1/a3 and b2/b4, whose key order happens to be every `a` then every `b` -
    # exactly what concatenating the types would produce, so the test would
    # have passed against no merge at all.
    for name, keys in (("aa", ["a1", "c3"]), ("bb", ["b2", "d4"])):
        kind = client.post(
            f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
            json={"api_name": f"{name}_{tag}", "display_name": f"{name.upper()} {tag}",
                  "properties": [{"api_name": "code", "display_name": "Code",
                                  "data_type": "string"}],
                  "title_property": "code"},
        ).json()
        assert client.put(
            f"{wbase(fx)}/object-types/{kind['id']}/interfaces",
            headers=hdr(fx.editor_sub),
            json=[{"interface_id": interface["id"],
                   "property_mapping": {"code": "code"}}],
        ).status_code == 200
        csv = ("code\n" + "".join(f"{k}\n" for k in keys)).encode()
        _map_and_sync(
            client, fx, kind["id"], _upload(client, fx, f"{name} {tag}", csv),
            "code", {"code": "code"},
        )

    def page(offset: int) -> list[str]:
        r = client.post(
            f"{wbase(fx)}/interfaces/{interface['id']}/evaluate",
            headers=hdr(fx.viewer_sub),
            json={"sort": "key", "limit": 2, "offset": offset},
        )
        assert r.status_code == 200, r.text
        assert r.json()["total"] == 4, r.text
        return [i["primary_key"] for i in r.json()["instances"]]

    # **The interleaving is the assertion.** Concatenating the types would give
    # a1, c3 then b2, d4; the merged order alternates.
    assert page(0) == ["a1", "b2"]
    assert page(2) == ["c3", "d4"]


def test_a_page_past_the_ceiling_is_refused_by_the_api(
    client: TestClient, fx: Fixture
) -> None:
    tag = uuid.uuid4().hex[:6]
    interface = client.post(
        f"{wbase(fx)}/interfaces", headers=hdr(fx.editor_sub),
        json={"api_name": f"Deep{tag}", "display_name": f"Deep {tag}"},
    ).json()
    r = client.post(
        f"{wbase(fx)}/interfaces/{interface['id']}/evaluate",
        headers=hdr(fx.viewer_sub),
        json={"limit": interface_sets.MAX_DEPTH, "offset": 1},
    )
    assert r.status_code == 422, r.text
    assert str(interface_sets.MAX_DEPTH) in r.text


def test_a_filter_the_interface_does_not_declare_is_refused_by_the_api(
    client: TestClient, fx: Fixture
) -> None:
    tag = uuid.uuid4().hex[:6]
    interface = client.post(
        f"{wbase(fx)}/interfaces", headers=hdr(fx.editor_sub),
        json={"api_name": f"Shaped{tag}", "display_name": f"Shaped {tag}",
              "properties": [{"api_name": "tag", "display_name": "Tag",
                              "data_type": "string"}]},
    ).json()
    kind = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"thing_{tag}", "display_name": f"Thing {tag}",
              "properties": [{"api_name": "tag", "display_name": "Tag",
                              "data_type": "string"}],
              "title_property": "tag"},
    ).json()
    assert client.put(
        f"{wbase(fx)}/object-types/{kind['id']}/interfaces",
        headers=hdr(fx.editor_sub),
        json=[{"interface_id": interface["id"],
               "property_mapping": {"tag": "tag"}}],
    ).status_code == 200

    r = client.post(
        f"{wbase(fx)}/interfaces/{interface['id']}/evaluate",
        headers=hdr(fx.viewer_sub),
        json={"filters": [{"property": "mileage", "op": "eq", "value": 1}]},
    )
    assert r.status_code == 422, r.text
    assert "does not declare" in r.text


def test_an_interface_nothing_implements_is_refused_by_the_api(
    client: TestClient, fx: Fixture
) -> None:
    tag = uuid.uuid4().hex[:6]
    interface = client.post(
        f"{wbase(fx)}/interfaces", headers=hdr(fx.editor_sub),
        json={"api_name": f"Unused{tag}", "display_name": f"Unused {tag}"},
    ).json()
    r = client.post(
        f"{wbase(fx)}/interfaces/{interface['id']}/evaluate",
        headers=hdr(fx.viewer_sub), json={},
    )
    assert r.status_code == 422, r.text
    assert "nothing implements" in r.text


def test_an_interface_from_another_workspace_is_not_readable(
    client: TestClient, fx: Fixture
) -> None:
    """The scope check §10 asks for on every id that arrives in a URL."""
    r = client.post(
        f"{wbase(fx)}/interfaces/{uuid.uuid4()}/evaluate",
        headers=hdr(fx.viewer_sub), json={},
    )
    assert r.status_code == 404, r.text
