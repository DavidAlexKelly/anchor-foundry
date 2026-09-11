"""One editor for transforms, and nothing that claims to be a second (§291).

**`code-repositories.md` §10 asks for this by name:** *"grep for `textarea`
under `app/(platform)` and assert `code/page.tsx` is not in the results. Crude,
and it cannot pass for the wrong reason."* It is here rather than in the browser
suite because there is nothing to click: the property is that a file does *not*
contain something, and no amount of driving a browser can establish that.

The line the specification opened with — *"Also delete
`app/(platform)/[workspace]/[project]/code/page.tsx`. 463 lines duplicating
this, worse, with a `<textarea className="code-editor">` at line 332"* — was
right about the editor and wrong about the rest (§278: five capabilities lived
only there). Each of the five has a home now, so the editor is gone and this is
what keeps it gone. A second transform editor is not a thing anybody would add
on purpose; it is a thing that comes back the next time somebody needs a quick
way to change a file and does not know the repository application exists.

**A Python test for a TypeScript property**, deliberately: this is a fact about
files on disk, and `apps/api/tests/test_dependency_pins.py` set the precedent
for keeping that kind of check with the suite that will actually be run.
"""
from __future__ import annotations

import os
import re

#: The repo root: this file is `<root>/apps/api/tests/`, so four levels up.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

PILLAR = os.path.join(ROOT, "apps", "web", "src", "app", "(platform)")
CODE_PAGE = os.path.join(PILLAR, "[workspace]", "[project]", "code", "page.tsx")


def _tsx_under(root: str) -> list[str]:
    found = []
    for here, _dirs, files in os.walk(root):
        for name in files:
            if name.endswith(".tsx") or name.endswith(".ts"):
                found.append(os.path.join(here, name))
    return found


def test_the_pillar_pages_hold_no_transform_editor() -> None:
    """The specification's own acceptance test, run.

    Narrowed to `className="code-editor"` rather than every `<textarea>`: a
    pillar page may perfectly well take a description or a SQL scratchpad, and
    a check that forbids all of them would be deleted the first time it got in
    somebody's way. What must not come back is a *second editor for a
    transform's source*, and that is the class the old one carried.
    """
    offenders = []
    for path in _tsx_under(PILLAR):
        source = open(path, encoding="utf-8").read()
        if re.search(r'<textarea[^>]*className="code-editor"', source, re.S):
            offenders.append(os.path.relpath(path, ROOT))
    assert offenders == [], (
        "a transform editor is back on a pillar page; the repository "
        f"application is the one editor: {offenders}"
    )


def test_the_code_pillar_is_the_repositories_and_not_a_repository() -> None:
    """**The page still exists, and that is the point** — §291 did not delete
    the route, it emptied it and put the thing that was missing in its place.

    Nothing in `apps/web` called `POST /repositories` before: every repository
    in the product had been made by a script, none could be listed anywhere,
    and the application was reachable only by a `/r/{id}` link somebody already
    had. A check that only asserted the *absence* of the editor would pass on a
    blank page and would have passed on the state this replaced.
    """
    source = open(CODE_PAGE, encoding="utf-8").read()
    assert "repoApi.create" in source, "the Code pillar cannot create a repository"
    assert "repoApi.list" in source, "the Code pillar does not list repositories"
    # And it opens into the application by resource id, not by slug: a link
    # built from a workspace and project slug stops working the moment somebody
    # renames either. `openHref` is where that rule lives and is unit-tested.
    assert "openHref" in source
    # The five capabilities §278 found here are gone rather than half-moved.
    for call in ("saveChangeSet", "setReviewPolicy", "codeApi.history", "codeApi.tree"):
        assert call not in source, f"{call} is still on the page it was moved off"
