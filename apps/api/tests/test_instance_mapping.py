"""One index per object type, mapped from declared types (decision 0006 §1-§2).

Pure: no client, no connection, no cluster. Every rule the mapping expresses is
checkable here, which is the reason the type decisions live in their own module
rather than inline in the store.
"""
from __future__ import annotations

import uuid

import pytest

import sys, os  # noqa: E401
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import instance_mapping as im  # noqa: E402


def props(*pairs: tuple[str, str]) -> list[dict]:
    return [{"api_name": name, "data_type": kind} for name, kind in pairs]


def fields(properties: list[dict]) -> dict:
    return im.mapping_for(properties)["mappings"]["properties"]["properties"]["properties"]


# ---- the type table ----------------------------------------------------------
def test_every_declared_type_has_a_field() -> None:
    """The enum is `property_data_type` (db 0003, widened by db 0029), and a
    type missing from the table maps as a string - findable but never
    orderable, silently. Listed here rather than derived from the module, so
    the two disagree loudly."""
    assert sorted(im.FIELD_TYPES) == sorted([
        "string", "integer", "float", "boolean",
        "date", "timestamp", "geopoint", "json", "attachment",
    ])


def test_a_string_keeps_both_readers() -> None:
    """`text` for the explorer, which searches words inside a value, and a
    `keyword` subfield for link traversal, which needs equality on the whole
    one. Either alone breaks a feature that exists."""
    field = im.field_for("string")
    assert field["type"] == "text"
    assert field["fields"]["keyword"]["type"] == "keyword"


def test_a_long_join_key_stays_indexed() -> None:
    """A dynamic mapping's `ignore_above` is 256, past which a keyword stops
    being indexed **silently** - so a long join key traverses to nothing for a
    reason invisible from outside."""
    assert im.field_for("string")["fields"]["keyword"]["ignore_above"] == 8192


def test_an_integer_is_a_long_and_a_float_is_a_double() -> None:
    """OpenSearch's `integer` is 32-bit and its `float` is single-precision.
    An id column past two billion is ordinary for a source dataset, and single
    precision silently rounds a value the source held exactly."""
    assert im.field_for("integer") == {"type": "long"}
    assert im.field_for("float") == {"type": "double"}


def test_a_date_and_a_timestamp_are_one_field_type() -> None:
    """A date *is* a timestamp at midnight, so one field type is right - and
    the format list is what stops the cluster guessing, since db 0029 stores
    both as ISO-8601 with the offset preserved when the source had one."""
    assert im.field_for("date") == im.field_for("timestamp")
    assert im.field_for("date")["type"] == "date"
    assert "strict_date_optional_time" in im.field_for("date")["format"]
    assert "epoch_millis" in im.field_for("date")["format"]


def test_a_geopoint_is_a_geo_point() -> None:
    """0006 §3: a bounding box as four comparisons on two numbers gets the
    antimeridian silently wrong. `geo_point` is what makes `geo_bounding_box`
    available at all."""
    assert im.field_for("geopoint") == {"type": "geo_point"}


def test_a_composite_value_is_not_indexed() -> None:
    """Nothing filters on a `json` blob or an attachment descriptor, and
    indexing one would map whatever keys the first document happened to carry -
    a mapping written by data rather than by a declaration."""
    for kind in ("json", "attachment"):
        assert im.field_for(kind) == {"type": "object", "enabled": False}, kind


def test_an_unknown_declared_type_falls_back_to_a_string() -> None:
    """A row written by a future migration against an older API. Mapped rather
    than refused: an index that cannot be created makes every instance of that
    type unreadable, which is a worse failure than an unorderable property."""
    assert im.field_for("quaternion") == im.field_for("string")
    assert im.field_for(None) == im.field_for("string")
    assert im.field_for(7) == im.field_for("string")


def test_the_table_is_not_shared_between_callers() -> None:
    """`field_for` returns a copy. A caller that mutated the answer - adding a
    `null_value`, say - would change the mapping every later index got, and the
    two indices would differ for no reason anybody could find."""
    first = im.field_for("integer")
    first["type"] = "text"
    assert im.field_for("integer") == {"type": "long"}


# ---- what may be ordered (0006 §2) -------------------------------------------
def test_the_orderable_types_are_the_numeric_and_temporal_ones() -> None:
    assert sorted(im.ORDERABLE_TYPES) == ["date", "float", "integer", "timestamp"]


def test_a_string_is_never_orderable() -> None:
    """**Refused permanently by 0006, not postponed.** Postgres orders by the
    database collation and OpenSearch by the keyword's byte order, so `'Z' <
    'a'` is true in one and false in the other for any non-C collation - the
    exact class of bug this file exists to remove."""
    assert "string" not in im.ORDERABLE_TYPES


def test_a_boolean_and_a_composite_are_not_orderable() -> None:
    for kind in ("boolean", "json", "attachment", "geopoint"):
        assert kind not in im.ORDERABLE_TYPES, kind


def test_everything_orderable_is_a_declared_type() -> None:
    """The other direction: an entry naming a type the ontology cannot declare
    is a rule with no subject, and it would hide the fact that the real name is
    spelled differently."""
    for kind in im.ORDERABLE_TYPES:
        assert kind in im.FIELD_TYPES, kind


# ---- index names -------------------------------------------------------------
def test_an_index_is_named_for_its_object_type() -> None:
    type_id = uuid.UUID("11111111-2222-3333-4444-555555555555")
    assert im.index_name("ws-ab12-", type_id) == "ws-ab12-objects-11111111-2222-3333-4444-555555555555"


def test_two_object_types_get_two_indices() -> None:
    """The whole of 0006 §1: an object type *is* a schema, and two schemas
    cannot share one mapping. A workspace holding an Order whose `status` is a
    string and a Reading whose `status` is an integer is the case that made
    the single index not merely hard but inexpressible."""
    a, b = uuid.uuid4(), uuid.uuid4()
    assert im.index_name("ws-", a) != im.index_name("ws-", b)


def test_the_pattern_does_not_match_the_index_it_replaces() -> None:
    """**A half-migrated workspace must not return each instance twice.** The
    explorer searches `{prefix}objects-*`, and the single index this replaces
    is `{prefix}object-instances` - they differ at the character after
    `object`, which is what makes the two nameable apart. Asserted with a
    matcher rather than by eye, because the two names are one character from
    being the same bug."""
    import fnmatch

    pattern = im.all_types_pattern("ws-ab12-")
    assert fnmatch.fnmatch(im.index_name("ws-ab12-", uuid.uuid4()), pattern)
    assert not fnmatch.fnmatch(im.legacy_index_name("ws-ab12-"), pattern)


def test_the_pattern_does_not_reach_another_workspace() -> None:
    """The prefix is the workspace boundary (db 0002), and a pattern that
    crossed it would make the explorer return another tenant's objects."""
    import fnmatch

    assert not fnmatch.fnmatch(
        im.index_name("ws-other-", uuid.uuid4()), im.all_types_pattern("ws-ab12-")
    )


# ---- the mapping -------------------------------------------------------------
def test_a_declared_property_is_mapped_by_its_type() -> None:
    mapped = fields(props(("capacity", "integer"), ("name", "string"), ("opened", "date")))
    assert mapped["capacity"] == {"type": "long"}
    assert mapped["name"]["type"] == "text"
    assert mapped["opened"]["type"] == "date"


def test_an_undeclared_property_is_refused_rather_than_guessed() -> None:
    """`dynamic: "strict"` is the point of the exercise. Left dynamic, the
    first document carrying an undeclared property decides its type for every
    document after it - and the declaration would have been for nothing."""
    body = im.mapping_for(props(("capacity", "integer")))
    assert body["mappings"]["properties"]["properties"]["dynamic"] == "strict"


def test_the_document_s_own_fields_are_declared_too() -> None:
    """`primary_key` and `source_id` are compared for exact equality by every
    delete and every traversal, and `updated_at` is what two of the four sorts
    order by. A dynamic guess would make `primary_key` analysed text, so a key
    containing a space would match a different row."""
    top = im.mapping_for([])["mappings"]["properties"]
    assert top["object_type_id"] == {"type": "keyword"}
    assert top["source_id"] == {"type": "keyword"}
    assert top["primary_key"] == {"type": "keyword"}
    assert top["updated_at"] == {"type": "date"}


def test_a_type_with_no_declared_properties_still_gets_an_index() -> None:
    """Instances can exist before properties do. An index that appeared only
    once somebody declared a property would make the first sync fail for a
    reason nobody could act on."""
    for empty in ([], None):
        body = im.mapping_for(empty)
        assert body["mappings"]["properties"]["properties"]["properties"] == {}
        assert body["mappings"]["properties"]["primary_key"] == {"type": "keyword"}


def test_a_junk_property_row_is_skipped_rather_than_mapped() -> None:
    """These rows come from a query, but a property with a blank api_name is
    reachable through an older migration - and a field named `""` is a mapping
    nothing can ever write to."""
    mapped = fields([None, 7, {}, {"api_name": ""}, {"api_name": "ok", "data_type": "integer"}])
    assert mapped == {"ok": {"type": "long"}}


# ---- adding versus retyping (0006 §4) ----------------------------------------
def test_a_new_property_is_an_addition_not_a_reindex() -> None:
    """OpenSearch adds a field to an existing mapping happily, and the
    documents already indexed simply have no value for it. Telling this apart
    from a *changed* type is what keeps somebody adding a column from
    rewriting a type's instances."""
    live = im.mapping_for(props(("capacity", "integer")))
    wanted = props(("capacity", "integer"), ("name", "string"))
    assert sorted(im.added_fields(live, wanted)) == ["name"]
    assert im.retyped_fields(live, wanted) == []


def test_a_changed_type_is_a_reindex_not_an_addition() -> None:
    live = im.mapping_for(props(("capacity", "string")))
    wanted = props(("capacity", "integer"))
    assert im.retyped_fields(live, wanted) == ["capacity"]
    assert im.added_fields(live, wanted) == {}


def test_a_date_becoming_a_timestamp_is_not_a_reindex() -> None:
    """The one pair that shares a field type. Reindexing a workspace's
    instances to change nothing is a cost paid for a difference that does not
    exist."""
    live = im.mapping_for(props(("seen", "date")))
    assert im.retyped_fields(live, props(("seen", "timestamp"))) == []


def test_a_removed_property_is_neither() -> None:
    """A field the mapping has and the ontology no longer declares. OpenSearch
    cannot drop a field from a mapping, and reporting it would make every
    property deletion look like a reindex."""
    live = im.mapping_for(props(("capacity", "integer"), ("gone", "string")))
    wanted = props(("capacity", "integer"))
    assert im.added_fields(live, wanted) == {}
    assert im.retyped_fields(live, wanted) == []


def test_two_retyped_properties_are_both_named() -> None:
    """Named rather than counted, because the impact report (0006 §4) has to
    say which - "this changes a property's type" is not something anybody can
    consent to without knowing whose."""
    live = im.mapping_for(props(("a", "string"), ("b", "string"), ("c", "string")))
    wanted = props(("a", "integer"), ("b", "string"), ("c", "date"))
    assert im.retyped_fields(live, wanted) == ["a", "c"]


def test_a_mapping_keyed_by_index_name_is_understood() -> None:
    """What `indices.get_mapping` actually returns. Read wrongly, every field
    reads as new and gets added again - which succeeds, quietly, and leaves
    the reindex check permanently answering "nothing changed"."""
    body = im.mapping_for(props(("capacity", "integer")))
    wrapped = {"ws-objects-abc": body}
    assert im.added_fields(wrapped, props(("capacity", "integer"), ("n", "string"))) == {
        "n": im.field_for("string")
    }
    assert im.retyped_fields(wrapped, props(("capacity", "string"))) == ["capacity"]


def test_a_missing_or_junk_mapping_reports_every_field_as_new() -> None:
    """An index that does not exist yet. Every field is an addition, which is
    what creating it will do - and none is a retype, because there is nothing
    to have changed from."""
    for absent in (None, {}, "nonsense", {"mappings": {}}):
        assert sorted(im.added_fields(absent, props(("a", "integer")))) == ["a"], absent
        assert im.retyped_fields(absent, props(("a", "integer"))) == [], absent


def test_comparing_uses_the_field_type_rather_than_the_whole_mapping() -> None:
    """A mapping a cluster echoes back carries defaults nobody wrote. Compared
    as dictionaries, every index would report a reindex on every check - and a
    reindex nobody needs is the most expensive false alarm this platform has."""
    live = {"mappings": {"properties": {"properties": {"properties": {
        "name": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
                 "norms": True, "similarity": "BM25"},
    }}}}}
    assert im.retyped_fields(live, props(("name", "string"))) == []
