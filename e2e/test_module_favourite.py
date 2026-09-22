"""p.47's favourite toggle, on the route it governs (§437; `workshop` p.47).

    "Toggle the ability for users to favorite the module in view mode."
    (docs/pal/foundry_workshop.pdf p.47)

**View mode is the published route here**, and that is the whole reason this
file is not a unit test. `module-header.test.ts` decides what a document
*means* — absent is allowed, `false` is not — and a reader nobody called
passes every one of those. What needs a browser is that the star is on the
published page at all, that unticking the builder's box takes it off, and that
pressing it writes the shortcut §436 built.

**The builder's own star is deliberately untouched by the toggle.** A module
opened for editing is a resource like any other and carries the star every
application's header does (p.34); p.47's sentence says "for users… in view
mode". A test for that is here too, because it is the divergence somebody will
otherwise read as a bug.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder, publish, save, select_node, viewer_url

STAR = "[data-testid='resource-favourite']"


def favourite_module(api, name: str, props: dict) -> Module:
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({
            "hdr": {"resolvedName": "CanvasHeader", "props": props},
            "page": {"resolvedName": "CanvasPage",
                     "props": {"title": "Overview", "icon": "◎"},
                     "isCanvas": True,
                     "nodes": ["body"]},
            "body": {"resolvedName": "CanvasText",
                     "props": {"tag": "p", "text": "PAGE BODY"}, "parent": "page"},
        }),
        "variables": {},
        "events": {},
    })
    publish(mod)
    return mod


@pytest.fixture(scope="module")
def allowed(api):
    """A header written before the toggle existed — which is every module in
    the stored corpus, and the case the default is chosen for."""
    return favourite_module(api, "Favouritable", {"title": "Fleet status"})


@pytest.fixture(scope="module")
def refused(api):
    return favourite_module(api, "Not favouritable",
                            {"title": "Locked down", "allowFavourite": False})


def unstar(mod) -> None:
    """Leave the workspace's list as this file found it. The list is shared
    across every suite that stars anything, and §436's cap is a hundred."""
    for f in mod.api.call("GET", f"/workspaces/{mod.workspace_id}/object-favourites"):
        if f.get("resource_id"):
            mod.api.call(
                "DELETE",
                f"/workspaces/{mod.workspace_id}/resource-favourites/{f['resource_id']}",
            )


def open_viewer(page, mod) -> None:
    page.goto(viewer_url(mod))
    # The module rendered, which is what says the route resolved rather than
    # that it is still deciding — a star absent on a page still loading would
    # satisfy every negative assertion below (§318).
    expect(page.locator(".canvas-frame-area")).to_be_visible(timeout=30000)
    # **And the frame is not late enough**, which the sweep had to say out
    # loud: the star waits on a *second* round trip — the module's resource
    # has to resolve before anything can be drawn — so `to_have_count(0)`
    # against a rendered frame is an answer about a page that is still
    # asking. The mutant that offered the star to every module passed
    # `test_unticking_the_box_…` with that wait and no other.
    #
    # Quiet network is the point after which "no star" is a decision rather
    # than a moment. It is available here because a published module makes a
    # bounded number of requests and this fixture configures no auto-refresh;
    # a module that polled would need a different anchor.
    page.wait_for_load_state("networkidle")


def test_a_published_module_offers_the_star(page, allowed) -> None:
    """p.47's ability, present by default. A module written before the setting
    existed has nobody who turned it off."""
    unstar(allowed)
    open_viewer(page, allowed)
    star = page.locator(STAR)
    expect(star).to_be_visible(timeout=30000)
    expect(star).to_have_attribute("data-favourite", "false")


def test_the_star_on_a_published_module_keeps_a_shortcut(page, allowed) -> None:
    """**The press has to reach the store**, which is the half a rendering
    assertion never sees: a star that filled in and wrote nothing looks exactly
    like one that worked."""
    unstar(allowed)
    open_viewer(page, allowed)
    page.locator(STAR).click()
    expect(page.locator(STAR)).to_have_attribute("data-favourite", "true", timeout=30000)

    kept = allowed.api.call(
        "GET", f"/workspaces/{allowed.workspace_id}/object-favourites")
    pointed = [f for f in kept if f.get("resource_id") == allowed.resource_id]
    assert pointed, f"nothing in {kept} points at the module that was starred"
    assert pointed[0]["label"] == f"App {allowed.tag}", pointed[0]
    unstar(allowed)


def test_unticking_the_box_takes_the_star_off_the_published_module(
    page, refused
) -> None:
    """The toggle's whole job. Asserted against a module whose *sibling* has
    the star, so a selector that never matched anything would fail the test
    above rather than passing this one quietly."""
    open_viewer(page, refused)
    expect(page.locator(STAR)).to_have_count(0)


def test_the_builder_keeps_its_own_star_either_way(page, refused) -> None:
    """The divergence, checked rather than described.

    p.47 governs view mode. A module opened for editing is a resource, and
    §436 put a star on every resource application's header — unticking a box
    about viewers must not take away the author's own shortcut.
    """
    open_builder(page, refused)
    expect(page.locator(STAR)).to_be_visible(timeout=30000)


def test_the_toggle_is_the_builders_and_it_moves(page, api) -> None:
    """**End to end through the control somebody actually uses**, rather than
    through a document a fixture wrote. The two fixtures above prove the reader
    works on documents; this proves the checkbox writes the value the reader
    reads — which is the seam a `data-testid` on an input can hide.
    """
    mod = favourite_module(api, "Toggle moves", {"title": "Switchable"})
    open_builder(page, mod)
    select_node(page, "Header")

    box = page.get_by_test_id("header-allow-favourite")
    expect(box).to_be_visible(timeout=30000)
    expect(box).to_be_checked()
    box.uncheck()
    save(page)
    publish(mod)

    open_viewer(page, mod)
    expect(page.locator(STAR)).to_have_count(0)

    open_builder(page, mod)
    select_node(page, "Header")
    page.get_by_test_id("header-allow-favourite").check()
    save(page)
    publish(mod)

    open_viewer(page, mod)
    expect(page.locator(STAR)).to_be_visible(timeout=30000)


def test_the_hint_says_which_star_the_toggle_is_about(page, api) -> None:
    """§337: the control names the surface it governs. A builder who unticks it
    and sees their own star still in the application header would reasonably
    conclude the setting is broken."""
    mod = favourite_module(api, "Toggle hint", {"title": "Hinted"})
    open_builder(page, mod)
    select_node(page, "Header")
    panel = page.locator(".canvas-settings")
    expect(panel).to_contain_text("published module", timeout=30000)
