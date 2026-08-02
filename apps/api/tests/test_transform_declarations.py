"""Transform declarations (roadmap phase 2, item 2.5; decision 0004).

The proof that matters is the first one: a declaration is read **without
running the file**. Everything else follows from that - the refusals exist
because a value that cannot be read from the source could only be obtained by
executing code, which is the thing decision 0004 exists to gate.

No database. This is a parser.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.transform_declarations import (  # noqa: E402
    DeclarationError,
    read,
    read_repository,
)


# ---- the point of the whole module -------------------------------------------
def test_a_file_that_would_explode_on_import_still_parses() -> None:
    """The load-bearing test. Importing this module to read its decorator would
    delete a directory; reading it with `ast` does not run a line of it."""
    source = """
import shutil
shutil.rmtree("/")          # never executed - this file is only ever parsed
raise SystemExit("boom")

@transform(output="daily_orders", inputs={"orders": "raw_orders"})
def build(orders):
    return orders
"""
    declaration = read("src/build.py", source)
    assert declaration is not None
    assert declaration.output == "daily_orders"
    assert declaration.inputs == {"orders": "raw_orders"}


def test_a_declaration_that_cannot_be_read_is_refused_not_guessed() -> None:
    """A computed output could only be resolved by running the file. A lineage
    graph that is right most of the time is worse than one that says it cannot
    read something, because nobody checks the edges they cannot see."""
    source = """
NAME = "daily_" + "orders"

@transform(output=NAME)
def build():
    ...
"""
    with pytest.raises(DeclarationError, match="computed"):
        read("src/build.py", source)


def test_inputs_assembled_at_runtime_are_refused() -> None:
    source = """
@transform(output="x", inputs=dict(orders="raw_orders"))
def build(orders): ...
"""
    with pytest.raises(DeclarationError, match="dictionary literal"):
        read("src/build.py", source)


# ---- Python ------------------------------------------------------------------
def test_a_decorator_reached_through_a_module_is_the_same_decorator() -> None:
    source = """
import anchor

@anchor.transform(output="daily_orders")
def build(): ...
"""
    declaration = read("src/build.py", source)
    assert declaration is not None and declaration.output == "daily_orders"


def test_a_file_with_no_transform_is_not_an_error() -> None:
    """Repositories hold helpers and fixtures too. Treating every file without
    a declaration as a mistake would make the common case noisy."""
    assert read("src/helpers.py", "def clean(df):\n    return df\n") is None
    assert read("README.md", "# hello") is None


def test_a_transform_without_an_output_says_so() -> None:
    with pytest.raises(DeclarationError, match="needs an `output`"):
        read("src/build.py", "@transform(inputs={'a': 'b'})\ndef build(a): ...\n")


def test_positional_arguments_are_refused() -> None:
    with pytest.raises(DeclarationError, match="keyword arguments only"):
        read("src/build.py", "@transform('daily_orders')\ndef build(): ...\n")


def test_a_file_that_does_not_parse_names_a_line_and_a_reason() -> None:
    """Which line Python blames for a syntax error is Python's business - what
    matters is that the refusal carries one, so the author is not left hunting
    a whole file."""
    with pytest.raises(DeclarationError, match=r"line \d+.*syntax"):
        read("src/build.py", "def build(:\n    (((\n")


# ---- SQL ---------------------------------------------------------------------
def test_sql_declares_the_same_thing_in_the_same_shape() -> None:
    source = """-- output: daily_orders
-- input: orders = raw_orders
-- input: regions = dim_regions
SELECT * FROM orders JOIN regions USING (region)
"""
    declaration = read("src/daily.sql", source)
    assert declaration is not None
    assert declaration.output == "daily_orders"
    assert declaration.inputs == {"orders": "raw_orders", "regions": "dim_regions"}


def test_only_the_leading_comment_block_declares() -> None:
    """A `-- output:` inside a query is somebody explaining a column, not
    declaring a transform."""
    source = """SELECT 1
-- output: not_a_declaration
"""
    assert read("src/q.sql", source) is None


def test_sql_inputs_without_an_output_are_refused() -> None:
    with pytest.raises(DeclarationError, match="no output"):
        read("src/q.sql", "-- input: orders = raw_orders\nSELECT 1\n")


def test_a_plain_sql_file_declares_nothing() -> None:
    assert read("src/scratch.sql", "SELECT 1\n") is None


# ---- a whole snapshot --------------------------------------------------------
def test_a_repository_reads_every_declaring_file() -> None:
    files = {
        "README.md": "# transforms",
        "src/helpers.py": "def clean(df): return df",
        "src/daily.sql": "-- output: daily_orders\n-- input: orders = raw\nSELECT 1",
        "src/weekly.py": "@transform(output='weekly_orders', inputs={'d': 'daily_orders'})\ndef b(d): ...",
    }
    found = read_repository(files)
    assert set(found) == {"src/daily.sql", "src/weekly.py"}
    assert found["src/weekly.py"].inputs == {"d": "daily_orders"}


def test_two_files_claiming_one_output_are_refused() -> None:
    """The pipeline graph would have two producers for one dataset and no way
    to say which run wrote it - a question this platform answers everywhere
    else."""
    files = {
        "a.sql": "-- output: daily_orders\nSELECT 1",
        "b.py": "@transform(output='daily_orders')\ndef build(): ...",
    }
    with pytest.raises(DeclarationError, match="one dataset has one producer"):
        read_repository(files)
