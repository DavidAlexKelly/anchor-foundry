"""What a transform declares, read without running it.

Decided in `docs/decisions/0004-running-customer-code.md`. The short version,
because it is the reason this module exists at all:

Foundry finds a transform's inputs and outputs by evaluating a decorator at
import time. **This platform must not**, because importing a module to read its
decorators *is* executing it - on the API's request path, before any sandbox is
involved, for code whose execution is the very thing decision 0004 gates. So
declarations are parsed from source with `ast`, which evaluates nothing.

Only literals are read. A declaration assembled from a variable or built by
calling a function is **refused** rather than guessed at: a lineage graph that
is right most of the time is worse than one that says it cannot read a file,
because nobody checks the edges they cannot see.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

DECORATOR_NAME = "transform"

# `-- output: daily_orders` / `-- input: orders = raw_orders`, in the leading
# comment block of a SQL file. Same question, same answer shape, so a reader
# does not have to know which language a repository is written in.
_SQL_OUTPUT = re.compile(r"^\s*--\s*output\s*:\s*(?P<name>[A-Za-z0-9_.-]+)\s*$", re.IGNORECASE)
_SQL_INPUT = re.compile(
    r"^\s*--\s*input\s*:\s*(?P<alias>[A-Za-z0-9_]+)\s*=\s*(?P<name>[A-Za-z0-9_.-]+)\s*$",
    re.IGNORECASE,
)


class DeclarationError(ValueError):
    """Refusal, phrased for whoever wrote the file."""


@dataclass(frozen=True)
class Declaration:
    """One transform: what it produces, and what it reads to produce it."""

    output: str
    inputs: dict[str, str] = field(default_factory=dict)
    # Where it was found, so a refusal or a lineage edge can point at a line.
    line: int = 0


def read(path: str, source: str) -> Declaration | None:
    """The declaration in a file, or None if it does not declare one.

    None is not an error. A repository holds helpers, fixtures and READMEs as
    well as transforms, and treating every file without a declaration as a
    mistake would make the common case noisy.
    """
    if path.endswith(".py"):
        return _read_python(source)
    if path.endswith(".sql"):
        return _read_sql(source)
    return None


def _read_python(source: str) -> Declaration | None:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise DeclarationError(
            f"this file does not parse as Python (line {exc.lineno}): {exc.msg}"
        ) from exc

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            if _decorator_name(decorator.func) != DECORATOR_NAME:
                continue
            return _from_call(decorator, node.lineno)
    return None


def _decorator_name(func: ast.expr) -> str | None:
    """`@transform(...)` and `@anchor.transform(...)` are the same decorator.
    Anything else is not this decorator and is left alone."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _from_call(call: ast.Call, line: int) -> Declaration:
    if call.args:
        raise DeclarationError(
            "@transform takes keyword arguments only, so the file says which is "
            "the output and which are the inputs rather than relying on order"
        )
    output: str | None = None
    inputs: dict[str, str] = {}
    for keyword in call.keywords:
        if keyword.arg == "output":
            output = _literal_str(keyword.value, "output")
        elif keyword.arg == "inputs":
            inputs = _literal_mapping(keyword.value)
        elif keyword.arg is None:
            raise DeclarationError(
                "@transform cannot be given **kwargs: the declaration has to be "
                "readable without running the file"
            )
        else:
            raise DeclarationError(
                f"@transform does not take {keyword.arg!r} (it takes `output` and `inputs`)"
            )
    if not output:
        raise DeclarationError("@transform needs an `output` naming the dataset it produces")
    return Declaration(output=output, inputs=inputs, line=line)


def _literal_str(node: ast.expr, what: str) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.strip():
        return node.value.strip()
    raise DeclarationError(
        f"`{what}` has to be a plain string written in the file. This one is computed, "
        "and reading it would mean running the file to find out what it produces."
    )


def _literal_mapping(node: ast.expr) -> dict[str, str]:
    if not isinstance(node, ast.Dict):
        raise DeclarationError(
            "`inputs` has to be a dictionary literal written in the file, so the "
            "lineage can be read without running it"
        )
    inputs: dict[str, str] = {}
    for key, value in zip(node.keys, node.values):
        if key is None:
            raise DeclarationError("`inputs` cannot be built with `**` - it has to be literal")
        alias = _literal_str(key, "an input alias")
        if alias in inputs:
            raise DeclarationError(f"input {alias!r} is declared twice")
        inputs[alias] = _literal_str(value, f"the dataset for input {alias!r}")
    return inputs


def _read_sql(source: str) -> Declaration | None:
    """Read the leading comment block only.

    Stopping at the first non-comment line is deliberate: a `-- output:` inside
    the body of a query is somebody explaining a column, not declaring a
    transform, and a scanner that read the whole file would find both.
    """
    output: str | None = None
    inputs: dict[str, str] = {}
    line_number = 0
    for index, raw in enumerate(source.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        if not line.startswith("--"):
            break
        matched_output = _SQL_OUTPUT.match(line)
        if matched_output:
            if output is not None:
                raise DeclarationError("this file declares more than one output")
            output = matched_output.group("name")
            line_number = index
            continue
        matched_input = _SQL_INPUT.match(line)
        if matched_input:
            alias = matched_input.group("alias")
            if alias in inputs:
                raise DeclarationError(f"input {alias!r} is declared twice")
            inputs[alias] = matched_input.group("name")

    if output is None:
        if inputs:
            raise DeclarationError(
                "this file declares inputs but no output, so nothing knows what it builds"
            )
        return None
    return Declaration(output=output, inputs=inputs, line=line_number)


def read_repository(files: dict[str, str]) -> dict[str, Declaration]:
    """Every declaring file in a snapshot, path → declaration.

    Refuses a snapshot in which two files claim the same output: the pipeline
    graph would have two producers for one dataset and no way to say which run
    wrote it, which is a question this platform answers everywhere else.
    """
    found: dict[str, Declaration] = {}
    producers: dict[str, str] = {}
    for path in sorted(files):
        declaration = read(path, files[path])
        if declaration is None:
            continue
        if declaration.output in producers:
            raise DeclarationError(
                f"{path} and {producers[declaration.output]} both declare the output "
                f"{declaration.output!r} - one dataset has one producer"
            )
        producers[declaration.output] = path
        found[path] = declaration
    return found
