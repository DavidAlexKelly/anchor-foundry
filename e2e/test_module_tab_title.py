"""The browser tab name (parity `workshop.md` §1.1).

    "Set a title for the header. This title will also be used to set the
     browser tab or Carbon workspace tab name. If a title is not set, the
     Workshop module resource name will be used instead."
     (docs/pal/foundry_workshop.pdf p.47)

Two claims, and the second is the one that needs a browser: `moduleTitle` is
unit-tested in `apps/web/src/components/canvas/module-title.test.ts`, so what is
left to check is that the *tab* changes at all - a pure function nobody called
would pass every unit test it has.

The fallback case is checked with a header that *has* no title rather than a
module with no header, because the header is where a title would come from and
"title left blank" is the state a builder actually reaches.
"""
from __future__ import annotations

import pytest

from api import Module, layout
from conftest import eventually, open_builder, open_module


def title_module(api, name: str, title: str) -> Module:
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({
            "hdr": {"resolvedName": "CanvasHeader", "props": {"title": title}},
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
    return mod


@pytest.fixture(scope="module")
def titled(api):
    return title_module(api, "Tab titled", "Fleet status")


@pytest.fixture(scope="module")
def untitled(api):
    return title_module(api, "Tab untitled", "")


def tab(page, expected: str) -> None:
    eventually(page.title, lambda t: t == expected, what=f"the browser tab to read {expected!r}")


def test_the_header_title_becomes_the_tab_name(page, titled):
    open_builder(page, titled)
    tab(page, "Fleet status")


def test_a_module_with_no_title_falls_back_to_its_resource_name(page, untitled):
    """The half of p.47 a builder hits by accident. The resource name is what
    `Module.define` created the app as."""
    open_builder(page, untitled)
    tab(page, f"App {untitled.tag}")


def test_the_tab_name_survives_preview(page, titled):
    """Preview swaps the builder chrome for the rendered module. The title is
    the module's, not the builder's, so it does not go with the chrome."""
    open_module(page, titled)
    tab(page, "Fleet status")


def test_leaving_the_module_puts_the_platform_title_back(page, titled):
    """A module must not strand its name in the tab of the next page.

    Today this passes because Next re-applies the route's metadata on a
    client-side navigation, not because `useModuleTitle` restores anything — a
    mutation removing its cleanup left this green, and the cleanup was deleted
    rather than kept unfalsifiable. The check stays: it is what fails if that
    assumption stops holding, which is exactly when we would want to know.
    """
    open_builder(page, titled)
    tab(page, "Fleet status")

    # The shell's breadcrumb, which is a client-side navigation - the case the
    # cleanup exists for. A full page load would put the title back on its own
    # and prove nothing.
    page.locator(".app-crumbs a").first.click()
    eventually(page.title, lambda t: t != "Fleet status",
               what="the tab to stop naming the module we left")
