"""p.67-69's in-product documentation (§442; `code-repositories` p.67-69).

    "You can provide users with documentation on projects in Code Repositories
     by adding a README file. README files in Code Repositories support
     Markdown… Edit or add a README.md file to your repository to get
     started." (p.67)

    "You can reference any Foundry resource by pasting its Resource ID directly
     into the Markdown file for the README. Resources referenced like this will
     automatically be named and linked to the corresponding resource in
     platform." (p.68)

    "To create a link to a file within your repository, use the repo://
     protocol followed by the file path… Files referenced like this will
     automatically open when clicked." (p.68)

The Markdown syntax is `canvas/markdown.test.ts`'s and the two link rewrites
are `lib/readme.test.ts`'s. What needs a browser is the pair neither can see:
that the README on screen is **this branch's**, and that p.68's two links
actually go where they say — a resource id named after a lookup nobody made in
a unit test, and a `repo://` path that opens the file rather than navigating
away from the documentation.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE


@pytest.fixture(scope="module")
def documented(api):
    """A repository whose README mentions a dataset by id and a file by path.

    The dataset is real, because p.68's "automatically be named" is the claim
    worth checking and a made-up id would only ever show the fallback.
    """
    mod = Module(api, "Repo docs")
    name = f"orders_{uuid.uuid4().hex[:8]}"
    made = mod.api.upload_csv(f"{mod.base}/datasets/upload", name,
                              b"id,total\n1,10\n")
    # `DatasetOut` carries no resource id; the registry is where the mapping
    # lives, and `/r/{id}` is what a pasted id has to be.
    resources = mod.api.call("GET", f"{mod.base}/resources")["resources"]
    dataset = {**made,
               "resource_id": next(r["id"] for r in resources
                                   if r["name"] == made["name"])}
    repo = mod.api.call("POST", f"{mod.base}/repositories",
                        {"name": f"Transforms {mod.tag}"})
    readme = (
        "# Daily orders\n\n"
        "The logic lives in repo://transforms/daily.sql and it writes\n"
        f"{dataset['resource_id']}.\n\n"
        "| Column | Meaning |\n| --- | --- |\n| total | pennies |\n\n"
        "Do not paste `repo://an/example.sql` in prose.\n"
    )
    mod.api.call(
        "POST", f"{mod.base}/repositories/{repo['id']}/commits",
        {"branch": "main", "message": "the first cut",
         "files": {"README.md": readme,
                   "transforms/daily.sql": "SELECT id, total FROM raw\n"}},
    )
    return {"mod": mod, "repo": repo, "dataset": dataset}


def open_docs(page, repo: dict) -> None:
    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=docs")
    expect(page.get_by_test_id("repo-docs")).to_be_visible(timeout=30000)


def test_the_readme_is_rendered_rather_than_shown_as_text(page, documented) -> None:
    """p.67: "README files in Code Repositories support Markdown for flexible,
    easy-to-use formatting". A panel that printed the source would satisfy any
    assertion about the words being present."""
    open_docs(page, documented["repo"])
    docs = page.get_by_test_id("repo-docs")
    expect(docs.locator("h1")).to_have_text("Daily orders")
    expect(docs.locator("table th").first).to_have_text("Column")
    expect(docs).not_to_contain_text("# Daily orders")


def test_a_pasted_resource_id_is_linked_by_its_name(page, documented) -> None:
    """p.68's "automatically be named and linked". The name is the half a unit
    test cannot reach — it comes from resolving the id."""
    open_docs(page, documented["repo"])
    link = page.get_by_test_id("repo-docs").locator(
        f"a[href='/r/{documented['dataset']['resource_id']}']")
    expect(link).to_be_visible(timeout=30000)
    expect(link).to_have_text(documented["dataset"]["name"])
    # And it is a name rather than the id it was written as.
    expect(link).not_to_have_text(documented["dataset"]["resource_id"])


def test_following_a_resource_link_opens_the_resource(page, documented) -> None:
    """A link that is named and goes nowhere is worse than the bare id."""
    open_docs(page, documented["repo"])
    page.get_by_test_id("repo-docs").locator(
        f"a[href='/r/{documented['dataset']['resource_id']}']").click()
    page.wait_for_url(lambda url: documented["dataset"]["resource_id"] in url,
                      timeout=30000)
    expect(page.locator(".app-title h1")).to_have_text(documented["dataset"]["name"],
                                                       timeout=30000)


def test_a_repo_link_opens_the_file_in_this_repository(page, documented) -> None:
    """p.68: "Files referenced like this will automatically open when
    clicked."""
    open_docs(page, documented["repo"])
    page.get_by_test_id("repo-docs").get_by_role(
        "link", name="transforms/daily.sql").click()
    page.wait_for_url(lambda url: "file=transforms" in url, timeout=30000)
    expect(page.locator(".code-editor-loading")).to_have_count(0, timeout=30000)
    expect(page.locator(".view-lines")).to_contain_text("SELECT id, total",
                                                        timeout=30000)


def test_an_example_in_code_stays_an_example(page, documented) -> None:
    """A README explaining the syntax is exactly the document that contains
    it, and p.67's own page is one."""
    open_docs(page, documented["repo"])
    docs = page.get_by_test_id("repo-docs")
    expect(docs).to_contain_text("repo://an/example.sql")
    expect(docs.get_by_role("link", name="an/example.sql")).to_have_count(0)


def test_a_repository_with_no_readme_says_how_to_make_one(page, api) -> None:
    """p.67's instruction is the whole answer, and a panel saying "no
    documentation" leaves somebody looking for a setting that does not
    exist."""
    mod = Module(api, "Repo undocumented")
    repo = mod.api.call("POST", f"{mod.base}/repositories",
                        {"name": f"Bare {mod.tag}"})
    mod.api.call(
        "POST", f"{mod.base}/repositories/{repo['id']}/commits",
        {"branch": "main", "message": "the first cut",
         "files": {"transforms/daily.sql": "SELECT 1\n"}},
    )

    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=docs")
    empty = page.get_by_test_id("docs-empty")
    expect(empty).to_be_visible(timeout=30000)
    expect(empty).to_contain_text("README.md")
    expect(page.get_by_test_id("repo-docs")).to_have_count(0)


def test_the_readme_is_the_branch_the_reader_is_on(page, api) -> None:
    """**Documentation that lagged behind the code beside it would be
    documentation about a different repository.**

    Asserted by *changing* it on a branch rather than by reading the default,
    so a panel hard-wired to the default branch fails here and nowhere else.
    """
    mod = Module(api, "Repo docs branch")
    repo = mod.api.call("POST", f"{mod.base}/repositories",
                        {"name": f"Branched {mod.tag}"})
    mod.api.call(
        "POST", f"{mod.base}/repositories/{repo['id']}/commits",
        {"branch": "main", "message": "on main", "files": {"README.md": "# On main\n"}},
    )
    mod.api.call(
        "POST", f"{mod.base}/repositories/{repo['id']}/branches",
        {"name": "sandbox", "from_branch": "main"},
    )
    mod.api.call(
        "POST", f"{mod.base}/repositories/{repo['id']}/commits",
        {"branch": "sandbox", "message": "on the sandbox",
         "files": {"README.md": "# On the sandbox\n"}},
    )

    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=docs")
    expect(page.get_by_test_id("repo-docs")).to_contain_text("On main", timeout=30000)

    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=docs&branch=sandbox")
    expect(page.get_by_test_id("repo-docs")).to_contain_text("On the sandbox",
                                                             timeout=30000)
