"""The SQL Scratchpad's reference syntax (§305; p.15).

    "To access a specific branch of an input dataset in SQL Scratchpad, you
     prepend the name of the branch to the query: e.g. ``SELECT * FROM
     `branch_A`.`/path/to/dataset` ``. If no branch is specified it will
     default to master." (p.15)

No database. This is a parser and a rewriter, and the reason it is a *rewriter*
is that Foundry runs Spark, where a backtick quotes an identifier, and DuckDB
has no backtick syntax at all — it fails at the parser. Supporting p.15's
sentence means translating it.
"""
from __future__ import annotations

import os
import sys

import duckdb
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.scratchpad import (  # noqa: E402
    Reference,
    ScratchpadError,
    bind,
    references,
    unresolved,
)


# --- Reading the references -------------------------------------------------


def test_p15s_own_example_is_read_as_a_branch_and_a_path() -> None:
    """The sentence this module exists for, parsed exactly as written."""
    found = references("SELECT * FROM `branch_A`.`/path/to/dataset`")
    assert found == [Reference(qualifier="branch_A", path="/path/to/dataset")]


def test_an_unqualified_reference_is_the_common_case() -> None:
    assert references("SELECT * FROM `orders`") == [
        Reference(qualifier=None, path="orders")
    ]


def test_a_path_resolves_to_its_last_segment() -> None:
    """Projects here are flat, so a path is a way of *writing* a name.

    Reading `/path/to/dataset` as a literal name and then failing to find one
    would refuse a query written exactly as the documentation shows it.
    """
    assert Reference(None, "/path/to/dataset").name == "dataset"
    assert Reference(None, "orders").name == "orders"
    assert Reference(None, "/orders/").name == "orders"


def test_every_reference_is_found_not_only_the_first() -> None:
    found = references("SELECT * FROM `a` JOIN `b` ON a.id = b.id")
    assert [r.path for r in found] == ["a", "b"]


def test_a_dataset_named_twice_stays_named_twice() -> None:
    """A self-join names one dataset twice. Collapsing here would hide a query
    reading the same thing under two qualifiers."""
    found = references("SELECT * FROM `a` x JOIN `a` y ON x.id = y.id")
    assert len(found) == 2


def test_a_query_with_no_references_is_not_an_error() -> None:
    assert references("SELECT 1") == []


# --- Backticks that are text, not syntax ------------------------------------


def test_a_backtick_inside_a_string_literal_is_not_a_reference() -> None:
    """The bug that shows up as a wrong answer rather than an error.

    `SELECT '`/orders`'` is a query *about a string*; rewriting inside it
    changes what the query returns.
    """
    assert references("SELECT '`/orders`' AS note") == []


def test_a_doubled_quote_inside_a_literal_does_not_end_it() -> None:
    """`''` is an escaped quote. A scanner that ended the literal there would
    treat the rest of the string as SQL."""
    assert references("SELECT 'it''s `/orders` really' AS note") == []


def test_a_backtick_in_a_line_comment_is_not_a_reference() -> None:
    assert references("-- read `/orders` next\nSELECT 1") == []


def test_a_backtick_in_a_block_comment_is_not_a_reference() -> None:
    assert references("/* read `/orders` */ SELECT 1") == []


def test_a_reference_after_a_comment_is_still_found() -> None:
    """The skipping is by span, not a switch that stays on."""
    found = references("-- a note\nSELECT * FROM `orders`")
    assert [r.path for r in found] == ["orders"]


def test_a_reference_after_a_string_is_still_found() -> None:
    found = references("SELECT 'hello' AS greeting, * FROM `orders`")
    assert [r.path for r in found] == ["orders"]


# --- Rewriting for the engine -----------------------------------------------


def test_a_reference_becomes_a_double_quoted_identifier() -> None:
    """Foundry runs Spark; we run DuckDB, which has no backtick syntax."""
    rewritten, found = bind("SELECT * FROM `/path/to/orders`")
    assert rewritten == 'SELECT * FROM "orders"'
    assert [r.name for r in found] == ["orders"]


def test_the_rewritten_query_is_one_duckdb_can_actually_parse() -> None:
    """**The property, not the string.** The whole reason this module rewrites
    at all is that the engine rejects the original, so the test that matters is
    the engine accepting the result."""
    connection = duckdb.connect()
    connection.execute('CREATE TABLE "orders" AS SELECT 1 AS id')
    rewritten, _ = bind("SELECT * FROM `/path/to/orders`")
    assert connection.execute(rewritten).fetchall() == [(1,)]


def test_the_original_query_is_one_duckdb_cannot_parse() -> None:
    """The other half, and it is what makes the test above mean something: if
    DuckDB ever grew backticks, the rewrite would be unnecessary rather than
    wrong, and this is what would say so."""
    connection = duckdb.connect()
    connection.execute('CREATE TABLE "orders" AS SELECT 1 AS id')
    with pytest.raises(duckdb.Error):
        connection.execute("SELECT * FROM `/path/to/orders`")


def test_a_string_literal_survives_the_rewrite_untouched() -> None:
    rewritten, _ = bind("SELECT '`/orders`' AS note FROM `orders`")
    assert rewritten == "SELECT '`/orders`' AS note FROM \"orders\""


def test_a_query_with_nothing_to_rewrite_comes_back_unchanged() -> None:
    assert bind("SELECT 1")[0] == "SELECT 1"


# --- The refusals -----------------------------------------------------------


def test_a_branch_qualifier_is_refused_and_names_the_model_difference() -> None:
    """**Refused rather than ignored**, and that is the decision.

    Ignoring the qualifier returns a table, so nobody checks it — it answers a
    question nobody asked. Datasets here are versioned, not branched (db 0025),
    and Global Branching is out of scope in `docs/parity/README.md`.
    """
    with pytest.raises(ScratchpadError) as raised:
        bind("SELECT * FROM `branch_A`.`/path/to/dataset`")
    said = str(raised.value)
    assert "branch_A" in said
    assert "versioned" in said
    # And it says what to do instead, rather than only saying no.
    assert "fork" in said or "directly" in said


def test_the_refusal_survives_a_qualifier_on_the_second_reference() -> None:
    """Every reference is checked, not the first one."""
    with pytest.raises(ScratchpadError) as raised:
        bind("SELECT * FROM `orders` JOIN `branch_B`.`items` ON true")
    assert "branch_B" in str(raised.value)


def test_an_unterminated_backtick_is_refused_with_a_useful_message() -> None:
    """DuckDB's own message for a stray backtick is `syntax error at or near
    "`"`, which is true and tells somebody who wrote p.15's syntax nothing."""
    with pytest.raises(ScratchpadError) as raised:
        bind("SELECT * FROM `orders")
    said = str(raised.value)
    assert "closing" in said
    # It shows the shape rather than describing it.
    assert "`/path/to/dataset`" in said


def test_a_backtick_inside_a_literal_does_not_count_as_unterminated() -> None:
    """One backtick in a string is text. Refusing it would refuse a valid
    query about a string."""
    assert bind("SELECT '`' AS tick")[0] == "SELECT '`' AS tick"


# --- What the project does not have -----------------------------------------


def test_missing_datasets_are_all_named_at_once() -> None:
    """Every one, not the first: the second refusal otherwise arrives after
    the author thinks they have finished."""
    found = references("SELECT * FROM `a` JOIN `b` JOIN `c`")
    assert unresolved(found, {"b"}) == ["a", "c"]


def test_nothing_missing_is_an_empty_list() -> None:
    found = references("SELECT * FROM `a`")
    assert unresolved(found, {"a", "b"}) == []


def test_a_dataset_named_twice_is_reported_once() -> None:
    found = references("SELECT * FROM `a` x JOIN `a` y ON true")
    assert unresolved(found, set()) == ["a"]


def test_a_path_is_looked_up_by_its_name() -> None:
    """The half that would silently never match: p.15 writes paths, and the
    registry holds names."""
    found = references("SELECT * FROM `/path/to/orders`")
    assert unresolved(found, {"orders"}) == []
