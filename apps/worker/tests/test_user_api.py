"""The module customer transform code imports (§292).

**Why this file exists rather than more runner tests.** `anchor.py` is copied
verbatim into every directory customer code runs in, and its rules were
previously written out twice — once as a string inside `python_sandbox.py`'s
runner template, once (differently, and incompletely) in `transform_runner.py`.
Testing a template string means testing a copy; testing this module means
testing the bytes that ship.

The two shapes it decides between are `python_sandbox.py`'s docstring's
subject: the *declared* transform decision 0004 documents, and the *script*
every model authored in the Models editor before repositories existed is
written in.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from anchor_worker import user_api  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_registry():
    """A run is a fresh process, so the registry starts empty every time.

    Asserted here rather than assumed: these tests share one process, and a
    registry that leaked between them would make the second declaration in the
    file look ambiguous — which is exactly the bug `_load_anchor` avoids by
    loading a new module object per run.
    """
    user_api.declared.clear()
    yield
    user_api.declared.clear()


def test_the_decorator_returns_the_function_unchanged() -> None:
    """It records and returns, and that is the whole implementation. Reading a
    declaration is `transform_declarations.py`'s job, done with `ast` and
    evaluating nothing, because importing a module to read its decorators *is*
    executing it — decision 0004's central point."""
    @user_api.transform(output="daily", inputs={"orders": "raw"})
    def build(orders):
        return orders

    assert build("rows") == "rows"
    assert user_api.declared == [(build, {"output": "daily", "inputs": {"orders": "raw"}})]


def test_a_script_wins_over_a_declaration() -> None:
    """Not a precedence puzzle: a file with both is a script that also happens
    to declare, and the script's assignment is the thing that ran last."""
    @user_api.transform(output="daily", inputs={})
    def build():
        return "from the function"

    assert user_api.resolve_output({"output": "from the script"}) == "from the script"


def test_a_declared_transform_is_called_with_its_inputs_by_keyword() -> None:
    """**By keyword, never by position.** A transform whose parameters were in
    a different order from its declaration would otherwise silently read the
    wrong dataset."""
    seen = {}

    @user_api.transform(output="daily", inputs={"left": "a", "right": "b"})
    def build(right, left):  # deliberately the other order
        seen.update({"left": left, "right": right})
        return "built"

    got = user_api.resolve_output({"left": "L", "right": "R", "output": None})
    assert got == "built"
    assert seen == {"left": "L", "right": "R"}


def test_two_declarations_are_refused_rather_than_the_first_one_picked() -> None:
    """The publisher refuses this too, so reaching it means the file changed
    between publish and run. Refusing keeps "what was declared" and "what ran"
    the same sentence."""
    @user_api.transform(output="one", inputs={})
    def a():
        return 1

    @user_api.transform(output="two", inputs={})
    def b():
        return 2

    with pytest.raises(user_api.ShapeError, match="more than one transform"):
        user_api.resolve_output({})


def test_a_file_that_is_neither_shape_is_told_both_ways_out() -> None:
    with pytest.raises(user_api.ShapeError) as caught:
        user_api.resolve_output({"answer": 42})
    assert "assign the table it produces" in str(caught.value)
    assert "decorate the function that returns it" in str(caught.value)


def test_an_input_that_was_not_provided_is_named() -> None:
    @user_api.transform(output="daily", inputs={"orders": "raw", "refs": "other"})
    def build(orders, refs):
        return orders

    with pytest.raises(user_api.ShapeError, match="orders, refs"):
        user_api.resolve_output({})


def test_a_parameter_list_that_does_not_match_names_the_mismatch() -> None:
    """A raw TypeError names the function rather than the mismatch, which is
    the wrong half of the sentence for whoever has to fix it."""
    @user_api.transform(output="daily", inputs={"orders": "raw"})
    def build():  # takes nothing, declares one
        return "x"

    with pytest.raises(user_api.ShapeError) as caught:
        user_api.resolve_output({"orders": "rows"})
    assert "does not take the inputs it declares (orders)" in str(caught.value)


def test_a_transform_that_returns_nothing_is_told_so() -> None:
    @user_api.transform(output="daily", inputs={})
    def build():
        return None

    with pytest.raises(user_api.ShapeError, match="returned nothing"):
        user_api.resolve_output({})


def test_the_copy_is_byte_for_byte_this_file(tmp_path) -> None:
    """**Copied, not generated**, and this is the property that makes the tests
    above worth anything: what customer code imports is the module they ran
    against, not a template that resembles it."""
    written = user_api.write_into(str(tmp_path))
    assert os.path.basename(written) == "anchor.py"
    assert open(written, "rb").read() == open(user_api.__file__, "rb").read()
