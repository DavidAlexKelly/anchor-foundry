"""The parity specifications cite. Nothing opened what they cited (§302).

`docs/parity/` is this project's build order and its scoreboard: five
specifications, 204 rows marked ✅ meaning *this part of Foundry is here*, and
837 citations into the official PDFs in `docs/pal/` saying where each
requirement came from. **Not one of those citations was ever resolved.** A test
file could be renamed, a PDF replaced with a longer edition, a page number
mistyped, and every document would go on saying the same thing; the only reader
who would find out is a person going to look, a month later, at the one row
that mattered to them.

That is this repository's recurring finding — *two things that must agree, kept
apart* — sitting on the document that decides what gets built next. §216's rule
is "open what a line cites before building on it"; this is that rule, run.

**Three claims are checkable, and they are checked here.**

1. A backticked path is a file that exists.
2. A source's page count, which each specification writes into its own header
   (`foundry_ontology.pdf` (172 pp)), is the PDF's real page count.
3. A cited page exists in a source that specification names.

**One is not, and is deliberately absent: `§NNN`.** A section number is a
reference into a narrative, and this repository keeps no machine-readable
ledger of sections — eleven of the numbers cited by finished rows appear in no
source file and eight appear in no commit message either, because the units
that earned them were squashed or left their mark only in prose. A check over
"does this number appear anywhere" would pass on coincidence and fail on §301,
which is a real unit of work whose whole change was a test. Enforcing it would
mean grandfathering eight numbers, and a grandfather list is a thing that rots
into the reason the check gets deleted.

**What this establishes is names, not behaviour.** A row citing
`e2e/test_tags.py` is checked to the extent that the file is there; whether it
tests tags is that file's business, and §299's mutation run is what answered
it. So this is a check against **rot** — the rename, the move, the replaced
edition, the typo — which is exactly the failure mode a hand-maintained
scoreboard has, and which care does not prevent, because the person doing the
renaming is not reading the scoreboard.

**A Python test for a Markdown property**, for `test_one_editor.py`'s reason:
it is a fact about files on disk, and this is the suite that will be run.
"""
from __future__ import annotations

import os
import re

import pypdf

#: The repo root: this file is `<root>/apps/api/tests/`, so four levels up.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

PARITY = os.path.join(ROOT, "docs", "parity")
PAL = os.path.join(ROOT, "docs", "pal")

#: Where a path citation may point. Not the whole repository: `docs/` holds the
#: specifications themselves and quotes their own filenames, and a check a
#: document could satisfy by mentioning itself is not a check.
SOURCE_TREES = ("apps", "packages", "e2e", "scripts", ".github")

#: What counts as naming a file of ours. Extensions we actually write, so a
#: sentence about a `.csv` upload or a `.parquet` output stays prose. `.json`
#: is deliberately out: the only one the specifications name is
#: `repoSettings.json`, which lives at the root of a **customer's** repository
#: (p.17's tag-name convention is read out of it), and requiring it on disk
#: here would be requiring the platform to contain its users' files.
SOURCE_SUFFIXES = (".py", ".ts", ".tsx", ".sql", ".sh", ".yml")

TICK = "✅"

#: A backticked span ending in one of our suffixes. Backticks matter: prose
#: says "the tests panel", code voice says `e2e/test_tests_panel.py`, and only
#: the second is making a claim about a path.
QUOTED_PATH = re.compile(r"`([^`\s]+(?:" + "|".join(
    s.replace(".", r"\.") for s in SOURCE_SUFFIXES) + r"))`")

PDF_NAME = re.compile(r"foundry_[a-z0-9-]+\.pdf")

#: `foundry_ontology.pdf` (172 pp)` and `foundry_workshop.pdf`, 718 pages` -
#: both forms are in use, in headers written a month apart.
DECLARED_PAGES = re.compile(
    r"`(foundry_[a-z0-9-]+\.pdf)`[^\n]{0,4}?\(?(\d+)\s*(?:pp|pages)\b")

#: A page citation, optionally qualified by the source's slug the way
#: `ontology.md`'s own header asks for: "Citations name the file:
#: `(object-link-types p.127)`".
PAGE = re.compile(r"(?:([a-z][a-z0-9-]*)\s+)?\bp\.(\d+)\b")


def specifications() -> list[str]:
    """Every parity document, by absolute path."""
    return sorted(
        os.path.join(PARITY, name)
        for name in os.listdir(PARITY)
        if name.endswith(".md")
    )


def page_counts() -> dict[str, int]:
    """Every PDF in `docs/pal/`, by name, with its real length."""
    return {
        name: len(pypdf.PdfReader(os.path.join(PAL, name)).pages)
        for name in sorted(os.listdir(PAL))
        if name.endswith(".pdf")
    }


def claims(text: str) -> list[tuple[int, str]]:
    """The lines that say a thing is done, numbered from one.

    A ✅ anywhere on the line, not only in a table cell: the acceptance-test
    list at the foot of `code-repositories.md` marks its items in running
    prose, and those are the rows that name test files most often.
    """
    return [
        (n, line) for n, line in enumerate(text.splitlines(), start=1)
        if TICK in line
    ]


def paths_in(line: str) -> set[str]:
    """The backticked file names on one line."""
    return set(QUOTED_PATH.findall(line))


def source_files() -> list[str]:
    """Every file under the source trees, repo-relative, forward-slashed.

    Walked once and shared, because the alternative is a filesystem search per
    citation and there are hundreds of citations.
    """
    found: list[str] = []
    for tree in SOURCE_TREES:
        for here, dirs, files in os.walk(os.path.join(ROOT, tree)):
            dirs[:] = [
                d for d in dirs
                if d not in {"node_modules", "__pycache__", ".next", ".pytest_cache"}
            ]
            for name in files:
                rel = os.path.relpath(os.path.join(here, name), ROOT)
                found.append(rel.replace(os.sep, "/"))
    return found


def resolves(cited: str, files: list[str]) -> bool:
    """Whether a cited path names a file that is there.

    **A suffix match, not equality**, because the specifications cite at the
    precision the sentence needs: `models/page.tsx` where the pillar is obvious
    from the paragraph, `apps/worker/tests/test_execution_parity.py` where it
    is not. Requiring the full path would push them into writing out
    `apps/web/src/app/(platform)/…` in the middle of an argument, which is how
    a rule gets deleted for being in the way.

    Anchored on a path separator, so `page.tsx` alone does not pass by matching
    some unrelated `page.tsx` — a citation still has to name enough of the path
    to be about one file.
    """
    wanted = cited.replace(os.sep, "/").lstrip("./")
    return any(f == wanted or f.endswith("/" + wanted) for f in files)


def sources_named(text: str) -> list[str]:
    """The PDFs a specification says it is written from."""
    return sorted(set(PDF_NAME.findall(text)))


def declared_lengths(text: str) -> dict[str, int]:
    """The page counts a specification writes into its own header."""
    return {name: int(count) for name, count in DECLARED_PAGES.findall(text)}


def page_citations(text: str) -> list[tuple[int, str | None, int]]:
    """Every `p.N`, with the source slug in front of it if there was one."""
    found: list[tuple[int, str | None, int]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for qualifier, page in PAGE.findall(line):
            found.append((number, qualifier or None, int(page)))
    return found


def _slug(pdf: str) -> str:
    return pdf[len("foundry_"):-len(".pdf")]


def unreachable_pages(
    text: str, counts: dict[str, int]
) -> list[str]:
    """Citations naming a page no source of this document has.

    **Exact when the citation is qualified, widest-source when it is not**, and
    the difference is worth stating because the unqualified case is the weak
    one: `ontology.md` is written from five PDFs, so an unqualified `p.200`
    only has to fit the 274-page one, and a page number that belongs to the
    74-page manual passes. That is the honest limit of a citation that does not
    say what it cites, and it is why `ontology.md`'s header asks for the
    qualified form. It still catches the error that actually happened — a
    number larger than *every* source, which is a citation into a document the
    reader would never find.

    A single-source specification has no weak case at all, and three of the
    five are single-source.
    """
    named = sources_named(text)
    if not named:
        return []
    by_slug = {_slug(p): counts[p] for p in named if p in counts}
    widest = max(by_slug.values(), default=0)

    problems: list[str] = []
    for line, qualifier, page in page_citations(text):
        if qualifier in by_slug:
            if page > by_slug[qualifier]:
                problems.append(
                    f"line {line}: {qualifier} p.{page}, but "
                    f"foundry_{qualifier}.pdf has {by_slug[qualifier]} pages"
                )
        elif page > widest:
            problems.append(
                f"line {line}: p.{page}, but the longest source this document "
                f"names has {widest} pages"
            )
    return problems


def unresolved_paths(text: str, files: list[str]) -> list[str]:
    """Every path citation on a ✅ line that is not a file, named with its line.

    Returned rather than asserted so the manufactured-breakage test can call
    the same function on a document it wrote itself: the check has to be
    demonstrably able to say no, and the only way to show that is to hand it
    something that should get one.
    """
    return [
        f"line {number}: `{cited}` is not a file here"
        for number, line in claims(text)
        for cited in sorted(paths_in(line))
        if not resolves(cited, files)
    ]


def test_every_path_a_finished_row_cites_is_there() -> None:
    """The rot check.

    The failure names the document, the line and the citation, because the fix
    is one of three and which one depends on the answer: the file moved (update
    the row), the file went (the row is no longer true), or it is a typo.
    """
    files = source_files()
    broken = [
        f"{os.path.relpath(path, ROOT)} {problem}"
        for path in specifications()
        for problem in unresolved_paths(open(path, encoding="utf-8").read(), files)
    ]
    assert broken == [], (
        "the parity specifications cite files that are not where they say:\n  "
        + "\n  ".join(broken)
    )


def test_the_declared_page_counts_are_the_pdfs_real_lengths() -> None:
    """Each specification's header says how long its sources are. Check it.

    This is the cheapest fact in the set and the one most likely to go quietly
    wrong: a PDF re-exported from a later edition of the documentation keeps
    its filename, gains fifty pages, and every page number in a 454-citation
    specification now points somewhere else. The header is the only place that
    would notice, and only if somebody compares it.
    """
    counts = page_counts()
    wrong = []
    for path in specifications():
        text = open(path, encoding="utf-8").read()
        for name, declared in declared_lengths(text).items():
            actual = counts.get(name)
            if actual is None:
                wrong.append(
                    f"{os.path.relpath(path, ROOT)} names {name}, which is not "
                    "in docs/pal/"
                )
            elif actual != declared:
                wrong.append(
                    f"{os.path.relpath(path, ROOT)} says {name} is {declared} "
                    f"pages; it is {actual}"
                )
    assert wrong == [], "\n  " + "\n  ".join(wrong)


def test_every_source_a_specification_names_is_in_the_library() -> None:
    """A citation into a PDF nobody has is a citation into nothing."""
    counts = page_counts()
    missing = []
    for path in specifications():
        text = open(path, encoding="utf-8").read()
        for name in sources_named(text):
            if name not in counts:
                missing.append(f"{os.path.relpath(path, ROOT)} names {name}")
    assert missing == [], "\n  " + "\n  ".join(missing)


def test_every_cited_page_exists_in_a_source_the_document_names() -> None:
    """§216's rule, run over all 837 citations.

    Found `ontology.md` citing p.582 and p.583 against a set of sources whose
    longest is 274 pages. The pages are real and the sentence is right — they
    are `foundry_workshop.pdf`'s, and they do name Map, Metric Card and Object
    Table — but a reader following the citation as written would open a
    274-page PDF and find nothing. Qualified, which is what that document's own
    header asks for.
    """
    counts = page_counts()
    problems = [
        f"{os.path.relpath(path, ROOT)} {problem}"
        for path in specifications()
        for problem in unreachable_pages(open(path, encoding="utf-8").read(), counts)
    ]
    assert problems == [], (
        "the parity specifications cite pages their sources do not have:\n  "
        + "\n  ".join(problems)
    )


def test_the_checks_say_no_when_a_citation_is_wrong() -> None:
    """**Manufactured breakage**, for §298's reason.

    Every check above is a search that returns nothing when it passes, and a
    search that has quietly stopped matching returns nothing too. Each way of
    being wrong gets its own case, so a partial regression is a partial failure
    rather than a silent pass.
    """
    files = source_files()
    counts = page_counts()

    # A path that was never there.
    assert len(unresolved_paths(
        "| Thing | ✅ | in `e2e/test_a_thing_nobody_wrote.py` |", files)) == 1
    # A file that exists, cited under a directory it is not in - the rename.
    assert len(unresolved_paths(
        "| Thing | ✅ | in `apps/web/test_tags.py` |", files)) == 1
    # Two on one line are two problems, not one.
    assert len(unresolved_paths(
        "| ✅ | `e2e/no_such.py` and `apps/api/no_such.py` |", files)) == 2

    # A page past the end of the single source this fragment names.
    over = unreachable_pages(
        "From `foundry_code-repositories.pdf`. See p.900.", counts)
    assert len(over) == 1, over
    # The same page, qualified against a source long enough to have it.
    assert unreachable_pages(
        "From `foundry_workshop.pdf`. See workshop p.700.", counts) == []
    # Qualified against one that is not, while a longer source is also named -
    # the case the unqualified check is blind to and this one is not.
    narrow = unreachable_pages(
        "From `foundry_workshop.pdf` and `foundry_ontology-manager.pdf`. "
        "See ontology-manager p.700.", counts)
    assert len(narrow) == 1, narrow

    # A declared length that disagrees with the file.
    assert declared_lengths("`foundry_workshop.pdf` (99 pp)") == {
        "foundry_workshop.pdf": 99}
    assert page_counts()["foundry_workshop.pdf"] != 99


def test_an_unfinished_row_is_not_path_checked() -> None:
    """A row without a ✅ makes no claim, so its paths are plans.

    This is the half that keeps the rule usable. `code-repositories.md` names
    the test it *intends* to write beside each item it has not built yet — that
    is what a build order is — and a check that resolved those too would force
    every plan to be written before it could be recorded.
    """
    planned = "| Explorer | ⬜ | will be `e2e/test_explorer.py` |"
    assert unresolved_paths(planned, source_files()) == []


def test_the_specifications_still_parse_as_claiming_things() -> None:
    """The vacuity guard: a parser that matched nothing would pass everything.

    Three separate floors, because there are three ways for this file to go
    quietly green: the tick stops being recognised (a different character, a
    table rewritten as a list), one document goes dark while the others hold
    the total up, or the citations stop being found.
    """
    per_document = {}
    citations = 0
    for path in specifications():
        text = open(path, encoding="utf-8").read()
        per_document[os.path.basename(path)] = len(claims(text))
        citations += len(page_citations(text))

    assert len(per_document) >= 5, per_document
    silent = [name for name, count in per_document.items() if count == 0]
    assert silent == [], (
        f"these specifications no longer parse as claiming anything: {silent}"
    )
    assert sum(per_document.values()) >= 150, per_document
    assert citations >= 500, citations


def test_the_finished_rows_mostly_say_what_made_them_true() -> None:
    """Every citation resolving is trivially true of a document with none.

    So the rules above are worth what the habit of citing is worth, and this is
    the floor under the habit. A floor rather than a requirement on every row:
    the earliest ticks predate the convention and say `create, list, delete`
    where a citation would say less, and rewriting history to satisfy a check
    is how a check starts lying.
    """
    cited = total = 0
    for path in specifications():
        for _number, line in claims(open(path, encoding="utf-8").read()):
            total += 1
            if paths_in(line) or "§" in line or re.search(r"\bp\.\d", line):
                cited += 1
    assert total > 0
    assert cited >= total // 2, (
        f"only {cited} of {total} finished rows say what made them true; "
        "a scoreboard nobody can check is a scoreboard in name only"
    )
