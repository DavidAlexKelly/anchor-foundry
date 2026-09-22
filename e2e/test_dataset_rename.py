"""Renaming a dataset, and what it costs (§435; `dataset-preview` p.2).

    "The header also allows some file related operations such as sharing,
     moving, renaming, and more." (p.2)

The rules are in `apps/api/tests/test_dataset_rename.py` and
`apps/web/src/lib/dataset-rename.test.ts`. What needs a browser is the half no
pure function can hold: that the control exists at all — the endpoint has taken
a name since the dataset routes were written and nothing in `apps/web` ever
sent one — that the cost is on the screen *before* the button is pressed, and
that the link to the file somebody has to fix actually goes there.
"""
from __future__ import annotations

import uuid

from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually


def project(api, name: str) -> Module:
    return Module(api, name)


def dataset(mod: Module, name: str) -> dict:
    """The uploaded dataset, with the id the *web* addresses it by.

    A dataset row and its resource row are two different ids, and only the
    second opens the application (`/r/{resource_id}`).
    """
    made = mod.api.upload_csv(f"{mod.base}/datasets/upload", name,
                              b"id,total\n1,10\n2,20\n")
    resources = mod.api.call("GET", f"{mod.base}/resources")["resources"]
    resource = next(r for r in resources if r["name"] == made["name"])
    return {**made, "resource_id": resource["id"]}


def repository(mod: Module, name: str) -> dict:
    return mod.api.call("POST", f"{mod.base}/repositories", {"name": name})


def commit(mod: Module, repo: dict, files: dict[str, str]) -> dict:
    return mod.api.call(
        "POST", f"{mod.base}/repositories/{repo['id']}/commits",
        {"branch": "main", "files": files, "message": "a change"},
    )


def open_details(page, made: dict) -> None:
    page.goto(f"{WEB_BASE}/r/{made['resource_id']}?tab=details")
    expect(page.get_by_test_id("dataset-rename")).to_be_visible(timeout=30000)


def test_a_dataset_can_be_renamed_from_the_screen(page, api) -> None:
    """**The control that did not exist.** `PATCH /datasets/{id}` has taken a
    name since the routes were written; nothing in the product ever sent one,
    so a dataset named by a typo stayed named by it."""
    mod = project(api, "Rename plain")
    made = dataset(mod, f"orders_{mod.tag}")
    open_details(page, made)

    fresh = f"daily_orders_{uuid.uuid4().hex[:6]}"
    page.get_by_test_id("rename-input").fill(fresh)
    page.get_by_test_id("rename-save").click()

    expect(page.get_by_test_id("rename-done")).to_be_visible(timeout=20000)
    eventually(
        lambda: mod.api.call("GET", f"{mod.base}/datasets/{made['id']}")["name"],
        lambda name: name == fresh,
        what="the server to have the new name",
    )


def test_the_link_does_not_change_with_the_name(page, api) -> None:
    """A slug that followed the name would turn every saved URL into a 404 the
    first time somebody fixed a typo — which is the point of p.2 listing "name"
    and "display name" as different things."""
    mod = project(api, "Rename slug")
    made = dataset(mod, f"orders_{mod.tag}")
    open_details(page, made)

    page.get_by_test_id("rename-input").fill(f"renamed_{uuid.uuid4().hex[:6]}")
    page.get_by_test_id("rename-save").click()
    expect(page.get_by_test_id("rename-done")).to_contain_text("link has not changed")

    # The same URL still opens it, which is the claim rather than the sentence.
    page.reload()
    expect(page.get_by_test_id("dataset-rename")).to_be_visible(timeout=30000)


def test_the_button_refuses_a_name_nothing_could_do_with(page, api) -> None:
    mod = project(api, "Rename refusals")
    made = dataset(mod, f"orders_{mod.tag}")
    open_details(page, made)

    save = page.get_by_test_id("rename-save")
    # It opens on the current name, so there is nothing to do yet — and no
    # sentence either, because "that is already its name" about a form nobody
    # has touched is noise.
    expect(save).to_be_disabled()
    expect(page.get_by_test_id("rename-problem")).to_have_count(0)

    page.get_by_test_id("rename-input").fill("   ")
    expect(save).to_be_disabled()
    expect(page.get_by_test_id("rename-problem")).to_contain_text("needs a name")


def test_a_name_another_dataset_has_is_refused_with_its_slug(page, api) -> None:
    """**The rule the platform assumed and never wrote down** (db 0099). A
    transform declares what it reads by name, so two of them cannot share
    one — and the refusal says which dataset has it, which a constraint
    cannot."""
    mod = project(api, "Rename clash")
    first = dataset(mod, f"alpha_{mod.tag}")
    second = dataset(mod, f"beta_{mod.tag}")
    open_details(page, second)

    page.get_by_test_id("rename-input").fill(first["name"])
    page.get_by_test_id("rename-save").click()
    failure = page.get_by_test_id("rename-failure")
    expect(failure).to_be_visible(timeout=20000)
    expect(failure).to_contain_text(first["slug"])


def test_a_dataset_nothing_names_says_renaming_is_safe(page, api) -> None:
    """A warning that appears only sometimes is one a reader learns to look
    for; its absence has to mean something too."""
    mod = project(api, "Rename safe")
    made = dataset(mod, f"lonely_{mod.tag}")
    open_details(page, made)

    expect(page.get_by_test_id("rename-warning")).to_contain_text("breaks nothing")
    expect(page.get_by_test_id("rename-files")).to_have_count(0)


def test_the_cost_is_on_the_screen_before_the_button_is_pressed(page, api) -> None:
    """**The whole reason this is not a text box.** Renaming edits, at a
    distance, every file that declares the old name — and the worse of the two
    cases is silent, so it is named first."""
    mod = project(api, "Rename cost")
    source = dataset(mod, f"src_{mod.tag}")
    repo = repository(mod, f"Transforms {mod.tag}")
    out = f"daily_{uuid.uuid4().hex[:6]}"
    commit(mod, repo, {
        "src/t.sql":
            f"-- output: {out}\n-- input: raw = {source['name']}\nSELECT id FROM raw\n",
    })

    open_details(page, source)
    warning = page.get_by_test_id("rename-warning")
    expect(warning).to_contain_text("read")
    expect(warning).to_contain_text("already been published")
    # And the file is named rather than counted, with a link to it.
    expect(page.get_by_test_id("rename-files")).to_contain_text("src/t.sql")


def test_the_file_link_opens_the_file(page, api) -> None:
    """A list of paths somebody has to find by hand is a list nobody uses."""
    mod = project(api, "Rename link")
    source = dataset(mod, f"src_{mod.tag}")
    repo = repository(mod, f"Transforms {mod.tag}")
    commit(mod, repo, {
        "src/t.sql":
            f"-- output: d_{uuid.uuid4().hex[:6]}\n-- input: raw = {source['name']}\n"
            "SELECT id FROM raw\n",
    })

    open_details(page, source)
    page.get_by_test_id("rename-files").get_by_role("link").first.click()
    page.wait_for_url(lambda url: "tab=files" in url and "src%2Ft.sql" in url,
                      timeout=30000)
    expect(page.locator(".repo-file-head code")).to_have_text("src/t.sql", timeout=30000)


def test_a_file_that_writes_it_is_named_as_the_worse_case(page, api) -> None:
    """A reader stops publishing and says so; a writer goes on publishing and
    starts filling a different table."""
    mod = project(api, "Rename writer")
    source = dataset(mod, f"in_{mod.tag}")
    out = dataset(mod, f"out_{mod.tag}")
    repo = repository(mod, f"Transforms {mod.tag}")
    commit(mod, repo, {
        "src/t.sql":
            f"-- output: {out['name']}\n-- input: raw = {source['name']}\n"
            "SELECT id FROM raw\n",
    })

    open_details(page, out)
    expect(page.get_by_test_id("rename-warning")).to_contain_text(
        "create a new dataset under the old name"
    )
    expect(page.get_by_test_id("rename-files")).to_contain_text("writes")


def test_after_a_rename_the_screen_says_what_is_left_to_fix(page, api) -> None:
    """**The one sentence a rename must not answer with.**

    The live warning is about the *new* name, and nothing declares that — so
    on its own the screen would answer a rename with "renaming it breaks
    nothing" at exactly the moment the files that declared the old name are
    broken. The list somebody was warned about stays, as what is left to do.
    """
    mod = project(api, "Rename aftermath")
    source = dataset(mod, f"src_{mod.tag}")
    repo = repository(mod, f"Transforms {mod.tag}")
    commit(mod, repo, {
        "src/t.sql":
            f"-- output: d_{uuid.uuid4().hex[:6]}\n-- input: raw = {source['name']}\n"
            "SELECT id FROM raw\n",
    })

    open_details(page, source)
    expect(page.get_by_test_id("rename-warning")).to_contain_text("read")

    page.get_by_test_id("rename-input").fill(f"renamed_{uuid.uuid4().hex[:6]}")
    page.get_by_test_id("rename-save").click()
    expect(page.get_by_test_id("rename-done")).to_be_visible(timeout=20000)

    # What is left to fix, by its *old* name and with a link to the file.
    broke = page.get_by_test_id("rename-broke")
    expect(broke).to_contain_text(source["name"])
    expect(broke).to_contain_text("src/t.sql")

    # And the live warning has caught up with the new name rather than still
    # describing the old one.
    eventually(
        lambda: page.get_by_test_id("rename-warning").text_content() or "",
        lambda said: "breaks nothing" in said,
        what="the warning to be about the name the dataset now has",
    )
