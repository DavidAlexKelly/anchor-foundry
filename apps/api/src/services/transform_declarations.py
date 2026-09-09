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

**`render` lives here too, beside `read`, and that placement is the point**
(§274). It is the inverse function - the writer of the syntax this module
reads - and §272 was exactly two things that had to agree being kept in
different files and each verified alone. A writer over there and a reader over
here is that shape, and it drifts the first time either changes. Same module,
and `test_a_declaration_survives_being_written_and_read_back` is the property
that holds them together rather than a promise that they match.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

DECORATOR_NAME = "transform"

# `-- output: daily_orders` / `-- input: orders = raw_orders`, in the leading
# comment block of a SQL file. Same question, same answer shape, so a reader
# does not have to know which language a repository is written in.
#
# **And in a Python file too, with `#`** (§273, decision 0017). The only Python
# declaration form was a decorated function, which a *script* has nowhere to
# put - and every model authored in the Models editor before repositories
# existed is a script (§272). So those models could not live in a repository at
# all, which is the blocker B.1 exists to clear. Built from one pattern with the
# prefix parameterised rather than as a second pair, because the sentence above
# is the property being bought and two hand-written copies is how it stops being
# true.
def _block_patterns(prefix: str) -> tuple[re.Pattern[str], re.Pattern[str]]:
    p = re.escape(prefix)
    return (
        re.compile(rf"^\s*{p}\s*output\s*:\s*(?P<name>[A-Za-z0-9_.-]+)\s*$", re.IGNORECASE),
        re.compile(
            rf"^\s*{p}\s*input\s*:\s*(?P<alias>[A-Za-z0-9_]+)\s*=\s*(?P<name>[A-Za-z0-9_.-]+)\s*$",
            re.IGNORECASE,
        ),
    )


#: The comment prefix each language declares behind. The one asymmetry between
#: them, and the whole of it.
COMMENT_PREFIX = {".sql": "--", ".py": "#"}


class DeclarationError(ValueError):
    """Refusal, phrased for whoever wrote the file."""


@dataclass(frozen=True)
class Declaration:
    """One transform: what it produces, and what it reads to produce it."""

    output: str
    inputs: dict[str, str] = field(default_factory=dict)
    # Where it was found, so a refusal or a lineage edge can point at a line.
    line: int = 0


# What a declaration can *say*, as opposed to what a name may *be*. Model and
# dataset names are constrained only by length (db 0001: 1-200 characters, any
# of them), so a name can exist that this syntax cannot write down (§274).
#
# **The two are not the same rule, and conflating them loses data silently.**
# A name accepts dots and hyphens; an alias does not, because an alias becomes
# a *module-level variable name* in the Python sandbox - `_namespace[alias] =
# <DataFrame>` - so it has to be something a file can refer to. Measured
# against the reader: an input whose dataset name holds a space does not fail,
# it *vanishes*, and the file publishes as a transform that reads nothing.
_WRITABLE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
_WRITABLE_ALIAS = re.compile(r"^[A-Za-z0-9_]+$")


def unwritable(output: str, inputs: dict[str, str]) -> list[str]:
    """Why these names cannot be declared — the output first, then the inputs
    by alias — or an empty list.

    Separate from `render` so a caller can ask before it acts - the adoption
    screen wants to say "this model cannot move yet, and here is why" without
    writing a file first.

    **Every reason, not the first one.** A model with two unwritable names
    would otherwise be two round trips through the same refusal, and the second
    one arrives after the author thinks they have finished.
    """
    problems: list[str] = []
    if not _WRITABLE_NAME.match(output):
        problems.append(
            f"the name {output!r} cannot be written in a declaration - it may "
            "hold letters, digits, and _ . - only"
        )
    for alias, dataset in sorted(inputs.items()):
        if not _WRITABLE_ALIAS.match(alias):
            problems.append(
                f"the input alias {alias!r} is not a usable name - an alias "
                "becomes a variable the transform refers to, so it may hold "
                "letters, digits and _ only"
            )
        if not _WRITABLE_NAME.match(dataset):
            problems.append(
                f"the dataset {dataset!r} cannot be written in a declaration - "
                "it may hold letters, digits, and _ . - only"
            )
    return problems


class UnwritableDeclaration(DeclarationError):
    """A declaration that cannot be written, with each reason kept separately.

    A subclass so a caller can tell "these names do not fit the syntax" from
    "this file says something contradictory" - the first is fixed by renaming
    and the second by editing, and a screen wants to offer different things.
    """

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def render(output: str, inputs: dict[str, str], *, prefix: str) -> str:
    """The declaration block for these names — the inverse of `read`.

    Refuses rather than writing something the reader would misread. That is not
    caution: measured against the reader, an input whose dataset name holds a
    space **parses successfully with no inputs at all**, so the file would
    publish as a transform that reads nothing and fail much later as a run
    against missing inputs, or simply produce a wrong answer.

    Inputs are written in sorted order so that adopting the same model twice
    produces the same bytes, and a diff of an unchanged declaration is empty.
    """
    problems = unwritable(output, inputs)
    if problems:
        raise UnwritableDeclaration(problems)
    lines = [f"{prefix} output: {output}"]
    lines += [f"{prefix} input: {alias} = {inputs[alias]}" for alias in sorted(inputs)]
    return "\n".join(lines) + "\n"


def read(path: str, source: str) -> Declaration | None:
    """The declaration in a file, or None if it does not declare one.

    None is not an error. A repository holds helpers, fixtures and READMEs as
    well as transforms, and treating every file without a declaration as a
    mistake would make the common case noisy.
    """
    if path.endswith(".py"):
        return _read_python(source)
    if path.endswith(".sql"):
        return _read_comment_block(source, COMMENT_PREFIX[".sql"])
    return None


def _read_python(source: str) -> Declaration | None:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise DeclarationError(
            f"this file does not parse as Python (line {exc.lineno}): {exc.msg}"
        ) from exc

    # **Every decorated function, not the first one** (§272). `_read_sql`
    # refuses a file with two `-- output:` lines, and this returned the first
    # of two `@transform` functions and dropped the second silently - so the
    # module docstring's "same question, same answer shape, so a reader does
    # not have to know which language a repository is written in" was true of
    # the syntax and false of the answer. It matters more than a tidiness
    # point: the second transform is invisible to the publisher, so it is
    # never built, never scheduled, and its author has no way to find out
    # except by noticing the dataset is stale.
    found: list[tuple[str, Declaration]] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            if _decorator_name(decorator.func) != DECORATOR_NAME:
                continue
            found.append((node.name, _from_call(decorator, node.lineno)))
            break
    if len(found) > 1:
        # **A divergence from Foundry, and deliberate.** A Foundry repository
        # file may hold several transforms - `code-repositories` p.39 shows a
        # generator producing three from a loop. Here identity is
        # `(repository, path)`, which is db 0038's unique index and the thing
        # that makes a renamed file publish to the same model rather than a
        # second one; one path cannot name two models. So the gap is in the
        # identity rather than in this reader, and closing it means identity
        # becomes `(repository, path, output)` - a schema change touching every
        # published model, worth doing when somebody wants a file of small
        # related transforms and not before.
        #
        # What this replaced matched neither model: returning the first of two
        # is not one-per-file *or* many-per-file, it is one-per-file with the
        # error left out.
        #
        # Named, both of them, because the fix is to split the file and the
        # author needs to know which two things to split.
        names = ", ".join(name for name, _ in found)
        raise DeclarationError(
            f"this file declares more than one transform ({names}) - one file "
            "produces one dataset, so put each in its own"
        )

    # **The other form a Python file may declare in** (§273, decision 0017):
    # a leading `# output:` block, the same shape SQL has always used. A
    # *script* - inputs as module-level names, the result assigned to `output`,
    # which is every model authored before repositories existed - has no
    # function to decorate, so without this it cannot live in a repository at
    # all. Read after the decorator so a file with neither costs one `ast` walk
    # and no regex work.
    #
    # **Leniently when a decorator already declared.** The "inputs but no
    # output" refusal below exists for SQL, where a mistyped output line leaves
    # a file that silently builds nothing and there is no other way to declare.
    # Python has another way, so beside a decorator a stray `# input:` line is
    # a comment, not a broken declaration - raising there would answer a
    # question the author did not ask, about a file that declares correctly.
    block = _read_comment_block(
        source, COMMENT_PREFIX[".py"], orphan_inputs_are_an_error=not found
    )
    if block is not None and found:
        # Same rule as two decorators, and it has to be, or "one file, one
        # transform" would hold within each form and not between them. Named
        # by *form* rather than by line, because the fix is to delete one of
        # them and the author needs to know which two things are competing.
        raise DeclarationError(
            f"this file declares a transform twice - once with @transform "
            f"({found[0][0]}) and once in a leading {COMMENT_PREFIX['.py']} "
            "output: comment. Keep whichever one describes what actually runs"
        )
    if block is not None:
        return block
    return found[0][1] if found else None


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


def _read_comment_block(
    source: str, prefix: str, *, orphan_inputs_are_an_error: bool = True
) -> Declaration | None:
    """Read the leading comment block only.

    Stopping at the first non-comment line is deliberate: a `-- output:` inside
    the body of a query is somebody explaining a column, not declaring a
    transform, and a scanner that read the whole file would find both.

    **One function for both languages** (§273). The prefix is the only thing
    that differs, and a second hand-written copy for Python is exactly how the
    module docstring's claim - that a reader does not have to know which
    language a repository is written in - would have quietly stopped being
    true. §272 found that same claim already false in the other reader.
    """
    pattern_output, pattern_input = _block_patterns(prefix)
    output: str | None = None
    inputs: dict[str, str] = {}
    line_number = 0
    for index, raw in enumerate(source.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        if not line.startswith(prefix):
            break
        matched_output = pattern_output.match(line)
        if matched_output:
            if output is not None:
                raise DeclarationError("this file declares more than one output")
            output = matched_output.group("name")
            line_number = index
            continue
        matched_input = pattern_input.match(line)
        if matched_input:
            alias = matched_input.group("alias")
            if alias in inputs:
                raise DeclarationError(f"input {alias!r} is declared twice")
            inputs[alias] = matched_input.group("name")

    if output is None:
        if inputs and orphan_inputs_are_an_error:
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
