"""A shortcut to a resource (§436; `getting-started` p.34).

    "You can add and remove favorites with the star icon while navigating the
     folder structure or **from within an open resource** in a Palantir
     platform application." (p.34)

§312 built the paragraph below that sentence — the star on an object view. This
is the sentence itself. The rules are in `apps/api/tests/test_favourites.py`
and `apps/web/src/lib/favourites.test.ts`; what needs a browser is that the
star is in *every* application's header rather than in one of them, that it
survives a reload, and that the shortcut it leaves behind opens the thing it
points at.
"""
from __future__ import annotations

import time
import uuid

from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually


def project(api, name: str) -> Module:
    return Module(api, name)


def dataset(mod: Module, name: str) -> dict:
    made = mod.api.upload_csv(f"{mod.base}/datasets/upload", name,
                              b"id,total\n1,10\n2,20\n")
    resources = mod.api.call("GET", f"{mod.base}/resources")["resources"]
    resource = next(r for r in resources if r["name"] == made["name"])
    return {**made, "resource_id": resource["id"]}


def repository(mod: Module, name: str) -> dict:
    return mod.api.call("POST", f"{mod.base}/repositories", {"name": name})


def open_resource(page, resource_id: str) -> None:
    page.goto(f"{WEB_BASE}/r/{resource_id}")
    expect(page.get_by_test_id("resource-favourite")).to_be_visible(timeout=30000)


def star(page):
    return page.get_by_test_id("resource-favourite")


def starred(page) -> bool:
    return star(page).get_attribute("data-favourite") == "true"


def clear(mod: Module) -> None:
    """Leave the workspace's list empty, whichever kind each row is.

    The list is per user and the suite shares one, so a test that assumed an
    empty list would pass alone and fail after any other (§271).
    """
    for f in mod.api.call("GET", f"/workspaces/{mod.workspace_id}/object-favourites"):
        if f.get("resource_id"):
            mod.api.call(
                "DELETE", f"/workspaces/{mod.workspace_id}/resource-favourites/{f['resource_id']}")
        else:
            mod.api.call(
                "DELETE",
                f"/workspaces/{mod.workspace_id}/object-favourites/"
                f"{f['object_type_id']}/{f['instance_id']}",
            )


def test_the_star_is_in_every_applications_header(page, api) -> None:
    """**One control, not one per application.** The thing being starred is
    the resource, which every application shares and none of them owns — the
    same argument the Copy link button beside it is built on."""
    mod = project(api, "Star everywhere")
    made = dataset(mod, f"orders_{mod.tag}")
    repo = repository(mod, f"Transforms {mod.tag}")

    open_resource(page, made["resource_id"])
    expect(star(page)).to_be_visible()

    open_resource(page, repo["resource_id"])
    expect(star(page)).to_be_visible()


def test_starring_keeps_a_shortcut_that_survives_a_reload(page, api) -> None:
    mod = project(api, "Star persists")
    clear(mod)
    made = dataset(mod, f"orders_{mod.tag}")

    open_resource(page, made["resource_id"])
    assert starred(page) is False
    star(page).click()
    eventually(lambda: starred(page), lambda yes: yes,
               what="the star to fill in")

    page.reload()
    expect(star(page)).to_be_visible(timeout=30000)
    eventually(lambda: starred(page), lambda yes: yes,
               what="the star to still be filled after a reload")

    # And it is a toggle: the same press takes it back off.
    star(page).click()
    eventually(lambda: starred(page), lambda yes: not yes,
               what="the star to empty again")


def test_the_shortcut_opens_the_resource_it_points_at(page, api) -> None:
    """**A favourite is a shortcut** (p.34), so the test is whether it takes
    you back — a list that only remembered the name would be a list of names."""
    mod = project(api, "Star opens")
    clear(mod)
    made = dataset(mod, f"orders_{mod.tag}")

    open_resource(page, made["resource_id"])
    star(page).click()
    eventually(lambda: starred(page), lambda yes: yes, what="the star to fill in")

    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}")
    shortcut = page.get_by_test_id(f"favourite-resource-{made['resource_id']}")
    expect(shortcut).to_be_visible(timeout=30000)
    expect(shortcut).to_contain_text(made["name"])
    shortcut.click()

    page.wait_for_url(lambda url: made["resource_id"] in url, timeout=30000)
    expect(star(page)).to_be_visible(timeout=30000)


def test_a_project_with_no_shortcuts_shows_no_strip(page, api) -> None:
    """**Silent rather than empty.** The Explorer's list is a panel somebody
    opened; this sits above a project's whole contents, and a permanent empty
    box over the thing you came to read is furniture people learn to look
    past."""
    mod = project(api, "Star none")
    clear(mod)
    dataset(mod, f"orders_{mod.tag}")

    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}")
    expect(page.locator(".resource-browser")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("rb-favourites")).to_have_count(0)


def test_a_shortcut_says_what_kind_of_thing_it_points_at(page, api) -> None:
    """Two shortcuts with the same label are still tellable apart, and the
    kind is the only other thing on the row."""
    mod = project(api, "Star kind")
    clear(mod)
    repo = repository(mod, f"Transforms {mod.tag}")

    open_resource(page, repo["resource_id"])
    star(page).click()
    eventually(lambda: starred(page), lambda yes: yes, what="the star to fill in")

    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}")
    shortcut = page.get_by_test_id(f"favourite-resource-{repo['resource_id']}")
    expect(shortcut).to_be_visible(timeout=30000)
    # "Repository", not `code_repo` — a column value is not a noun.
    expect(shortcut).to_contain_text("Repository")


def test_no_star_is_drawn_until_the_answer_is_known(page, api) -> None:
    """**An unfilled star is a claim, not a placeholder** (§312's rule).

    It means "not a favourite", so drawing one before the server has answered
    tells somebody their shortcut is gone — and the press that follows would
    remove a favourite they still had. The request is held up here on purpose,
    because the honest state lasts a few milliseconds otherwise and a test of
    it would be a test of how fast the machine is.
    """
    mod = project(api, "Star unknown")
    clear(mod)
    made = dataset(mod, f"orders_{mod.tag}")
    mod.api.call("PUT", f"/workspaces/{mod.workspace_id}/resource-favourites",
                 {"resource_id": made["resource_id"], "label": made["name"]})

    def slowly(route):
        time.sleep(2)
        route.continue_()

    page.route("**/resource-favourites/**", slowly)
    page.goto(f"{WEB_BASE}/r/{made['resource_id']}")
    # The bar is up — the shell rendered — and the star is not on it yet.
    expect(page.locator(".app-toolbar")).to_be_visible(timeout=30000)
    expect(star(page)).to_have_count(0)

    page.unroute("**/resource-favourites/**")
    eventually(lambda: starred(page), lambda yes: yes,
               what="the star to arrive already filled in")


def test_the_star_itself_says_which_state_it_is_in(page, api) -> None:
    """A test that only read an attribute would pass over a star that drew the
    same glyph either way — and the glyph is the whole control."""
    mod = project(api, "Star glyph")
    clear(mod)
    made = dataset(mod, f"orders_{mod.tag}")

    open_resource(page, made["resource_id"])
    expect(star(page)).to_have_text("☆")
    star(page).click()
    eventually(lambda: star(page).text_content(), lambda t: t == "★",
               what="the star to fill in on the screen, not only in an attribute")


def test_an_object_shortcut_is_not_listed_among_the_resources(page, api) -> None:
    """**One store, two lists, and each keeps only what it can open.**

    An object shortcut has no resource id, so a strip that took the whole
    listing would render a link to `/r/null` — a shortcut that goes nowhere,
    in the place somebody goes to use one.
    """
    mod = project(api, "Star kinds apart")
    clear(mod)
    type_id = mod.object_type(
        columns=["id", "name"],
        rows=[{"id": "1", "name": "Ada"}],
        key="id",
        title="name",
    )
    instance = uuid.uuid4()
    mod.api.call("PUT", f"/workspaces/{mod.workspace_id}/object-favourites",
                 {"object_type_id": type_id, "instance_id": str(instance),
                  "label": "An object"})
    made = dataset(mod, f"orders_{mod.tag}")
    mod.api.call("PUT", f"/workspaces/{mod.workspace_id}/resource-favourites",
                 {"resource_id": made["resource_id"], "label": made["name"]})

    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}")
    strip = page.get_by_test_id("rb-favourites")
    # The positive wait first: the resource shortcut is there, so the strip has
    # rendered and the absence below is about the filter (§318).
    expect(strip.get_by_test_id(f"favourite-resource-{made['resource_id']}")).to_be_visible(
        timeout=30000
    )
    expect(strip).not_to_contain_text("An object")
    clear(mod)
