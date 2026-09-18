"""p.13's Build button and p.14's Build helper, which are one thing (§385).

    "If you select a dataset source file […] you can click the [build] button
     to build a new version of your output dataset after running automatic
     checks on your code. Clicking the button will trigger a build on all
     output datasets of the current file; **if the current file does not
     generate any datasets, no build is triggered**." (p.13)

    "The Build helper lets you trigger dataset builds and **view the progress**
     for your builds." (p.14)

    "Clicking the Build button at the top right corner of the Code
     Repositories interface is **equivalent to** triggering a build from the
     Build helper." (p.14)

Foundry says the trigger and the panel are one feature; §384 found this
platform's checklist carrying them as two ○ rows whose notes disagreed about
whether either was worth doing. They are built together because the button
alone is §214's control that looks like it works.

The wording rules are in `apps/web/src/lib/build-runs.test.ts`. What needs a
browser is the **seam**: press it, and the dataset gains a version.

**SQL, deliberately.** `POST /models/{id}/run` executes a SQL transform inline
through the same sandboxed DuckDB path the worker uses, so these tests need no
worker turn — unlike `test_tests_panel.py`, which has to drive the op itself.
A Python transform would be the same seam through one more queue, and the
queue is not what this feature is about.
"""
from __future__ import annotations

import uuid

from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE


def project(api, name: str) -> Module:
    return Module(api, name)


def repository(mod: Module, name: str) -> dict:
    return mod.api.call("POST", f"{mod.base}/repositories", {"name": name})


def dataset(mod: Module) -> str:
    """A dataset **named so a declaration can find it**.

    A transform names its inputs by dataset name, so the name has to be one
    the declaration syntax can carry: no spaces. The first draft of this used
    `f"Src {mod.tag}"`, the input resolved to nothing, and the model published
    with no inputs at all — which the panel then refused to offer a button for,
    correctly and for the reason it exists. The fixture was wrong, not the
    code, and it took the panel saying so to notice.
    """
    name = f"orders_{uuid.uuid4().hex[:8]}"
    mod.api.upload_csv(f"{mod.base}/datasets/upload", name,
                       b"id,total\n1,10\n2,20\n")
    return name


def commit(mod: Module, repo: dict, files: dict[str, str]) -> dict:
    return mod.api.call(
        "POST", f"{mod.base}/repositories/{repo['id']}/commits",
        {"branch": "main", "files": files, "message": "a transform"},
    )


def sql(output: str, source: str) -> str:
    """The declaration `transform_publish` reads, in its documented form."""
    return f"-- output: {output}\n-- input: raw = {source}\nSELECT id, total FROM raw\n"


def publish(mod: Module, repo: dict) -> dict:
    return mod.api.call(
        "POST", f"{mod.base}/repositories/{repo['id']}/publish", {"branch": "main"},
    )


def open_build(page, repo: dict, path: str) -> None:
    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=files&file={path}")
    expect(page.locator(".code-editor-loading")).to_have_count(0, timeout=30000)
    page.get_by_test_id("build-toggle").click()


def a_published_transform(api, name: str) -> tuple[Module, dict, str]:
    """A project whose repository publishes one SQL transform from one file."""
    mod = project(api, name)
    source = dataset(mod)
    repo = repository(mod, f"Transforms {mod.tag}")
    out = f"daily_{uuid.uuid4().hex[:8]}"
    commit(mod, repo, {"src/daily.sql": sql(out, source)})
    publish(mod, repo)
    return mod, repo, out


def test_building_the_current_file_gives_its_dataset_a_version(page, api) -> None:
    """**The seam, end to end.** p.13's button builds "a new version of your
    output dataset", and p.14's helper shows what became of it — so the test
    presses the one and reads the other, because a build nobody can see the
    result of is the half §384 found missing."""
    mod, repo, _out = a_published_transform(api, "Build runs")

    open_build(page, repo, "src/daily.sql")
    # Before anything is asked for, the panel says so rather than showing a
    # tick over a build that never happened.
    expect(page.get_by_test_id("build-verdict")).to_have_text("never built", timeout=30000)

    page.get_by_test_id("build-run").click()
    # The row is the progress view: p.14's "view the progress for your builds".
    expect(page.get_by_test_id("build-verdict")).to_contain_text("built", timeout=60000)
    expect(page.get_by_test_id("build-runs")).to_contain_text("succeeded")
    # A version, which is what p.13 says the button produces.
    expect(page.get_by_test_id("build-runs")).to_contain_text("v1")


def test_a_file_that_publishes_nothing_says_so_rather_than_offering_a_button(
    page, api
) -> None:
    """**p.13's no-op rule, said rather than performed.**

    Foundry's answer to a file that generates no datasets is that "no build is
    triggered" — a button that quietly does nothing, which is exactly §214's
    control that looks like it works. Saying why is a better answer to the same
    fact: an unpublished transform is one publish away, and nothing else on the
    screen says so.
    """
    mod, repo, _out = a_published_transform(api, "Build nothing")
    # A second file in the same repository that declares no transform, so the
    # difference under test is *this file*, not this repository.
    commit(mod, repo, {"src/notes.md": "# not a transform\n"})

    open_build(page, repo, "src/notes.md")
    # Positive first (§318): the panel has answered before an absence means
    # anything.
    expect(page.get_by_test_id("build-blocked")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("build-blocked")).to_contain_text("only a transform file")
    expect(page.get_by_test_id("build-run")).to_have_count(0)


def test_an_unpublished_transform_is_told_apart_from_a_file_that_is_not_one(
    page, api
) -> None:
    """The other half of the same rule, and the reason it is two sentences.

    A `.sql` file nobody has published and a `.md` file are both "does not
    generate any datasets" in p.13's wording, and they send a reader to
    different places: one is a publish away from building, the other will never
    build. A single sentence for both hides the actionable one.
    """
    mod = project(api, "Build unpublished")
    source = dataset(mod)
    repo = repository(mod, f"Transforms {mod.tag}")
    out = f"daily_{uuid.uuid4().hex[:8]}"
    # Committed and never published, which is the state under test.
    commit(mod, repo, {"src/daily.sql": sql(out, source)})

    open_build(page, repo, "src/daily.sql")
    blocked = page.get_by_test_id("build-blocked")
    expect(blocked).to_be_visible(timeout=30000)
    expect(blocked).to_contain_text("not been published")
    expect(page.get_by_test_id("build-run")).to_have_count(0)
