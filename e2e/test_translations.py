"""Translations: a reader is served their own language (parity `workshop.md`
§9; Foundry p.207-211).

> "Viewers will then be presented with a translated view of the module in
> their browser's locale if the Workshop application has been translated into
> that language using this feature." (p.207)

Which strings are translatable, how a table is looked up and which language
wins are all values, and they are checked directly in
`apps/web/src/components/canvas/translatable.test.ts`. What needs a browser is
the sentence above: that a real Chromium asking for French, through a real
`Accept-Language`, gets French out of a real document — and that everybody
else, and every builder, does not.

**The tables are written through the API here**, which is also how a builder
writes them today: p.209's Translations tab is not built, and `workshop.md` §9
says so. What *is* built is everything a reader touches.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import _signed_in, open_builder, publish, save, viewer_url

FR = {
    "Case review": {"text": "Examen des dossiers"},
    "Open": {"text": "Ouvert"},
    "Draft": {"text": "Brouillon"},
    "Submit": {"text": "Envoyer"},
}


@pytest.fixture
def french_page(browser, token: str, request):
    """A reader whose browser asks for Canadian French.

    `fr-CA` rather than `fr`, because the interesting half of the lookup is
    the fallback: a module is translated into `fr` and a browser almost never
    asks for exactly that.
    """
    yield from _signed_in(browser, token, request, locale="fr-CA")


def translated_module(api, name: str, *, enabled: bool = True, languages=None) -> Module:
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({
            "h": {"resolvedName": "CanvasHeader", "isCanvas": True,
                  "props": {"title": "Case review"}, "nodes": []},
            # Collapsible, because that is the one arrangement in which a
            # section draws its own title - a plain section's title is a
            # builder-side label. Asserting on a string the product never
            # renders is how the first draft of this file passed nothing.
            "sec": {"resolvedName": "CanvasSection", "isCanvas": True,
                    "props": {"direction": "columns", "gap": 12, "title": "Open",
                              "collapsible": True},
                    "nodes": ["btn"]},
            # p.208's "Section header … and Tabs": several strings in one
            # comma-separated prop, each translated on its own.
            # `direction: "tabs"` and one child per tab: a section's tab strip
            # is drawn from its *children*, so an empty one has no tabs to
            # label and nothing for a translation to reach.
            "tabs": {"resolvedName": "CanvasSection", "isCanvas": True,
                     "props": {"direction": "tabs", "gap": 12,
                               "tabs": "Draft,Closed"},
                     "nodes": ["t1", "t2"]},
            "t1": {"resolvedName": "CanvasText", "parent": "tabs",
                   "props": {"tag": "p", "text": "First"}},
            "t2": {"resolvedName": "CanvasText", "parent": "tabs",
                   "props": {"tag": "p", "text": "Second"}},
            "btn": {"resolvedName": "CanvasButton", "parent": "sec",
                    "props": {"label": "Submit", "style": "primary"}},
        }),
        "variables": {},
        "events": {},
        "translations": {
            "enabled": enabled,
            "source_language": "en",
            "languages": {"fr": FR} if languages is None else languages,
        },
    })
    return mod


def test_a_french_reader_gets_french(french_page, api) -> None:
    """p.207's whole sentence, through a browser that really is asking for it."""
    mod = translated_module(api, "Translated fr")
    publish(mod)
    french_page.goto(viewer_url(mod))

    expect(french_page.get_by_text("Examen des dossiers")).to_be_visible()
    expect(french_page.get_by_text("Ouvert")).to_be_visible()
    expect(french_page.get_by_role("button", name="Envoyer")).to_be_visible()
    # One tab translated and the other not, from one prop. The pair is the
    # assertion: a whole-prop translation would have had to translate both or
    # neither.
    expect(french_page.get_by_role("tab", name="Brouillon")).to_be_visible()
    expect(french_page.get_by_role("tab", name="Closed")).to_be_visible()


def test_an_english_reader_gets_the_module_as_written(page, api) -> None:
    """The other half, and the one that fails if the table is applied to
    everybody. The default context asks for English."""
    mod = translated_module(api, "Translated en")
    publish(mod)
    page.goto(viewer_url(mod))

    expect(page.get_by_text("Case review")).to_be_visible()
    expect(page.get_by_text("Examen des dossiers")).to_have_count(0)


def test_the_browser_tab_is_translated_too(french_page, api) -> None:
    """p.208 makes the module header Title translatable, and the tab title is
    that title. A French module whose tab said English would be the one place
    the translation leaked — and it is a separate call site, which is exactly
    the kind that gets missed."""
    mod = translated_module(api, "Translated title")
    publish(mod)
    french_page.goto(viewer_url(mod))

    expect(french_page.get_by_text("Examen des dossiers")).to_be_visible()
    assert "Examen des dossiers" in french_page.title()


def test_the_switch_off_reaches_nobody(french_page, api) -> None:
    """p.208 makes Translations something a builder turns on. A module with a
    half-entered table and the switch off must serve the document as written —
    otherwise the switch is decoration and a work-in-progress translation is
    live the moment somebody types it."""
    mod = translated_module(api, "Translated off", enabled=False)
    publish(mod)
    french_page.goto(viewer_url(mod))

    expect(french_page.get_by_text("Case review")).to_be_visible()
    expect(french_page.get_by_text("Examen des dossiers")).to_have_count(0)


def test_a_language_the_module_does_not_have_falls_back(french_page, api) -> None:
    """A module translated only into German, read by a French browser. Not an
    error and not a blank: the document as written."""
    mod = translated_module(
        api, "Translated de",
        languages={"de": {"Case review": {"text": "Fallprüfung"}}},
    )
    publish(mod)
    french_page.goto(viewer_url(mod))

    expect(french_page.get_by_text("Case review")).to_be_visible()
    expect(french_page.get_by_text("Fallprüfung")).to_have_count(0)


def test_an_empty_translation_does_not_blank_the_widget(french_page, api) -> None:
    """A box a builder opened and did not fill. Serving it would empty the
    header, which reads as a broken module rather than an untranslated one
    (§214)."""
    mod = translated_module(
        api, "Translated empty",
        languages={"fr": {"Case review": {"text": ""}, "Submit": {"text": "Envoyer"}}},
    )
    publish(mod)
    french_page.goto(viewer_url(mod))

    # The one that *is* translated first, so this is a check about the empty
    # entry rather than about a page that has not rendered (§318).
    expect(french_page.get_by_role("button", name="Envoyer")).to_be_visible()
    expect(french_page.get_by_text("Case review")).to_be_visible()


def test_the_builder_sees_the_strings_it_is_editing(french_page, api) -> None:
    """p.211 gives edit mode its own preview, "by navigating to the
    Translations tab and selecting the configured language of choice" — an
    explicit act. An author editing a module in a French browser must see the
    English they are editing, or every string they touch would be replaced
    with its translation in the box they typed it in."""
    mod = translated_module(api, "Translated builder")
    open_builder(french_page, mod)

    # The rendered header, named exactly (§337): the Layout tree lists the
    # same string, and a loose text match would pass on the tree row alone -
    # which is not the canvas and not what p.211 is about.
    expect(french_page.locator(".canvas-header-title")).to_have_text("Case review")
    expect(french_page.get_by_text("Examen des dossiers")).to_have_count(0)


def test_the_settings_panel_carries_p208s_switch(page, api) -> None:
    """p.208: "navigate to the Settings tab in edit mode and toggle on
    Translations in the Advanced functionalities section"."""
    mod = translated_module(api, "Translated switch", enabled=False)
    open_builder(page, mod)

    toggle = page.locator('[data-testid="translations-toggle"]')
    expect(toggle).not_to_be_checked()
    toggle.check()
    # It says what turning it on means, and how many languages there are to
    # mean it with — a switch reporting nothing is a switch nobody can tell
    # is doing anything.
    expect(page.locator('[data-testid="translations-state"]')).to_contain_text("1 language")


def test_the_switch_is_saved_with_the_document(page, api) -> None:
    """The tables translate strings that live in the layout, so they travel
    with it. A save that dropped them would make the toggle a delete button."""
    mod = translated_module(api, "Translated saved", enabled=False)
    open_builder(page, mod)
    page.locator('[data-testid="translations-toggle"]').check()
    save(page)

    stored = mod.definition()["translations"]
    assert stored["enabled"] is True
    # And the tables are still there, which is the half a toggle could
    # plausibly have eaten.
    assert stored["languages"]["fr"]["Open"]["text"] == "Ouvert"
