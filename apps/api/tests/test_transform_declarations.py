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
    _block_patterns,
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


# ---- one file, one transform (§272) -----------------------------------------
# This module's docstring says both languages answer "the same question" in
# "the same answer shape, so a reader does not have to know which language a
# repository is written in". That was true of the syntax and false of the
# answer: SQL refused a second `-- output:` and Python returned the first of
# two `@transform` functions, silently. Written as a pair on purpose - a rule
# stated once per language is a rule that can hold in one of them.
def test_sql_refuses_a_file_that_declares_two_outputs() -> None:
    with pytest.raises(DeclarationError, match="more than one output"):
        read("x.sql", "-- output: a\n-- output: b\nSELECT 1")


def test_python_refuses_a_file_that_declares_two_transforms() -> None:
    """**The second one is invisible, which is what makes this worth a
    refusal rather than a preference.** A dropped declaration is not built,
    not scheduled and not in the lineage graph, and its author's only clue is
    a dataset that stops changing - so the failure is silent at every layer
    that could have reported it.
    """
    source = (
        "@transform(output='a')\ndef one(): ...\n\n"
        "@transform(output='b')\ndef two(): ...\n"
    )
    with pytest.raises(DeclarationError, match="more than one transform"):
        read("x.py", source)


def test_the_refusal_names_both_functions() -> None:
    """The fix is to split the file, so the message has to say which two
    things to split. A refusal naming only the count leaves the author reading
    the whole file to find the pair."""
    source = (
        "@transform(output='a')\ndef daily(): ...\n\n"
        "@transform(output='b')\ndef weekly(): ...\n"
    )
    with pytest.raises(DeclarationError) as caught:
        read("x.py", source)
    assert "daily" in str(caught.value) and "weekly" in str(caught.value)


def test_one_decorated_function_beside_undecorated_ones_is_not_two() -> None:
    """A repository holds helpers, and the rule is about *declarations* rather
    than about how many functions a file has. A version of this check that
    counted functions would refuse every transform with a helper beside it -
    which is most of them."""
    source = (
        "def clean(df): return df\n\n"
        "@transform(output='daily', inputs={'t': 'raw'})\n"
        "def build(t): return clean(t)\n\n"
        "def unused(): ...\n"
    )
    found = read("x.py", source)
    assert found is not None and found.output == "daily"


def test_a_function_carrying_the_decorator_twice_is_one_transform() -> None:
    """Stacked decorators on **one** function are one declaration, however
    odd. The count that matters is functions that declare, not decorators
    seen - a loop that counted the inner one twice would refuse a file with
    one transform in it."""
    source = (
        "@transform(output='a')\n@transform(output='a')\ndef build(): ...\n"
    )
    found = read("x.py", source)
    assert found is not None and found.output == "a"


# ---- a script declares in a comment, like SQL always has (§273) --------------
# decision 0017. The only Python declaration form was a decorated function, and
# a *script* - inputs as module-level names, the result assigned to `output`,
# which is every model authored before repositories existed (§272) - has no
# function to decorate. So those models could not live in a repository at all,
# which is the blocker B.1 exists to clear.
SCRIPT = "# output: daily_orders\n# input: orders = raw_orders\n\noutput = orders\n"


def test_a_script_declares_in_a_leading_comment() -> None:
    found = read("src/daily.py", SCRIPT)
    assert found is not None
    assert found.output == "daily_orders"
    assert found.inputs == {"orders": "raw_orders"}


def test_the_two_languages_answer_identically_apart_from_the_prefix() -> None:
    """**The property being bought, asserted directly.**

    This module's docstring says both languages answer "the same question" in
    "the same answer shape, so a reader does not have to know which language a
    repository is written in". §272 found that claim already false in the other
    reader, so it is worth a test that fails when the two drift rather than a
    sentence that goes on being read.

    The bodies differ because one is SQL and one is Python; the *declarations*
    are the same text with one prefix swapped.
    """
    sql = read("t.sql", "-- output: daily_orders\n-- input: orders = raw_orders\nSELECT 1")
    py = read("t.py", SCRIPT)
    assert sql is not None and py is not None
    assert (sql.output, sql.inputs) == (py.output, py.inputs)


def test_a_file_declaring_both_ways_is_refused_naming_both_forms() -> None:
    """"One file, one transform" has to hold *between* the forms as well as
    within each, or the rule is two rules that happen to agree. And the message
    names the forms rather than the lines: the fix is to delete one of them, so
    what the author needs to know is which two things are competing."""
    source = (
        "# output: daily_orders\n"
        "@transform(output='daily_orders')\n"
        "def build_the_daily_totals(): ...\n"
    )
    with pytest.raises(DeclarationError) as caught:
        read("x.py", source)
    message = str(caught.value)
    assert "@transform" in message and "comment" in message
    # **And which function carries the decorator.** The fix is to delete one of
    # the two declarations, so a message naming only the forms leaves the author
    # scrolling a file to find the decorated one. The function is deliberately
    # not called `build` here: a name that short would appear in this assertion
    # by accident out of almost any message.
    assert "build_the_daily_totals" in message, message


def test_a_stray_input_comment_beside_a_decorator_is_just_a_comment() -> None:
    """The "inputs but no output" refusal exists for SQL, where a mistyped
    output line leaves a file that silently builds nothing and there is no other
    way to declare. Python has another way, so raising here would answer a
    question the author did not ask, about a file that declares correctly."""
    source = (
        "# input: orders = raw_orders\n"
        "@transform(output='daily_orders', inputs={'orders': 'raw_orders'})\n"
        "def build(orders): ...\n"
    )
    found = read("x.py", source)
    assert found is not None and found.output == "daily_orders"


def test_a_script_with_inputs_and_no_output_is_still_refused() -> None:
    """With no decorator there is no other way to have declared, so this is the
    typo it looks like - the same answer SQL gives."""
    with pytest.raises(DeclarationError, match="inputs but no output"):
        read("x.py", "# input: orders = raw_orders\noutput = orders\n")


def test_an_output_comment_after_the_first_statement_is_not_a_declaration() -> None:
    """The leading block only, as with SQL: a `# output:` further down is
    somebody explaining a variable, and a scanner that read the whole file
    would find both."""
    assert read("x.py", "output = orders\n# output: sneaky\n") is None


def test_a_shebang_does_not_stop_the_block() -> None:
    """`#!/usr/bin/env python` is a comment, so it neither declares anything nor
    ends the leading block - a file that lost its declaration to a shebang would
    be a rule about line one masquerading as a rule about comments."""
    found = read("x.py", "#!/usr/bin/env python\n# output: daily_orders\noutput = 1\n")
    assert found is not None and found.output == "daily_orders"


def test_a_docstring_ends_the_block_and_that_is_the_sql_rule_too() -> None:
    """A module docstring is a statement, not a comment, so it closes the
    leading block exactly as the first `SELECT` does. Worth a test because it is
    the surprising half of "leading comment block": the rule is about comments
    and not about "before the code starts"."""
    assert read("x.py", '"""Daily totals."""\n# output: daily_orders\noutput = 1\n') is None


def test_a_helper_with_no_declaration_is_still_not_an_error() -> None:
    """The common case, and the reason `read` returns None rather than raising:
    a repository holds helpers, fixtures and READMEs. Re-asserted here because
    §273 added a second way for a `.py` file to declare, and a new branch that
    treated "no comment header" as a refusal would make every helper a failure.
    """
    assert read("src/helpers.py", "def clean(df):\n    return df\n") is None


def test_a_comment_prefix_is_matched_literally_and_not_as_a_pattern() -> None:
    """**§265's move: build the divergence the guard defends against.**

    `_block_patterns` escapes its prefix, and against the two prefixes that
    exist — `--` and `#` — that call does nothing, because neither holds a
    regex metacharacter. So a mutant removing the escape survives every test
    that goes through `read`, and §264's rule would say to delete a line that
    cannot fail.

    It can fail. `COMMENT_PREFIX` is a table meant to gain a row when a third
    language arrives, and a prefix like `/*` contains one. Unescaped, `/*`
    means "zero or more slashes", so the pattern would match a line with **no
    prefix at all** — every `output:` comment anywhere in a leading block, in a
    language that had not opted in. That is constructible by hand today, so it
    is tested rather than deleted or excused.

    Tests the private factory deliberately: the hazard is in the pattern, and
    routing through `read` would need a fourth language to exist first.
    """
    pattern_output, pattern_input = _block_patterns("/*")

    assert pattern_output.match("/* output: daily_orders")
    assert pattern_input.match("/* input: orders = raw_orders")

    # The line the unescaped version would wrongly accept: no prefix at all,
    # because `/*` would have meant "zero or more slashes".
    assert pattern_output.match(" output: daily_orders") is None
    assert pattern_input.match(" input: orders = raw_orders") is None
