"""A module's overlay, from a keyboard (§1010).

It is drawn in the page and says `aria-modal`, which promises what a native
`<dialog>` does: focus goes into it, Tab stays in it, Escape closes it, and
closing it puts focus back. None of that was true - Tab from the overlay's
Close went on into the page behind it, which a sighted keyboard user could
not see and a screen reader user could not know about.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import open_module


def overlay_module(api) -> Module:
    mod = Module(api, "Modal focus")
    mod.define({
        "format": 2,
        "layout": layout({
            "open": {"resolvedName": "CanvasButton", "props": {"label": "Open detail"}},
            "behind": {"resolvedName": "CanvasButton", "props": {"label": "Behind"}},
            "ov": {"resolvedName": "CanvasOverlay", "props": {"title": "Detail"},
                   "isCanvas": True, "nodes": ["inside"]},
            "inside": {"resolvedName": "CanvasButton", "props": {"label": "Inside"},
                       "parent": "ov"},
        }),
        "variables": {},
        "events": {
            "e_open": {"id": "e_open", "trigger": {"node": "open", "on": "click"},
                       "effects": [{"type": "navigate", "config": {"page": "ov"}}]},
        },
    })
    return mod


def focused(page) -> str:
    return page.evaluate("""() => {
        const el = document.activeElement;
        const box = el && el.closest('[role=dialog]');
        return (box ? 'in:' : 'out:') + (el.getAttribute('aria-label') || el.textContent || '').trim();
    }""")


def test_the_overlay_takes_focus_keeps_it_and_gives_it_back(page, api) -> None:
    open_module(page, overlay_module(api))
    opener = page.get_by_role("button", name="Open detail")
    opener.focus()
    page.keyboard.press("Enter")
    dialog = page.get_by_role("dialog", name="Detail")
    expect(dialog).to_be_visible()

    # Into it, at the box itself, so its name is what is read first.
    expect(dialog).to_be_focused()

    # Round its own two controls and no further, either way.
    seen = []
    for _ in range(5):
        page.keyboard.press("Tab")
        seen.append(focused(page))
    assert all(s.startswith("in:") for s in seen), seen
    assert {"in:Close", "in:Inside"} <= set(seen), seen
    page.keyboard.press("Shift+Tab")
    assert focused(page).startswith("in:")

    # Escape closes it, and focus is back on what opened it.
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    expect(opener).to_be_focused()


def test_its_close_button_gives_focus_back_too(page, api) -> None:
    open_module(page, overlay_module(api))
    opener = page.get_by_role("button", name="Open detail")
    opener.focus()
    page.keyboard.press("Enter")
    dialog = page.get_by_role("dialog", name="Detail")
    dialog.get_by_role("button", name="Close").focus()
    page.keyboard.press("Enter")
    expect(dialog).to_have_count(0)
    expect(opener).to_be_focused()
