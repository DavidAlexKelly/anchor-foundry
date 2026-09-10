"""Problems detected in a repository's code (§286; `code-repositories.md` §2.4).

p.14: *"The Problems helper tells you about any issues detected in your code.
Click on a specific issue listed here to open up the problematic code."*

**Every problem here is one the platform already knows how to refuse.** The
publish path refuses a file that declares nothing, two files claiming one
output, and an input naming a dataset the project does not have; DuckDB refuses
SQL it cannot parse; the declaration reader refuses Python that does not parse.
What was missing was not the knowledge - it was *when*: all of it arrived at
publish time, hours after the code was written, in a message about the whole
commit rather than about a line.

So this is deliberately **not a second rule engine**. It runs the same readers
and reports what they say, against the working set rather than against a
commit. A rule that lived only here would be a rule the publish does not
enforce, and a rule the publish enforces but this does not see would be exactly
the surprise the panel exists to prevent.

**Warnings and errors are not the same thing** and the panel would be useless
if they were. An error is something that will refuse a publish. A warning is
something worth knowing that will not: a `.sql` file declaring no transform is
perfectly legal - a repository may hold anything - but a file somebody *meant*
to be a transform and mistyped the output line of looks exactly the same, and
saying so costs nothing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import duckdb
from sqlalchemy.ext.asyncio import AsyncConnection

from . import datasets as ds_service
from . import transform_declarations as declarations

#: Files worth looking at. A repository may hold a README, a `.gitignore` or a
#: fixture; reporting that they declare no transform would bury the one file
#: that does under a list of files that never claimed to.
SOURCE_SUFFIXES = (".sql", ".py")

ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True)
class Problem:
    path: str
    line: int
    severity: str
    message: str
    #: Which reader said so, so the panel can group and a reader can be
    #: recognised again when its wording changes.
    source: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "line": self.line,
            "severity": self.severity,
            "message": self.message,
            "source": self.source,
        }


def line_of(source: str, offset: int) -> int:
    """The 1-based line an offset falls on.

    DuckDB reports a parse failure as a character offset into the statement,
    and a panel that said "syntax error" without saying *where* would be a
    panel somebody reads once. p.14's whole promise is "click on a specific
    issue to open up the problematic code", and a line is the smallest thing
    that can be opened.
    """
    # **Two guards were here and neither did anything** (§213, and a mutant
    # apiece proved it). `offset <= 0` returned 1, which is what
    # `count("\n", 0, 0) + 1` already gives; `min(offset, len(source))` clamped
    # an offset past the end, which `str.count` already clamps. The only inputs
    # they changed were a negative offset and one DuckDB cannot produce - and a
    # guard against an impossible input is a line no test can reach.
    return source.count("\n", 0, offset) + 1


def _parses_as_sql(source: str) -> tuple[str, int] | None:
    """None if DuckDB can parse this, else what it said and where.

    `json_serialize_sql` parses and returns the statement as JSON **without
    running anything** - no tables are resolved, no data is touched. That
    matters twice over: this runs whenever somebody opens the panel, and the
    text is customer code nobody has reviewed. Decision 0004 keeps customer
    *Python* out of this process entirely; SQL is parsed here because parsing
    is not running, and the same parser already refuses at preview time.

    An unparseable statement comes back with `error: true` *inside the JSON*
    rather than as an exception, which is why this reads the answer rather than
    trusting a `try`.

    The declaration comments are left in the text on purpose: DuckDB skips
    `--` comments, so stripping them would buy nothing and make every line
    number wrong.
    """
    try:
        rows = duckdb.execute(
            "SELECT json_serialize_sql(?::VARCHAR)", [source]
        ).fetchone()
    except duckdb.Error as exc:  # pragma: no cover - a malformed argument, not SQL
        return str(exc).strip().splitlines()[0], 1
    if not rows or not rows[0]:
        return None
    try:
        parsed = json.loads(rows[0])
    except ValueError:  # pragma: no cover - DuckDB always returns JSON here
        return None
    if not parsed.get("error"):
        return None
    message = str(parsed.get("error_message") or "this does not parse as SQL")
    try:
        offset = int(parsed.get("position") or 0)
    except (TypeError, ValueError):  # pragma: no cover - always a number in practice
        offset = 0
    return message.strip().splitlines()[0], line_of(source, offset)


def _of_file(
    path: str, source: str
) -> tuple[list[Problem], declarations.Declaration | None]:
    """This file's problems, and what it declares if it declares anything.

    Both at once because the caller needs both and reading twice is how two
    answers to one question start: a file whose declaration is read here and
    again in `find` could be reported as clean and then counted as a producer,
    which is the disagreement this returns a pair to avoid.
    """
    problems: list[Problem] = []
    try:
        declaration = declarations.read(path, source)
    except declarations.DeclarationError as exc:
        # The reader's own words. It knows what is wrong with the file far
        # better than a rephrasing here would, and it already names the line
        # where it can.
        return [Problem(path, 0, ERROR, str(exc), "declaration")], None

    if declaration is None:
        problems.append(
            Problem(
                path, 0, WARNING,
                "this file declares no transform, so publishing ignores it",
                "declaration",
            )
        )
    if path.endswith(".sql"):
        said = _parses_as_sql(source)
        if said is not None:
            problems.append(Problem(path, said[1], ERROR, said[0], "sql"))
    return problems, declaration


async def find(
    conn: AsyncConnection, *, project_id: UUID, files: dict[str, str]
) -> list[dict[str, Any]]:
    """Every problem in this working set, in the order somebody reads them.

    The whole set rather than one file, because "is anything wrong" is the
    question the panel answers and a panel that could only see the open file
    would answer a different one - the file you are looking at is the one you
    are least likely to have forgotten about.
    """
    problems: list[Problem] = []
    declared: dict[str, declarations.Declaration] = {}
    for path in sorted(files):
        if not path.endswith(SOURCE_SUFFIXES):
            continue
        found, one = _of_file(path, files[path])
        problems.extend(found)
        # **A file with an error still declares what it declares.** The first
        # version of this skipped it, on the reasoning that two errors for one
        # mistake reads as two mistakes - which was wrong twice. They are two
        # different mistakes, so fixing the first would make a second appear
        # and the panel would play whack-a-mole; and `transform_publish.plan`
        # checks the clash without parsing any SQL, so hiding it here would
        # make this panel disagree with the refusal it exists to predict.
        if one is not None:
            declared[path] = one

    # Two producers for one dataset. Reported on **both** files rather than on
    # the second one sorted: neither is more wrong than the other, and a panel
    # that blamed `z.sql` because `a.sql` came first would send somebody to fix
    # the wrong file.
    producers: dict[str, list[str]] = {}
    for path, one in declared.items():
        producers.setdefault(one.output, []).append(path)
    for output, paths in producers.items():
        if len(paths) > 1:
            for path in paths:
                others = ", ".join(p for p in sorted(paths) if p != path)
                problems.append(Problem(
                    path, declared[path].line, ERROR,
                    f"{output} is also declared by {others} - one dataset has one producer",
                    "declaration",
                ))

    # Inputs that name nothing. Read once for the whole set rather than per
    # file: the answer cannot differ between two files in one request, and
    # asking twice is how it starts to.
    if declared:
        names = {
            str(row["name"]) for row in await ds_service.list_for_project(conn, project_id)
        }
        for path, one in declared.items():
            for alias, name in sorted(one.inputs.items()):
                if name not in names:
                    problems.append(Problem(
                        path, one.line, ERROR,
                        f"{name} is not a dataset in this project, so {alias} resolves "
                        "to nothing",
                        "input",
                    ))

    # Errors first, then by file, then by line. The panel is read to find what
    # is broken, and a warning above an error is a warning nobody wanted.
    problems.sort(key=lambda p: (p.severity != ERROR, p.path, p.line, p.message))
    return [p.as_dict() for p in problems]
