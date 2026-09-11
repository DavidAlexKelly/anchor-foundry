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
    COMMENT_PREFIX,
    DeclarationError,
    InsertRefused,
    UnwritableDeclaration,
    _block_patterns,
    read,
    read_repository,
    render,
    unwritable,
    with_input,
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


# ---- writing one, which is why `render` lives beside `read` (§274) -----------
# The round trip is the whole reason these two functions share a module. §272
# was two things that had to agree kept in different files and each verified
# alone; a writer of this syntax and a reader of it is exactly that shape.
ROUND_TRIPS = [
    ("the plain case", "daily_orders", {"orders": "raw_orders"}),
    ("no inputs at all", "daily_orders", {}),
    ("several inputs", "daily", {"a": "raw_a", "b": "raw_b", "c": "raw_c"}),
    ("dots and hyphens in names", "team.daily-orders", {"o": "raw.orders-v2"}),
    ("digits and underscores", "d2", {"_x9": "_raw9"}),
]


@pytest.mark.parametrize("suffix", sorted(COMMENT_PREFIX))
@pytest.mark.parametrize("label,output,inputs", ROUND_TRIPS,
                         ids=[c[0] for c in ROUND_TRIPS])
def test_a_declaration_survives_being_written_and_read_back(
    suffix: str, label: str, output: str, inputs: dict[str, str]
) -> None:
    """**Exact equality, not "the header survived".**

    Measured before this was written: prepending a header to a model whose own
    code begins with `-- input: x = y` produces a parse that *succeeds* and
    silently gains an input the model never had. A containment check passes
    that; equality does not.

    Run against both languages from one table, so a rule added to one has to be
    answered for the other.
    """
    body = "SELECT 1\n" if suffix == ".sql" else "output = 1\n"
    source = render(output, inputs, prefix=COMMENT_PREFIX[suffix]) + body

    found = read(f"src/thing{suffix}", source)
    assert found is not None, source
    assert (found.output, found.inputs) == (output, inputs), source


# ---- what cannot be written, and why it has to be refused -------------------
# Model and dataset names are constrained only by length (db 0001: 1-200
# characters, any of them), so a name can exist that this syntax cannot write.
# Each case below was measured against the reader first; the comment says what
# the reader actually did with it, because two of them do not fail - they lose
# data and carry on.
UNWRITABLE = [
    # (label, output, inputs, the fragment the refusal must name)
    ("a space in the output name",
     "Daily Totals", {"orders": "raw_orders"}, "Daily Totals"),
    # Measured: parses fine with `inputs={}`. The file would publish as a
    # transform that reads nothing.
    ("a space in an input's dataset name",
     "daily_orders", {"orders": "Raw Orders"}, "Raw Orders"),
    # Measured: the same silent loss.
    ("an alias that is not a usable variable name",
     "daily_orders", {"raw orders": "raw_orders"}, "raw orders"),
    # **The case that separates the two rules.** A *name* may hold dots and
    # hyphens; an alias may not, because it becomes a variable the transform
    # refers to and `raw-orders` is not a name Python can bind. Without this the
    # alias check could be done with the looser name rule and every test still
    # passes — the fixtures above are rejected by both (§212's family: a fixture
    # that never crosses the boundary cannot see it).
    ("a hyphen in an alias, which a dataset name may have",
     "daily_orders", {"raw-orders": "raw-orders"}, "raw-orders"),
    ("a dot in an alias, likewise",
     "daily_orders", {"raw.orders": "raw_orders"}, "raw.orders"),
    ("a slash in the output name",
     "team/daily", {"orders": "raw_orders"}, "team/daily"),
    ("an empty alias, which the schema still permits",
     "daily_orders", {"": "raw_orders"}, "''"),
]


@pytest.mark.parametrize("label,output,inputs,named", UNWRITABLE,
                         ids=[c[0] for c in UNWRITABLE])
def test_a_name_the_syntax_cannot_write_is_refused_and_named(
    label: str, output: str, inputs: dict[str, str], named: str
) -> None:
    """**Refused up front rather than left to the round trip**, because the
    round trip's own message blames the wrong thing.

    Written straight through, a space in the *output* raises "this file
    declares inputs but no output" — which sends the author looking at their
    inputs. A space in an input's *dataset* raises nothing at all. Neither
    message mentions the name that is actually wrong, so the check has to
    happen before the file exists and has to say which value it is about.
    """
    with pytest.raises(UnwritableDeclaration) as caught:
        render(output, inputs, prefix="--")
    assert named in str(caught.value), caught.value


def test_the_silent_cases_really_are_silent_without_the_check() -> None:
    """**The premise of the test above, asserted rather than assumed.**

    A refusal is only worth having if the thing it prevents is bad, and here
    the claim is specifically that these two lose data *quietly*. If the reader
    ever starts raising on them, this test fails and the docstrings above stop
    being true — which is the point, because they would then be describing a
    hazard that no longer exists.
    """
    # Written by hand, bypassing `render`, exactly as a naive adoption would.
    lost = "-- output: daily_orders\n-- input: orders = Raw Orders\nSELECT 1\n"
    found = read("x.sql", lost)
    assert found is not None
    assert found.inputs == {}, "the reader started refusing this; update §274's note"

    lost_alias = "-- output: daily_orders\n-- input: raw orders = raw_orders\nSELECT 1\n"
    found = read("x.sql", lost_alias)
    assert found is not None and found.inputs == {}


def test_every_reason_is_reported_not_just_the_first() -> None:
    """A model with two unwritable names would otherwise be two round trips
    through the same refusal, and the second arrives after the author thinks
    they have finished."""
    problems = unwritable("Daily Totals", {"raw orders": "Raw Orders"})
    assert len(problems) == 3, problems
    joined = " ".join(problems)
    assert "Daily Totals" in joined and "raw orders" in joined and "Raw Orders" in joined


def test_inputs_are_written_in_a_stable_order() -> None:
    """Adopting the same model twice produces the same bytes, so an unchanged
    declaration has an empty diff. Dict order is insertion order in Python, and
    `list_inputs` orders by alias today — a caller that built the mapping some
    other way would otherwise produce a spurious commit."""
    a = render("daily", {"b": "raw_b", "a": "raw_a"}, prefix="--")
    b = render("daily", {"a": "raw_a", "b": "raw_b"}, prefix="--")
    assert a == b
    assert a.index("input: a") < a.index("input: b")


def test_an_unwritable_declaration_is_a_declaration_error() -> None:
    """So a caller that only knows about `DeclarationError` still catches it,
    while one that wants to offer a rename can ask for the subclass. Renaming
    and editing are different fixes and a screen wants to offer different
    things."""
    assert issubclass(UnwritableDeclaration, DeclarationError)


def test_an_alias_is_held_to_a_stricter_rule_than_a_dataset_name() -> None:
    """Stated directly, because the two rules look interchangeable and are not.

    A dataset may legitimately be called `raw-orders`; an *alias* of that name
    would be a module-level variable the transform can never refer to, because
    `raw-orders` is not something Python can bind. So the same string is
    writable in one position and refused in the other, which is the sort of
    asymmetry that gets tidied away by somebody reading only one of them.
    """
    assert unwritable("daily", {"orders": "raw-orders"}) == []
    problems = unwritable("daily", {"raw-orders": "raw_orders"})
    assert len(problems) == 1 and "variable" in problems[0], problems


# --- Inserting a reference (§304) -------------------------------------------
#
# The Explorer's Insert button. These are here rather than in a file of their
# own for the module docstring's reason: `render` lives beside `read` because
# two things that must agree, kept apart, is how §272 broke. A splicer that has
# to produce text `read` accepts is the same hazard one step out, and the tests
# that hold it are the ones that read the result back.


def test_an_inserted_reference_reads_back_as_a_declaration() -> None:
    """**The property, not the bytes.** Anything can append a line that looks
    right; what matters is that the reader agrees, and that is what a copy of
    the syntax living in the browser would eventually stop doing."""
    after = with_input("t.sql", "-- output: daily\nSELECT 1\n",
                       alias="o", dataset="orders")
    declaration = read("t.sql", after)
    assert declaration is not None
    assert declaration.output == "daily"
    assert declaration.inputs == {"o": "orders"}


def test_an_existing_input_is_kept() -> None:
    """Inserting a second reference does not lose the first."""
    after = with_input("t.sql", "-- output: daily\n-- input: b = bees\nSELECT 1\n",
                       alias="o", dataset="orders")
    declaration = read("t.sql", after)
    assert declaration is not None
    assert declaration.inputs == {"b": "bees", "o": "orders"}


def test_the_body_of_the_file_is_untouched() -> None:
    """Only the declaration block moves. A splice that reformatted the query
    would make Insert a thing people stop using.

    **The comment in the body is one that would match**, and it has to be. The
    first version of this test used a note the pattern could not match anyway —
    so removing the splice's stopping rule broke nothing, and a mutation run
    said so. `-- output: total` inside a query is `read`'s own documented case:
    somebody explaining a column, not declaring a transform. The splice stops
    where the reader stops, or Insert silently edits the query.
    """
    body = "SELECT\n  id,\n  -- output: total\n  total\nFROM x\n"
    after = with_input("t.sql", f"-- output: daily\n{body}", alias="o", dataset="orders")
    assert after.endswith(body), after
    # And the file still declares exactly one output, which is what the note
    # inside the query never was.
    declaration = read("t.sql", after)
    assert declaration is not None and declaration.output == "daily"


def test_a_comment_above_the_declaration_stays_above_it() -> None:
    """The block is re-rendered in place, not appended to the end of it."""
    after = with_input(
        "t.sql", "-- What this builds, and why\n-- output: daily\nSELECT 1\n",
        alias="o", dataset="orders",
    )
    assert after.startswith("-- What this builds, and why\n-- output: daily\n")


def test_python_declares_behind_a_hash() -> None:
    """The one asymmetry between the languages, and the whole of it (§273)."""
    after = with_input("t.py", "# output: daily\nprint(1)\n", alias="o", dataset="orders")
    assert "# input: o = orders\n" in after
    declaration = read("t.py", after)
    assert declaration is not None and declaration.inputs == {"o": "orders"}


def test_the_block_comes_back_in_the_order_render_writes() -> None:
    """Re-rendered rather than appended, so an out-of-order block is
    normalised - and an inserted reference and an adopted model produce the
    same bytes, which is what makes a diff of an unchanged declaration empty."""
    after = with_input(
        "t.sql", "-- input: z = zebras\n-- output: daily\nSELECT 1\n",
        alias="a", dataset="apples",
    )
    assert after == (
        "-- output: daily\n-- input: a = apples\n-- input: z = zebras\nSELECT 1\n"
    )


def test_a_file_that_declares_nothing_is_refused_and_says_what_comes_first() -> None:
    """A transform names what it *builds* before it can read anything.

    Refused rather than invented: writing an input with no output produces a
    file the reader refuses as "inputs but no output", so guessing an output
    here would be this module handing itself a problem two lines later.
    """
    with pytest.raises(InsertRefused) as raised:
        with_input("t.sql", "SELECT 1\n", alias="o", dataset="orders")
    assert "output" in str(raised.value)


def test_the_decorator_form_is_refused_and_the_message_says_what_to_do() -> None:
    """**A boundary, not a missing case.** A `@transform(...)` call's inputs
    are code; rewriting them means printing an AST back over a file somebody
    wrote. A comment line can be inserted without touching anything else."""
    source = (
        "from transforms import transform\n\n"
        "@transform(output='daily')\n"
        "def build():\n    pass\n"
    )
    with pytest.raises(InsertRefused) as raised:
        with_input("t.py", source, alias="o", dataset="orders")
    said = str(raised.value)
    assert "decorator" in said
    # And it names both halves of what to type, because the remedy is manual.
    assert "orders" in said and "o " in said


def test_the_word_transform_in_a_string_is_not_a_decorator() -> None:
    """Parsed rather than searched for.

    A script that *mentions* `@transform` - in a docstring, in a comment, in a
    string it prints - declares behind a `#` like any other script, and a
    search for the word would refuse it with a message about a decorator it
    does not have.

    The declaration is the file's first line, which is `read`'s existing rule
    rather than anything this test chose: `_read_comment_block` reads the
    *leading* block only, so a docstring above it ends the block before it
    starts. The first draft of this test put the docstring first and was
    refused for having no declaration at all - a wrong premise, not a bug.
    """
    source = (
        "# output: daily\n"
        '"""Uses @transform elsewhere."""\n'
        "# @transform is also mentioned here\n"
        "print(1)\n"
    )
    after = with_input(source=source, path="t.py", alias="o", dataset="orders")
    assert "# input: o = orders\n" in after
    declaration = read("t.py", after)
    assert declaration is not None and declaration.inputs == {"o": "orders"}


def test_a_file_that_is_neither_sql_nor_python_is_refused() -> None:
    with pytest.raises(InsertRefused) as raised:
        with_input("notes.md", "# output: daily\n", alias="o", dataset="orders")
    assert ".sql" in str(raised.value)


def test_the_same_alias_twice_is_refused_and_names_what_it_already_reads() -> None:
    """The reader raises "input 'o' is declared twice", so producing one would
    be writing a file this platform refuses. The refusal is more useful here,
    where the dataset it already points at is the reader's next question."""
    with pytest.raises(InsertRefused) as raised:
        with_input("t.sql", "-- output: daily\n-- input: o = bees\nSELECT 1\n",
                   alias="o", dataset="orders")
    assert "bees" in str(raised.value)


def test_the_same_dataset_under_a_second_alias_is_refused() -> None:
    """Two aliases for one dataset is legal and almost always Insert clicked
    twice. The refusal names the alias that exists, so the fix is to use it."""
    with pytest.raises(InsertRefused) as raised:
        with_input("t.sql", "-- output: daily\n-- input: existing = orders\nSELECT 1\n",
                   alias="another", dataset="orders")
    assert "existing" in str(raised.value)


def test_an_unwritable_name_is_refused_by_the_writer_that_already_refuses_it() -> None:
    """Not a second validation. `render` refuses a dataset name holding a
    space because - measured against the reader - such a file parses
    successfully *with no inputs at all*, and would publish as a transform that
    reads nothing."""
    with pytest.raises(UnwritableDeclaration):
        with_input("t.sql", "-- output: daily\nSELECT 1\n",
                   alias="o", dataset="raw orders")


def test_a_file_that_does_not_parse_as_python_reports_the_line() -> None:
    """The refusal comes from `read`, which names the line, rather than from
    the decorator check quietly deciding there is no decorator."""
    with pytest.raises(DeclarationError) as raised:
        with_input("t.py", "# output: daily\ndef (\n", alias="o", dataset="orders")
    assert "line" in str(raised.value)
