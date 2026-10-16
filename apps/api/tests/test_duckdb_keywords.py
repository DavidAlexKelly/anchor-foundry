"""SQL that names a column DuckDB 1.4 made a keyword says so (§952).

DuckDB 1.1 read `at`, `by`, `lambda` and `unpack` as ordinary column names;
1.4 does not, so a person's saved query, model or function that used one
bare stopped working with the upgrade, and the error named the token after
the word ("syntax error at or near FROM"). The error now names the word and
the fix.
"""
from __future__ import annotations

import os
import sys

import duckdb
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.lib.duck import keyword_hint  # noqa: E402
from src.services import dataset_engine, function_engine  # noqa: E402


@pytest.mark.parametrize("sql, word", [
    ("SELECT at FROM dataset", "at"),
    ("SELECT b FROM t WHERE at > 1", "at"),
    ("SELECT by FROM t", "by"),
    ("SELECT lambda FROM t", "lambda"),
    ("SELECT unpack FROM t", "unpack"),
    ("SELECT AT FROM t", "at"),
    # Still SQL, or quoted, or qualified - DuckDB 1.4 reads all of these.
    ('SELECT "at" FROM dataset', None),
    ("SELECT d.at FROM dataset d", None),
    ("SELECT b FROM t ORDER BY b", None),
    ("SELECT b FROM t GROUP BY b", None),
    ("SELECT count(*) OVER (PARTITION BY b) FROM t", None),
    ("SELECT ts AT TIME ZONE 'UTC' FROM t", None),
    ("SELECT list_transform(l, lambda x: x + 1) FROM t", None),
    ("SELECT unpack(x) FROM t", None),
    ("SELECT b AS at FROM t", None),
    ("SELECT 'at' FROM t", None),
    ("SELECT b FROM t -- at the end", None),
    ("SELECT b /* by */ FROM t", None),
])
def test_the_hint_names_a_bare_word_and_nothing_else(sql, word) -> None:
    hint = keyword_hint(sql)
    if word is None:
        assert hint == ""
    else:
        assert f'"{word}" is a keyword since DuckDB 1.4' in hint


@pytest.fixture
def with_at(tmp_path) -> str:
    path = str(tmp_path / "d.parquet")
    duckdb.sql(f"""COPY (SELECT 1 AS "at", 2 AS b) TO '{path}' (FORMAT parquet)""")
    return path


def test_a_query_says_which_word(with_at) -> None:
    with pytest.raises(dataset_engine.DatasetEngineError,
                       match='"at" is a keyword since DuckDB 1.4.*"at"'):
        dataset_engine.query(with_at, "SELECT at FROM dataset")
    assert dataset_engine.query(with_at, 'SELECT "at" FROM dataset').rows == [[1]]


def test_a_transform_and_its_preview_say_which_word(with_at, tmp_path) -> None:
    for run in (lambda: dataset_engine.run_transform({"t": with_at}, "SELECT at FROM t",
                                                     str(tmp_path / "out.parquet")),
                lambda: dataset_engine.preview_transform({"t": with_at}, "SELECT at FROM t")):
        with pytest.raises(dataset_engine.DatasetEngineError, match='"at" is a keyword'):
            run()


def test_an_error_that_is_not_a_parse_error_gets_no_hint(with_at) -> None:
    # Parsed fine; a column is missing. `at := 1` is a named argument DuckDB
    # 1.4 still reads, and looks bare to the hint, so only the error's kind
    # keeps it from blaming a word that is not the problem.
    sql = "SELECT nope, struct_pack(at := 1) FROM dataset"
    assert keyword_hint(sql)
    with pytest.raises(dataset_engine.DatasetEngineError) as caught:
        dataset_engine.query(with_at, sql)
    assert "keyword" not in str(caught.value)


def test_a_function_is_told_at_publish(with_at) -> None:
    with pytest.raises(function_engine.FunctionError, match='"by" is a keyword'):
        function_engine.check_sql("SELECT by FROM objects", [])


def test_a_function_published_before_the_upgrade_is_told_when_it_runs() -> None:
    """The case the upgrade makes: SQL that passed 1.1's check, run on 1.4."""
    table = function_engine.InputTable(name="objects", columns=[("at", "BIGINT")],
                                       rows=[("i1", "k1", 1)])
    with pytest.raises(function_engine.FunctionError, match='"at" is a keyword'):
        function_engine.run([table], "SELECT at FROM objects", {}, {"kind": "table"})
