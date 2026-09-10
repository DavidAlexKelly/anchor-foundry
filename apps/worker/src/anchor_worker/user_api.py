"""The module customer transform code imports, as a file rather than a fiction.

**Copied out as `anchor.py`** into whatever directory customer code runs in —
`python_sandbox`'s temp dir, and the runner container's work dir. It is a real
module in this package so that our own suite can import it and check what it
does, rather than asserting things about a string.

**Why it had to exist (§292).** `docs/decisions/0004-running-customer-code.md`
documents the declared shape:

    @transform(output="daily_orders", inputs={"orders": "raw_orders"})
    def build(orders):
        return orders

and `python_sandbox.py`'s runner made that work by defining `transform` as a
local in the namespace it `exec`s the file into. That is enough to *run* a
transform and not enough to **import** one — and a unit test's first line is an
import. `from src.daily import build` on a file that says `@transform(...)`
raises `NameError` before any test runs, and `import anchor` raises
`ModuleNotFoundError`, because no such module was on disk anywhere. The
decorator was a convention enforced by one exec namespace, not a contract.

That is §272's finding in its third form: two things that must agree, kept
apart. So there is now one decorator, here, and the runner imports it instead
of defining a second one.

**It records and returns unchanged, and that is the whole implementation.**
Reading a declaration is `transform_declarations.py`'s job, done with `ast` and
evaluating nothing, because importing a module to read its decorators *is*
executing it — decision 0004's central point. Nothing here parses, validates or
resolves anything; if it did, there would again be two answers to "what does
this file declare".
"""
from __future__ import annotations

import os
import shutil
from typing import Any, Callable


class ShapeError(Exception):
    """The file is not a transform this platform can run, and the message says
    which of the several ways that is true."""

#: Every transform the imported files declared, in declaration order. Read by
#: the runner after it has executed the file; a test never looks at it.
declared: list[tuple[Callable[..., Any], dict[str, Any]]] = []


def transform(**kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Mark a function as the transform this file produces.

    **Keyword arguments only**, which is not a style preference: the file has
    to say which name means what rather than relying on order, and the runner
    passes inputs by keyword for the same reason. A transform whose parameters
    were in a different order from its declaration would otherwise silently
    read the wrong dataset.
    """
    def register(fn: Callable[..., Any]) -> Callable[..., Any]:
        declared.append((fn, kwargs))
        return fn

    return register


def resolve_output(namespace: dict[str, Any]) -> Any:
    """Which of the two shapes this file used, and what it produced.

    **One implementation, because there were two and they disagreed (§292).**
    `python_sandbox.py` handled both shapes; `transform_runner.py` — the
    container that runs customer Python *in production* — handled only the
    script, never bound `transform`, and answered a declared transform with
    `NameError: name 'transform' is not defined`. So the shape §272 built ran
    in development and failed in deployment, and no test used a declared
    transform on the container path. That is §272's own finding a second time,
    in the half nobody re-checked: two contracts for one thing, each right
    about itself.

    A module-level `output` wins. Not a precedence puzzle: a file with both is
    a script that also happens to declare, and the script's assignment is the
    thing that ran last. Checking it first also means the old shape reaches its
    result without the decorator machinery being involved at all.
    """
    output = namespace.get("output")
    if output is not None:
        return output
    if len(declared) > 1:
        # The publisher refuses this too (§272), so reaching it means the file
        # changed between publish and run. Refusing rather than picking the
        # first keeps "what was declared" and "what ran" the same sentence.
        raise ShapeError(
            "this file declares more than one transform, so which one produces "
            "the output is ambiguous"
        )
    if not declared:
        raise ShapeError(
            "this file neither set a variable named `output` nor declared a "
            "transform with @transform - assign the table it produces to a "
            "variable of that name, or decorate the function that returns it"
        )

    fn, kwargs = declared[0]
    aliases = dict(kwargs.get("inputs") or {})
    missing = [a for a in aliases if a not in namespace]
    if missing:
        raise ShapeError(
            "this transform declares inputs that were not provided: "
            + ", ".join(sorted(missing))
        )
    try:
        # **By keyword, never by position.** `transform` itself refuses
        # positional arguments so that the file says which name means what
        # rather than relying on order; passing the inputs positionally here
        # would put that back in through the other door, and a transform whose
        # parameters were in a different order would silently read the wrong
        # dataset.
        output = fn(**{a: namespace[a] for a in aliases})
    except TypeError as exc:
        # The common mistake, and a raw TypeError names the function rather
        # than the mismatch: a parameter list that does not match the declared
        # aliases.
        raise ShapeError(
            f"{fn.__name__} does not take the inputs it declares "
            f"({', '.join(sorted(aliases)) or 'none'}): {exc}"
        ) from exc
    if output is None:
        raise ShapeError(
            f"{fn.__name__} returned nothing - a declared transform returns the "
            "table it produces"
        )
    return output


def write_into(directory: str) -> str:
    """Put `anchor.py` beside the code that will import it.

    **Copied, not generated.** This is a real module, so our own suite imports
    and exercises it directly rather than asserting things about a template
    string — and what customer code imports is byte-for-byte what those tests
    ran against.
    """
    source = __file__
    target = os.path.join(directory, "anchor.py")
    shutil.copyfile(source, target)
    return target
