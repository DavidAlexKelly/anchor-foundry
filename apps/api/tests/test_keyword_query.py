"""p.452's advanced keyword syntax (§543): the grammar, and what it means.

> "… you can chain search operations with each other and define the order of
> operations through brackets. If no brackets are defined, common Boolean
> logic is used to determine precedence of operators as follows: quotations,
> parentheses, NOT, AND, OR." (p.452)

Both stores against this meaning is `test_object_sets.py`'s CASES; this is the
parse, and the reference `query_matches` those cases are held to.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.object_sets import (  # noqa: E402
    MAX_QUERY_LENGTH, MAX_QUERY_TERMS, QueryAnd, QueryNot, QueryOr, QueryTerm, parse,
    parse_keyword_query, query_matches, query_terms,
)

T = QueryTerm


def test_precedence_is_not_then_and_then_or() -> None:
    assert parse_keyword_query("a OR b AND NOT c") == QueryOr(
        (T("a"), QueryAnd((T("b"), QueryNot(T("c"))))))
    assert parse_keyword_query("NOT a AND b") == QueryAnd((QueryNot(T("a")), T("b")))


def test_brackets_order_it_otherwise() -> None:
    assert parse_keyword_query("(a OR b) AND c") == QueryAnd(
        (QueryOr((T("a"), T("b"))), T("c")))
    assert parse_keyword_query("NOT (a OR b)") == QueryNot(QueryOr((T("a"), T("b"))))
    assert parse_keyword_query("((a))") == T("a")


def test_side_by_side_is_and_and_chains_flatten() -> None:
    assert parse_keyword_query("a b c") == QueryAnd((T("a"), T("b"), T("c")))
    assert parse_keyword_query("a AND b AND c") == QueryAnd((T("a"), T("b"), T("c")))
    assert parse_keyword_query("a OR b OR c") == QueryOr((T("a"), T("b"), T("c")))
    assert parse_keyword_query("NOT NOT a") == QueryNot(QueryNot(T("a")))
    assert parse_keyword_query("a NOT b") == QueryAnd((T("a"), QueryNot(T("b"))))


def test_a_quotation_is_one_term_whatever_it_holds() -> None:
    assert parse_keyword_query('"north west"') == T("north west")
    assert parse_keyword_query('"NOT sure" OR x') == QueryOr((T("NOT sure"), T("x")))
    assert parse_keyword_query('a"b"') == QueryAnd((T("a"), T("b")))


def test_only_upper_case_words_are_operators() -> None:
    assert parse_keyword_query("a and b") == QueryAnd((T("a"), T("and"), T("b")))
    assert parse_keyword_query("Not a") == QueryAnd((T("Not"), T("a")))
    assert parse_keyword_query("not") == T("not")


@pytest.mark.parametrize("text, says", [
    ("", "empty"),
    ("   ", "empty"),
    ('"a', "quotation is not closed"),
    ('""', "quotation is empty"),
    ('"  "', "quotation is empty"),
    ("(a", "bracket is not closed"),
    ("a)", "closing bracket has no opening one"),
    (")", "closing bracket has no opening one"),
    ("()", "brackets holds nothing"),
    ("AND a", "AND needs a term on each side"),
    ("a OR OR b", "OR needs a term on each side"),
    ("a AND", "ends where a term was expected"),
    ("NOT", "ends where a term was expected"),
    (3, "is text"),
])
def test_a_query_that_does_not_parse_says_why(text: object, says: str) -> None:
    with pytest.raises(ValueError, match=says):
        parse_keyword_query(text)


def test_a_query_is_bounded() -> None:
    parse_keyword_query("a " * MAX_QUERY_TERMS)
    with pytest.raises(ValueError, match="at most"):
        parse_keyword_query("a " * (MAX_QUERY_TERMS + 1))
    with pytest.raises(ValueError, match="characters"):
        parse_keyword_query("a" * (MAX_QUERY_LENGTH + 1))
    parse_keyword_query("a" * MAX_QUERY_LENGTH)


def test_a_term_is_a_prefix_of_the_whole_value_ignoring_case() -> None:
    tree = parse_keyword_query("north")
    assert query_matches(tree, "North West")
    assert not query_matches(parse_keyword_query("west"), "North West")
    assert query_matches(parse_keyword_query('"north w" AND NOT "north west x"'), "north west")
    assert query_matches(parse_keyword_query("NOT a"), "b")
    assert not query_matches(parse_keyword_query("a b"), "a")
    assert query_matches(parse_keyword_query("a OR b"), "b")


def test_terms_lists_them_in_order() -> None:
    assert query_terms(parse_keyword_query('x OR NOT (y "z w")')) == ["x", "y", "z w"]


def test_a_filter_carries_the_parsed_tree_and_names_its_property_when_refused() -> None:
    definition = parse({"object_type_id": str(uuid.uuid4()), "filters": [
        {"property": "region", "op": "keyword_query", "value": "a OR b"}]})
    assert definition.filters[0].value == QueryOr((T("a"), T("b")))
    with pytest.raises(ValueError, match="keyword query on 'region': a bracket is not closed"):
        parse({"object_type_id": str(uuid.uuid4()), "filters": [
            {"property": "region", "op": "keyword_query", "value": "(a"}]})
    with pytest.raises(ValueError, match="omit the filter"):
        parse({"object_type_id": str(uuid.uuid4()), "filters": [
            {"property": "region", "op": "keyword_query", "value": None}]})
