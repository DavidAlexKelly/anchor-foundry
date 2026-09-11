"""One thing the browser suite relies on, made checkable (§311).

`e2e/api.py`'s `Module` takes `workspaces[0]` from a list
`workspaces.list_for_user` orders **by name**. So a test that creates a
workspace whose name sorts early becomes `[0]` for every test that runs after
it — in that process, and, because the dev database is never reset, in every
later run on that machine too.

**§308 did exactly that and §310 undid it.** An empty-state test made a
workspace called "Empty searches …", which sorts before the seeded one. CI
starts from a clean database, so there it sorted first and five later tests
built themselves in the wrong workspace; locally nine of them had piled up,
one per run, each poisoning the next.

§310 wrote the rule down in `Module`'s constructor. This is the same rule with
something behind it, for §302's reason: a comment is a claim, and the claims
nobody executes are the ones that go quietly false. The cost of *this* one
going false is a CI failure whose cause is in a different file from every test
that fails.

**A Python test for a property of the Python browser suite**, but deliberately
in the API suite rather than in `e2e/` — the browser suite takes half an hour
and needs a running stack, and this is a fact about text on disk that should
fail in seconds.

**Where the mutation testing stops, and why it stops there.** The helpers below
are mutation-tested through the manufactured-breakage cases: break the regex,
lose a line number, scan the wrong files, and one of them goes red. The
`assert` statements are not, and cannot be — weakening a test's own assertion
*is* deleting the test, and no suite can answer "would deleting this test be
noticed?" about itself. §311's run confirmed it: three mutants that softened
the floors and the refusal survived, as every such mutant always will. The
honest place to stop is one level up, at the helpers, which is where the
searching actually happens.
"""
from __future__ import annotations

import os
import re

#: The repo root: this file is `<root>/apps/api/tests/`, so four levels up.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

SUITE = os.path.join(ROOT, "e2e")

#: `POST` to `/workspaces` **and nothing after it**. The distinction is the
#: whole check: `POST f"/workspaces/{wid}/object-types"` is how nearly every
#: fixture in the suite builds anything, and a rule that caught those would be
#: deleted within the hour.
CREATES_A_WORKSPACE = re.compile(
    r"""["']POST["']\s*,\s*(?:f\s*)?["']/workspaces["']"""
)

#: Any `POST` at all, so a scanner that has stopped matching can be told from a
#: suite that has stopped posting.
ANY_POST = re.compile(r"""["']POST["']""")


def suite_files() -> list[str]:
    """Every Python file in the browser suite, `api.py` and `conftest.py`
    included — a fixture creating a workspace is the case that actually
    happened."""
    return sorted(
        os.path.join(SUITE, name)
        for name in os.listdir(SUITE)
        if name.endswith(".py")
    )


def creations_in(text: str) -> list[int]:
    """The line numbers, one-based, that create a workspace."""
    return [
        n for n, line in enumerate(text.splitlines(), start=1)
        if CREATES_A_WORKSPACE.search(line)
    ]


def posts_in(text: str) -> int:
    return len(ANY_POST.findall(text))


def test_no_browser_test_creates_a_workspace() -> None:
    """The rule `Module` relies on.

    The failure names the file and line, and says what to do instead, because
    the fix is nearly always the one §310 took: the thing being asserted was a
    sentence, and a sentence is checkable without a browser at all.
    """
    offenders = [
        f"{os.path.relpath(path, ROOT)}:{line}"
        for path in suite_files()
        for line in creations_in(open(path, encoding="utf-8").read())
    ]
    assert offenders == [], (
        "these create a workspace, and `Module` takes `workspaces[0]` from a "
        "list ordered by name — so a name that sorts early silently moves every "
        "test after it into the wrong workspace, and the dev database keeps it "
        "there for later runs:\n  " + "\n  ".join(offenders) + "\n"
        "If what you need is a state an existing workspace cannot be in, that "
        "is usually a sentence rather than a screen (§310)."
    )


def test_the_check_says_no_when_a_test_creates_one() -> None:
    """**Manufactured breakage**, for §298's reason.

    The check above is a search that finds nothing when it passes, and a search
    that has quietly stopped matching finds nothing too. Both quoting styles,
    because the suite uses both.
    """
    assert creations_in('api.call("POST", "/workspaces", {"name": "x"})') == [1]
    assert creations_in("api.call('POST', '/workspaces', {})") == [1]
    assert creations_in('    made = api.call(\n') == []
    # The line number is real, so the failure can be opened.
    assert creations_in('one\ntwo\napi.call("POST", "/workspaces", {})') == [3]


def test_the_check_leaves_alone_what_the_suite_does_constantly() -> None:
    """A rule that caught these would be deleted within the hour.

    Nearly every fixture in the suite posts *into* a workspace, and an f-string
    path is the normal form — so the trailing `/` is what separates building
    something from creating the workspace it goes in.
    """
    assert creations_in('api.call("POST", f"/workspaces/{wid}/object-types", {})') == []
    assert creations_in('api.call("POST", f"/workspaces/{wid}/projects", {})') == []
    assert creations_in('api.call("GET", "/workspaces")') == []
    # And a mention in prose is not a call.
    assert creations_in("# never POST to /workspaces from a test") == []


def test_the_scanner_is_looking_at_a_suite_that_posts() -> None:
    """The vacuity guard.

    A check that finds no offenders is indistinguishable from one pointed at an
    empty directory, and this repository has met that failure more than once.
    Both floors matter: the files have to be there, and they have to contain
    the kind of call the rule is about.
    """
    files = suite_files()
    assert len(files) >= 40, files
    total = sum(posts_in(open(path, encoding="utf-8").read()) for path in files)
    assert total >= 50, total


def test_the_rule_is_written_where_somebody_would_meet_it() -> None:
    """The check and the comment have to agree, or one of them is a trap.

    A test that refuses a line of code without the code saying why leaves
    whoever hits it guessing, and §310 put the reason in `Module`'s constructor
    precisely because that is where somebody reads `workspaces[0]` and wonders.
    """
    api = open(os.path.join(SUITE, "api.py"), encoding="utf-8").read()
    assert 'api.call("GET", "/workspaces")[0]' in api, (
        "`Module` no longer takes `workspaces[0]`; if the coupling is gone, "
        "this whole file should go with it rather than forbidding something "
        "that no longer matters"
    )
    assert "sorts early" in api or "sorted before" in api, (
        "the reason `workspaces[0]` is fragile is no longer written beside it"
    )
