"""`ontology` p.130-131's regular expression search (§728), the pattern
language alone - and that the three dialects it is written in agree.

Each example below is one p.131 gives, with what it says it matches and what
it does not. The Postgres check asks the database the same question the
reference answers, since a pattern one store read differently is a value one
store found and the other did not.
"""
from __future__ import annotations

import os
import re
import sys

import psycopg
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import regex_search  # noqa: E402

# (pattern, matches, does not match) - p.130-131's own examples.
EXAMPLES = [
    ("cat", ["cat"], ["concatenate"]),
    (".*cat.*", ["concatenate", "cat"], ["dog"]),
    ("c.t", ["cat", "cot", "cut"], ["ct", "cart"]),
    ("colou?r", ["color", "colour"], ["colouur"]),
    ("go+d", ["god", "good", "goood"], ["gd"]),
    ("go*d", ["gd", "god", "good", "goood"], ["gad"]),
    ("go{2}d", ["good"], ["god", "goood"]),
    ("go{2,}d", ["good", "goood"], ["god"]),
    ("go{2,4}d", ["good", "goood", "gooood"], ["god", "goooood"]),
    ("cat|dog", ["cat", "dog"], ["catdog", "cow"]),
    ("(un)?happy", ["happy", "unhappy"], ["unhap"]),
    ("gr[ae]y", ["gray", "grey"], ["griy"]),
    ("[a-z]", ["q"], ["Q", "1"]),
    ("[A-Za-z]", ["Q", "q"], ["1"]),
    ("[^0-9]", ["a", "-"], ["5"]),
    ("[-x]", ["-", "x"], ["y"]),
    (r"[a\-z]", ["-", "a", "z"], ["b"]),
    ('"v2.0"', ["v2.0"], ["v2X0", "v200"]),
    (r"\d{3}-\d{4}", ["555-1234", "800-5678"], ["55-1234", "abc-defg"]),
    (r"\D+", ["abc"], ["a1"]),
    (r"\w+\s\w+", ["hello world", "John Smith"], ["hello", "hello  world"]),
    (r"\S+", ["x"], ["a b"]),
    (r"\W", ["!"], ["a"]),
    (r"example\.com", ["example.com"], ["exampleXcom"]),
    # Every other character is itself - Lucene's optional operators included.
    ("a#b@c&d<e>f~g", ["a#b@c&d<e>f~g"], ["ab"]),
]


@pytest.mark.parametrize("pattern,yes,no", EXAMPLES)
def test_p131_s_examples(pattern: str, yes: list[str], no: list[str]) -> None:
    compiled = regex_search.parse(pattern)
    for value in yes:
        assert compiled.matches(value), (pattern, value, compiled.python)
    for value in no:
        assert not compiled.matches(value), (pattern, value, compiled.python)


@pytest.mark.parametrize("pattern,yes,no", EXAMPLES)
def test_postgres_reads_each_the_same(pattern: str, yes: list[str], no: list[str]) -> None:
    dsn = os.environ["TEST_ADMIN_DSN"]
    compiled = regex_search.parse(pattern)
    with psycopg.connect(dsn) as conn:
        for value, expected in [*((v, True) for v in yes), *((v, False) for v in no)]:
            got = conn.execute("SELECT %s ~ %s", (value, compiled.postgres)).fetchone()[0]
            assert got is expected, (pattern, value, compiled.postgres)


@pytest.mark.parametrize("pattern,yes,no", EXAMPLES)
def test_the_lucene_dialect_reads_the_same_as_the_reference(
    pattern: str, yes: list[str], no: list[str],
) -> None:
    """Lucene's regexp anchors both ends, as `re.fullmatch` does; the dialect
    is written in the subset the two read alike (the OpenSearch fixture leans
    on this), so a full match of it is the same answer."""
    compiled = regex_search.parse(pattern)
    for value, expected in [*((v, True) for v in yes), *((v, False) for v in no)]:
        assert (re.fullmatch(compiled.lucene, value) is not None) is expected, (
            pattern, value, compiled.lucene)


def test_the_lucene_dialect_names_no_class_lucene_might_not_know() -> None:
    """`\\d` and friends are written as plain sets, and Lucene's optional
    operators are escaped, so a cluster reads nothing p.131 did not say."""
    assert regex_search.parse(r"\d\w").lucene == "[0-9][A-Za-z0-9_]"
    assert regex_search.parse(r"\D").lucene == "[^0-9]"
    assert regex_search.parse("a#b~c").lucene == r"a\#b\~c"
    assert regex_search.parse('"a.b"').lucene == r"(a\.b)"


@pytest.mark.parametrize("pattern,why", [
    ("^cat", "anchors are not supported"),
    ("cat$", "anchors are not supported"),
    ("[ab", "has no closing ]"),
    ('"ab', 'has no closing "'),
    ("a{2", "must be {n}"),
    ("a{x}", "must be {n}"),
    ("a{4,2}", "runs backwards"),
    ("[z-a]", "runs backwards"),
    ("ab\\", "nothing to escape"),
    (r"[\D]", "cannot be used inside"),
    ("*a", "not a pattern"),
    ("(ab", "not a pattern"),
    ("", "non-empty text"),
    ("a" * (regex_search.MAX_LENGTH + 1), "at most"),
])
def test_what_p130_does_not_allow_is_refused_with_why(pattern: str, why: str) -> None:
    with pytest.raises(regex_search.RegexError, match=re.escape(why)):
        regex_search.parse(pattern)


def test_a_pattern_that_is_not_text_is_refused() -> None:
    for raw in (None, 5, ["a"]):
        with pytest.raises(regex_search.RegexError, match="non-empty text"):
            regex_search.parse(raw)


def test_a_set_filter_reads_the_pattern_once_and_refuses_a_number() -> None:
    import uuid

    from src.services import object_sets

    tid = str(uuid.uuid4())
    parsed = object_sets.parse(
        {"object_type_id": tid, "filters": [{"property": "code", "op": "matches_regex",
                                             "value": "A\\d+"}]},
        property_types={"code": "string", "size": "integer"})
    [f] = parsed.filters
    assert isinstance(f.value, regex_search.Pattern)
    assert object_sets.matches({"code": "A12"}, parsed.filters)
    assert not object_sets.matches({"code": "xA12"}, parsed.filters)
    assert not object_sets.matches({}, parsed.filters)
    with pytest.raises(ValueError, match="a integer property; a regular expression searches"):
        object_sets.parse(
            {"object_type_id": tid, "filters": [{"property": "size", "op": "matches_regex",
                                                 "value": "1.*"}]},
            property_types={"code": "string", "size": "integer"})
    with pytest.raises(ValueError, match="the regular expression on 'code': \\^ and \\$"):
        object_sets.parse(
            {"object_type_id": tid, "filters": [{"property": "code", "op": "matches_regex",
                                                 "value": "^A"}]})


def test_opensearch_is_asked_in_lucene_s_dialect_on_the_whole_value() -> None:
    """The fixture reads Lucene's dialect with Python's `re`, so it cannot
    tell the two apart; a cluster can (`\\d`, the escaped operators). So the
    query the gateway forms is pinned: Lucene's text, on the `.keyword`
    subfield that holds the whole value (p.130's "single unanalyzed value")."""
    import json
    import uuid

    from src.services import instance_store, object_sets

    tid = uuid.uuid4()
    parsed = object_sets.parse({"object_type_id": str(tid), "filters": [
        {"property": "code", "op": "matches_regex", "value": r"A#\d+"}]})
    body = json.dumps(instance_store.OpenSearchInstanceStore._set_clauses(tid, parsed.filters))
    assert json.dumps({"regexp": {"properties.code.keyword": {"value": r"A\#[0-9]+"}}}) in body
