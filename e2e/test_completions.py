"""Completions over the platform's own names (§434; `code-repositories` p.2).

    "Every repository type includes integrated features to aid with the code
     authoring experience, including IntelliSense, code linting and error
     checking, and rich help dialogs." (p.2)

Monaco already completes the language. What no editor can guess is that this
project has a dataset called `raw_orders`, that this file declared it as `raw`,
and that it has a column called `total` — and those are the three things
somebody writing a transform types wrong.

Which vocabulary belongs where is decided in
`apps/web/src/lib/completions.test.ts`. What needs a browser is that the
suggestions reach *Monaco*: a provider registered against a real editor,
triggered by a real keystroke, offering rows somebody can press Enter on. A
pure function nothing registers is a list nobody sees.
"""
from __future__ import annotations

import uuid

from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually


def project(api, name: str) -> Module:
    return Module(api, name)


def repository(mod: Module, name: str) -> dict:
    return mod.api.call("POST", f"{mod.base}/repositories", {"name": name})


def dataset(mod: Module, name: str) -> dict:
    """**Returned whole, because a dataset has two names.**

    `name` is what somebody typed and `slug` is what the URL uses, and a
    declaration resolves by *name* (`transform_publish.plan`). A fixture whose
    two names are identical cannot tell the two apart, and the completion that
    offered the slug would look right and publish as an unknown input.
    """
    return mod.api.upload_csv(f"{mod.base}/datasets/upload", name,
                              b"id,total,placed_at\n1,10,2026-01-01\n")


def commit(mod: Module, repo: dict, files: dict[str, str]) -> dict:
    return mod.api.call(
        "POST", f"{mod.base}/repositories/{repo['id']}/commits",
        {"branch": "main", "files": files, "message": "a change"},
    )


def a_repository(api, name: str, body: str) -> tuple[Module, dict, str]:
    mod = project(api, name)
    repo = repository(mod, f"Transforms {mod.tag}")
    # **Capitals, so the dataset's name and its slug differ.** No space: the
    # declaration syntax is `[A-Za-z0-9_.-]+` (`transform_declarations.py`), so
    # a name with a space could not be declared at all and offering it would be
    # offering something unusable.
    made = dataset(mod, f"Raw_Orders_{mod.tag}")
    source = str(made["name"])
    assert made["slug"] != source, "the fixture cannot tell a name from a slug"
    commit(mod, repo, {"src/t.sql": body.replace("<SOURCE>", source)})
    return mod, repo, source


def open_file(page, repo: dict, path: str = "src/t.sql") -> None:
    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=files&file={path}")
    expect(page.locator(".code-editor-loading")).to_have_count(0, timeout=30000)
    expect(page.locator(".view-lines").first).to_be_visible(timeout=30000)


def suggestions(page) -> list[str]:
    """What Monaco is offering, by label.

    Read off the widget rather than off the model: the claim is that these
    rows are in front of somebody, and a provider that returned them to
    nobody would satisfy any weaker assertion.
    """
    return page.locator(".suggest-widget .monaco-list-row .label-name").evaluate_all(
        "rows => rows.map(r => r.textContent.trim())"
    )


def type_at_end(page, text: str) -> None:
    page.locator(".view-lines").first.click()
    page.keyboard.press("Control+End")
    page.keyboard.type(text)


def test_a_datasets_name_is_offered_where_an_input_is_declared(page, api) -> None:
    """**The unit, in one line.** `-- input: raw = ` is the place somebody has
    to get a name exactly right, with nothing on the screen to check it
    against."""
    mod, repo, source = a_repository(
        api, "Completions input", "-- output: out_x\nSELECT 1 AS id\n",
    )
    open_file(page, repo)

    page.locator(".view-lines").first.click()
    page.keyboard.press("Control+Home")
    page.keyboard.type("-- input: raw = raw_o")
    # **By name, exactly.** A dataset has two, and a declaration resolves by
    # `name` (`transform_publish.plan`) — offering the slug would look right on
    # the screen and publish as an unknown input.
    eventually(lambda: suggestions(page), lambda s: source in s,
               what="the project's dataset to be offered by name")
    assert source.lower() != source, "the fixture's name must differ from its slug"


def test_a_declared_alias_is_offered_after_from(page, api) -> None:
    """The alias is this *file's* word for the dataset, so no dictionary has
    it — it exists only in the header two lines above."""
    mod, repo, source = a_repository(
        api, "Completions alias",
        f"-- output: out_y\n-- input: raw = <SOURCE>\nSELECT id FROM raw\n",
    )
    open_file(page, repo)

    type_at_end(page, "SELECT id FROM ra")
    eventually(lambda: suggestions(page), lambda s: "raw" in s,
               what="the alias this file declared to be offered")


def test_a_columns_name_is_offered_after_the_alias(page, api) -> None:
    """Three things somebody types wrong, and this is the third: the column
    names live in the dataset's schema and nowhere in the file."""
    mod, repo, source = a_repository(
        api, "Completions column",
        "-- output: out_z\n-- input: raw = <SOURCE>\nSELECT id FROM raw\n",
    )
    open_file(page, repo)

    type_at_end(page, "\nWHERE raw.")
    eventually(lambda: suggestions(page), lambda s: "placed_at" in s,
               what="the input's columns to be offered after the dot")
    # And it is the dataset's own columns rather than every word in the file.
    assert "out_z" not in suggestions(page)


def test_nothing_is_offered_for_an_alias_the_file_has_not_declared(page, api) -> None:
    """**The negative, after a positive wait.**

    A provider that answered every dot with every column in the project would
    look like it worked. The positive wait is the real alias offering its
    columns, which proves the provider is registered and running — so the
    absence below is about the rule rather than about a race (§318).
    """
    mod, repo, source = a_repository(
        api, "Completions unknown alias",
        "-- output: out_w\n-- input: raw = <SOURCE>\nSELECT id FROM raw\n",
    )
    open_file(page, repo)

    type_at_end(page, "\nWHERE raw.")
    eventually(lambda: suggestions(page), lambda s: "placed_at" in s,
               what="a declared alias to offer its columns")
    page.keyboard.press("Escape")

    page.keyboard.type("\nAND nope.")
    # Monaco's own word-based suggestions may still appear; what must not is a
    # column of a dataset this alias does not point at.
    eventually(lambda: suggestions(page), lambda s: "placed_at" not in s,
               what="an undeclared alias to offer no columns")


def test_pressing_enter_inserts_what_was_offered(page, api) -> None:
    """A suggestion nobody can accept is a list, not a completion."""
    mod, repo, source = a_repository(
        api, "Completions accept", "-- output: out_v\nSELECT 1 AS id\n",
    )
    open_file(page, repo)

    page.locator(".view-lines").first.click()
    page.keyboard.press("Control+Home")
    page.keyboard.type("-- input: raw = raw_o")
    eventually(lambda: suggestions(page), lambda s: source in s,
               what="the dataset to be offered")
    page.keyboard.press("Enter")

    eventually(
        lambda: page.locator(".view-lines").first.inner_text().replace("\xa0", " "),
        lambda text: source in text,
        what="the accepted suggestion to be in the file",
    )
