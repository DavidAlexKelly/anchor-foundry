"""p.13's Foundry Explorer helper, in the repository application (§303).

    "The Foundry Explorer helper is a file navigation interface that lets you
     quickly browse all files and folders. Once you select a specific dataset,
     you can click 'Open' to view the full dataset." (p.13)

**Ours browses the platform, not the repository**, for the reason
`explorer.ts` gives: the Files tab beside this one is already a file tree, and
a second one would be a second answer to what is in this repository. What the
editor has no way to see is everything *outside* it, which is what a transform
reads and writes — `code-repositories.md` §2.4 calls that small and
disproportionately valuable, and this is it.

The wording and ordering rules are in `apps/web/src/lib/explorer.test.ts`.
What needs a browser is the **seam**: that the panel asks for the right things
and that Open arrives somewhere.

**Names, not counts.** Object types belong to the workspace rather than to a
project, so every other test's fixtures are legitimately in this listing — that
is the panel working, not a leak. An assertion on how many rows there are would
be an assertion about what else ran today.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE


def project(api, name: str) -> Module:
    return Module(api, name)


def repository(mod: Module, name: str) -> dict:
    return mod.api.call("POST", f"{mod.base}/repositories", {"name": name})


def open_explorer(page, repo: dict) -> None:
    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=files")
    toggle = page.get_by_test_id("explorer-toggle")
    expect(toggle).to_be_visible(timeout=30000)
    toggle.click()


def seed(mod: Module) -> None:
    """A dataset and an object type, both named after this module's tag."""
    mod.object_type(columns=["id", "name"], rows=[{"id": "1", "name": "a"}], key="id")


def test_the_panel_lists_the_projects_datasets_and_the_object_types(page, api) -> None:
    """The seam. Both sections, each under its own heading.

    The object type is the half that would silently never appear: it belongs to
    the *workspace*, so a listing scoped to the project would show an empty
    Object types section in every project in the platform and look like a
    feature that does not work rather than a request nobody made.
    """
    mod = project(api, "Explorer lists")
    seed(mod)
    repo = repository(mod, f"Transforms {mod.tag}")

    open_explorer(page, repo)
    expect(page.get_by_test_id("explorer-dataset")).to_contain_text(
        f"seed_{mod.tag}", timeout=30000)
    expect(page.get_by_test_id("explorer-dataset")).to_contain_text("Datasets")
    expect(page.get_by_test_id("explorer-object_type")).to_contain_text(
        f"Seed {mod.tag}")
    expect(page.get_by_test_id("explorer-object_type")).to_contain_text("Object types")


def test_the_panel_is_closed_until_it_is_asked_for(page, api) -> None:
    """It costs a round trip, like every panel in this column.

    Asserted as the *rows* being absent rather than the section, because the
    section's toggle is always there — that is what you click.
    """
    mod = project(api, "Explorer closed")
    seed(mod)
    repo = repository(mod, f"Transforms {mod.tag}")

    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=files")
    expect(page.get_by_test_id("explorer-toggle")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("explorer-dataset")).to_have_count(0)
    page.get_by_test_id("explorer-toggle").click()
    expect(page.get_by_test_id("explorer-dataset")).to_contain_text(f"seed_{mod.tag}")


def test_open_goes_to_the_dataset_itself(page, api) -> None:
    """p.13's one verb. "Click Open to view the full dataset."

    The link is built from the resource's **id**, and this asserts where it
    arrives rather than what the href says: a link built from the name — which
    is the mistake that looks correct, because the name is right there beside
    the button — would resolve to nothing.
    """
    mod = project(api, "Explorer open")
    seed(mod)
    repo = repository(mod, f"Transforms {mod.tag}")

    open_explorer(page, repo)
    link = page.get_by_test_id(f"explorer-open-seed_{mod.tag}")
    expect(link).to_be_visible(timeout=30000)
    link.click()
    # It arrives at the dataset application, showing the dataset's own name.
    expect(page.get_by_text(f"seed_{mod.tag}").first).to_be_visible(timeout=30000)
    assert "/r/" in page.url


def test_a_search_narrows_the_list_and_says_so_when_it_matches_nothing(page, api) -> None:
    """The server searches; the panel decides when to ask.

    Both halves asserted together on purpose: a search that narrows to nothing
    has to *say* it was the search, because "no datasets in this project" sends
    the reader somewhere else entirely to fix it.
    """
    mod = project(api, "Explorer search")
    seed(mod)
    repo = repository(mod, f"Transforms {mod.tag}")

    open_explorer(page, repo)
    expect(page.get_by_test_id("explorer-dataset")).to_contain_text(
        f"seed_{mod.tag}", timeout=30000)

    page.get_by_test_id("explorer-search").fill(f"seed_{mod.tag}")
    expect(page.get_by_test_id("explorer-dataset")).to_contain_text(f"seed_{mod.tag}")

    page.get_by_test_id("explorer-search").fill("nothingmatchesthis")
    empty = page.get_by_test_id("explorer-empty")
    expect(empty).to_be_visible(timeout=30000)
    expect(empty).to_contain_text("nothingmatchesthis")
    # And it blames the search rather than the project, which is the whole
    # point of telling the two absences apart.
    expect(empty).not_to_contain_text("No datasets or object types yet")


def test_one_character_is_not_a_search(page, api) -> None:
    """Below the threshold the panel sends nothing and keeps the full list.

    A single character matches most of a platform, so treating it as a search
    is a list that empties and refills as somebody types a word. `shouldSearch`
    decides both what is sent *and* what the empty state blames, so this also
    pins those two together: if they disagreed, one character would show the
    unfiltered list under a message saying nothing matched it.
    """
    mod = project(api, "Explorer one char")
    seed(mod)
    repo = repository(mod, f"Transforms {mod.tag}")

    open_explorer(page, repo)
    expect(page.get_by_test_id("explorer-dataset")).to_contain_text(
        f"seed_{mod.tag}", timeout=30000)

    # A character that cannot be in the tagged name, so if it *were* sent as a
    # search the row would go.
    page.get_by_test_id("explorer-search").fill("z")
    expect(page.get_by_test_id("explorer-dataset")).to_contain_text(f"seed_{mod.tag}")
    expect(page.get_by_test_id("explorer-empty")).to_have_count(0)
