"""The SQL Scratchpad's reference syntax (§305; p.15).

    "The SQL helper lets you quickly test out SQL queries. Write a SQL query
     and click [run] to preview the results of your query." (p.15)

    "To access a specific branch of an input dataset in SQL Scratchpad, you
     prepend the name of the branch to the query: e.g. ``SELECT * FROM
     `branch_A`.`/path/to/dataset` ``. If no branch is specified it will
     default to master." (p.15)

**A scratchpad query names datasets directly**, which is what separates it
from the Preview helper next door: a transform declares its inputs and gets
aliases, and an ad-hoc query has no declaration to read. So the names in the
query *are* the references, and this module is what reads them.

**Backticks are Foundry's engine, not ours.** Foundry runs Spark, where a
backtick quotes an identifier; DuckDB has no backtick syntax at all and fails
at the parser. Supporting p.15's sentence therefore means *translating* it —
every reference is rewritten to a double-quoted identifier and the sampled
input is created under exactly that name. That is a real difference and it is
here rather than in a note, because the alternative was to invent a different
syntax and stop being able to cite p.15 at all.

**The qualifier is parsed and then refused, deliberately.** Datasets in this
platform are *versioned*, not branched — migration 0025 chose that on purpose
("copy a version into a separate dataset to experiment against, not git-style
branch/merge semantics") and `docs/parity/README.md` puts Global Branching out
of scope. The worst possible answer to `` `branch_A`.`/orders` `` is to ignore
the qualifier and run against the current version: that returns a table, so
nobody checks it, and it answers a question nobody asked. Refusing names the
model difference and leaves the syntax free for a branch name later, which is
the door README asks every branching decision to leave open.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


class ScratchpadError(ValueError):
    """Refusal, phrased for whoever wrote the query."""


#: What may sit between a pair of backticks. A dataset here is named, not
#: pathed, but p.15's example is a path and somebody reading it will type one —
#: so both are read and `resolve` is what decides whether the name exists.
_INSIDE = r"[A-Za-z0-9_./-]+"

#: One reference: `` `path` `` or `` `qualifier`.`path` ``.
_REFERENCE = re.compile(
    rf"`(?P<first>{_INSIDE})`(?:\s*\.\s*`(?P<second>{_INSIDE})`)?"
)


@dataclass(frozen=True)
class Reference:
    """One dataset named in a query."""

    #: What p.15 calls the branch. Always refused here — see the module
    #: docstring — but kept rather than dropped so the refusal can quote it.
    qualifier: str | None
    #: The dataset, as written. A leading slash is p.15's path style and is not
    #: part of the name.
    path: str

    @property
    def name(self) -> str:
        """The dataset name to look up.

        **The last segment**, so that p.15's `/path/to/dataset` and a bare
        `dataset` resolve to the same row. Projects here are flat, so a path is
        a way of writing a name rather than a location — reading it as one and
        then failing to find a dataset called `path/to/dataset` would refuse a
        query written exactly as the documentation shows.
        """
        return self.path.rstrip("/").rsplit("/", 1)[-1]


def _spans_to_skip(sql: str) -> list[tuple[int, int]]:
    """Where a backtick is text rather than syntax.

    String literals and comments. `SELECT '\\`/orders\\`'` is a query about a
    string that happens to hold backticks, and rewriting inside it would
    change what the query returns — which is the kind of bug that shows up as
    a wrong answer rather than an error.
    """
    spans: list[tuple[int, int]] = []
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'":
            j = i + 1
            while j < len(sql):
                if sql[j] == "'":
                    # `''` is an escaped quote inside the literal, not its end.
                    if j + 1 < len(sql) and sql[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            spans.append((i, min(j + 1, len(sql))))
            i = j + 1
            continue
        if ch == '"':
            j = sql.find('"', i + 1)
            end = len(sql) if j == -1 else j + 1
            spans.append((i, end))
            i = end
            continue
        if sql.startswith("--", i):
            end = sql.find("\n", i)
            end = len(sql) if end == -1 else end
            spans.append((i, end))
            i = end
            continue
        if sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            end = len(sql) if end == -1 else end + 2
            spans.append((i, end))
            i = end
            continue
        i += 1
    return spans


def _inside(position: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= position < end for start, end in spans)


def references(sql: str) -> list[Reference]:
    """Every dataset named in the query, in the order they appear.

    Duplicates are kept: a self-join names one dataset twice, and the caller
    binds by name, so collapsing them here would hide a query that reads the
    same thing under two qualifiers.
    """
    skip = _spans_to_skip(sql)
    found: list[Reference] = []
    for match in _REFERENCE.finditer(sql):
        if _inside(match.start(), skip):
            continue
        first, second = match.group("first"), match.group("second")
        if second is None:
            found.append(Reference(qualifier=None, path=first))
        else:
            found.append(Reference(qualifier=first, path=second))
    return found


def _unterminated(sql: str) -> bool:
    """A backtick with no partner, outside a literal.

    Worth its own refusal rather than being left to the engine: DuckDB's
    message for a stray backtick is `syntax error at or near "\\`"`, which is
    true and tells somebody who wrote p.15's syntax nothing at all.
    """
    skip = _spans_to_skip(sql)
    outside = [i for i, ch in enumerate(sql) if ch == "`" and not _inside(i, skip)]
    return len(outside) % 2 == 1


def bind(sql: str) -> tuple[str, list[Reference]]:
    """The query DuckDB can parse, and what it reads.

    Every reference becomes a double-quoted identifier holding the dataset's
    name, and the caller creates a table under exactly that name. Rewriting is
    the whole of the translation from Foundry's engine to ours.

    **A qualifier is refused here rather than by the caller**, because this is
    where the syntax is understood and a refusal that arrived two layers later
    would have lost the text somebody wrote.
    """
    if _unterminated(sql):
        raise ScratchpadError(
            "there is a ` with no closing ` in this query. A dataset is named "
            "between a pair of them, as in SELECT * FROM `/path/to/dataset`"
        )

    found = references(sql)
    for reference in found:
        if reference.qualifier is not None:
            raise ScratchpadError(
                f"`{reference.qualifier}`.`{reference.path}` names a branch, and "
                "datasets here are versioned rather than branched - a dataset "
                "fork is a separate dataset with its own name (db 0025). Name "
                f"that one directly, or drop the `{reference.qualifier}`. to "
                "read the current version"
            )

    skip = _spans_to_skip(sql)

    def rewrite(match: re.Match[str]) -> str:
        if _inside(match.start(), skip):
            return match.group(0)
        first, second = match.group("first"), match.group("second")
        raw = first if second is None else second
        name = Reference(qualifier=None, path=raw).name
        # A double quote cannot reach here: `_INSIDE` does not admit one.
        return f'"{name}"'

    return (_REFERENCE.sub(rewrite, sql), found)


def unresolved(found: list[Reference], available: set[str]) -> list[str]:
    """The names this project does not have, deduplicated and sorted.

    **Every one, not the first.** A query naming three datasets of which two
    are missing is otherwise two round trips through the same refusal, and the
    second arrives after the author thinks they have finished — the same
    argument `transform_declarations.unwritable` makes about names it cannot
    write.
    """
    return sorted({r.name for r in found if r.name not in available})
