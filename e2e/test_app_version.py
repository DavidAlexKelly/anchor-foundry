"""p.166's `/dev/`: the last saved version, in the browser (§314).

    "For testing purposes, you can change the `/latest/` to `/dev/` in the URL,
     and the link will now redirect to the last saved version of the Workshop
     application instead of the last published version." (p.166)

The refusal and the two reads are in `apps/api/tests/test_canvas.py`, and the
wording in `apps/web/src/lib/app-version.test.ts`. What needs a browser is
p.166's actual claim: **edit the URL by hand, and see the other version** —
which is only a claim about a URL, and therefore only checkable by using one.

`workshop.md` puts it well: "one route, and save-versus-publish becomes
checkable by a human". Until now the distinction `published_version` exists to
draw had no screen that could show both sides of it.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually


def layout(nodes: dict) -> dict:
    from test_workshop_application import layout as build  # reuse the builder

    return build(nodes)


def a_module(api, name: str, text: str) -> Module:
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({
            "t1": {"resolvedName": "CanvasText",
                   "props": {"tag": "p", "text": text}},
        }),
        "variables": {},
        "events": {},
    })
    return mod


def save(mod: Module, text: str) -> None:
    mod.define({
        "format": 2,
        "layout": layout({
            "t1": {"resolvedName": "CanvasText",
                   "props": {"tag": "p", "text": text}},
        }),
        "variables": {},
        "events": {},
    })


def publish(mod: Module) -> None:
    mod.api.call(
        "PUT", f"{mod.base}/canvas-apps/{mod.app_id}/publish", {"scope": "workspace"},
    )


def viewer_url(mod: Module, *, saved: bool) -> str:
    base = f"{WEB_BASE}/{mod.workspace_slug}/apps/{mod.app_id}"
    return f"{base}?version=saved" if saved else base


def test_the_published_url_shows_the_published_version(page, api) -> None:
    """The half that already worked, asserted so the other half means something.

    Without this, "the saved URL shows the saved version" is satisfied by a
    page that shows the saved version everywhere.
    """
    mod = a_module(api, "Version latest", "as published")
    publish(mod)
    save(mod, "still being worked on")

    page.goto(viewer_url(mod, saved=False))
    expect(page.get_by_text("as published")).to_be_visible(timeout=30000)
    expect(page.get_by_text("still being worked on")).to_have_count(0)
    expect(page.get_by_test_id("version-note")).to_have_count(0)


def test_editing_the_url_shows_the_last_saved_version(page, api) -> None:
    """**p.166's whole sentence**, and the only place it can be checked.

    Reached by `goto` rather than by a control, because the claim is about a
    URL somebody types — a button would prove something else works.
    """
    mod = a_module(api, "Version saved", "as published")
    publish(mod)
    save(mod, "still being worked on")

    page.goto(viewer_url(mod, saved=True))
    expect(page.get_by_text("still being worked on")).to_be_visible(timeout=30000)
    expect(page.get_by_text("as published")).to_have_count(0)


def test_the_saved_view_says_it_is_not_what_others_see(page, api) -> None:
    """p.166 calls this "for testing purposes".

    Somebody who arrived on a hand-edited link needs to know what they are
    looking at is not what their colleagues have — and how far ahead of it,
    which is the sentence a builder actually wants.
    """
    mod = a_module(api, "Version note", "as published")
    publish(mod)
    save(mod, "one")
    save(mod, "two")

    page.goto(viewer_url(mod, saved=True))
    note = page.get_by_test_id("version-note")
    expect(note).to_be_visible(timeout=30000)
    expect(note).to_contain_text("Other people see")
    expect(note).to_contain_text("2 saves ahead")


def test_an_unrecognised_version_shows_the_published_one(page, api) -> None:
    """A mistyped parameter must not be a way into unpublished work.

    The failure mode of guessing the other way is showing a draft to somebody
    who typed a character wrong — so `?version=dev`, which is what p.166's own
    wording would tempt somebody into, gets the published module.
    """
    mod = a_module(api, "Version typo", "as published")
    publish(mod)
    save(mod, "still being worked on")

    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/apps/{mod.app_id}?version=dev")
    expect(page.get_by_text("as published")).to_be_visible(timeout=30000)
    expect(page.get_by_text("still being worked on")).to_have_count(0)


def test_an_app_that_has_never_been_published_has_no_count_to_report(page, api) -> None:
    """"1 save ahead" of nothing is arithmetic rather than information.

    The banner still appears — what is on screen is still not what anybody else
    can see — but it stops short of a number it cannot mean.
    """
    mod = a_module(api, "Version unpublished", "never published")

    page.goto(viewer_url(mod, saved=True))
    note = page.get_by_test_id("version-note")
    expect(note).to_be_visible(timeout=30000)
    expect(note).to_contain_text("Other people see")
    expect(note).not_to_contain_text("ahead of what is published")
