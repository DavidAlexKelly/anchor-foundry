"""p.209-210's Translations tab (parity `workshop.md` §9; Foundry p.209-210).

> "On selection of a target language, each translatable string detected within
> the module will be displayed with an input field to manually enter
> translations." (p.209)

> "Once satisfied with the translations, the translations may then be Marked
> as complete… Any new or modified strings detected in the module, for
> example, on the addition of a new button or on edit of a section header's
> title, will appear in the To translate section, separating them from the
> already-translated and reviewed strings." (p.210)

Which strings are found, and which of them are still untranslated, are values
checked in `apps/web/src/components/canvas/translatable.test.ts` (§399). What
needs a browser is the tab: that it lists the module being edited, that typing
a translation moves the string between p.210's two sections, that the reviewed
tick survives a save, and that a reader then gets what was typed — which is
the whole point and the one thing neither half can show alone.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import _signed_in, open_builder, publish, save, viewer_url


@pytest.fixture
def french_page(browser, token: str, request):
    yield from _signed_in(browser, token, request, locale="fr-CA")


def module_with_strings(api, name: str, *, translations=None) -> Module:
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({
            "h": {"resolvedName": "CanvasHeader", "isCanvas": True,
                  "props": {"title": "Case review"}, "nodes": []},
            "sec": {"resolvedName": "CanvasSection", "isCanvas": True,
                    "props": {"direction": "columns", "gap": 12}, "nodes": ["btn"]},
            "btn": {"resolvedName": "CanvasButton", "parent": "sec",
                    "props": {"label": "Submit", "style": "primary"}},
        }),
        "variables": {},
        "events": {},
        **({"translations": translations} if translations else {}),
    })
    return mod


def open_tab(page, mod):
    open_builder(page, mod)
    page.get_by_role("button", name="Translations (0)", exact=True).click()


def test_the_tab_offers_a_box_per_string_once_a_language_exists(page, api) -> None:
    """p.209: "each translatable string detected within the module will be
    displayed with an input field"."""
    mod = module_with_strings(api, "Tab strings")
    open_tab(page, mod)

    # Nothing to type into until there is a language to type into.
    expect(page.get_by_test_id("tr-no-language")).to_be_visible()
    page.get_by_test_id("tr-add-language").fill("fr")
    page.get_by_test_id("tr-add").click()

    expect(page.get_by_test_id("tr-input-Case review")).to_be_visible()
    expect(page.get_by_test_id("tr-input-Submit")).to_be_visible()
    # Every string starts in To translate, which is p.210's whole point.
    expect(page.get_by_test_id("tr-pending").locator("li")).to_have_count(2)


def test_typing_a_translation_moves_it_out_of_to_translate(page, api) -> None:
    """p.210 separates "the already-translated and reviewed strings" from what
    still needs doing, and nothing has to notice the change: a string is in To
    translate exactly when the table has nothing for it."""
    mod = module_with_strings(api, "Tab moves")
    open_tab(page, mod)
    page.get_by_test_id("tr-add-language").fill("fr")
    page.get_by_test_id("tr-add").click()

    page.get_by_test_id("tr-input-Submit").fill("Envoyer")
    expect(page.get_by_test_id("tr-pending").locator("li")).to_have_count(1)
    expect(page.get_by_test_id("tr-done").locator("li")).to_have_count(1)
    expect(page.get_by_test_id("tr-done")).to_contain_text("Submit")


def test_clearing_the_box_removes_the_entry_from_the_document(page, api) -> None:
    """An empty entry is not served (§399), so storing one would be a row that
    looks translated in the document and reads as English on screen.

    **Asserted on the saved document, not on the panel**, and a mutant is why.
    Storing `{"text": ""}` instead of deleting the key leaves the two sections
    looking exactly as they do here - `say()` falls back to the source for a
    blank entry, so the string is in To translate either way. The screen
    cannot tell these apart; only the document can.
    """
    mod = module_with_strings(api, "Tab clears")
    open_tab(page, mod)
    page.get_by_test_id("tr-add-language").fill("fr")
    page.get_by_test_id("tr-add").click()
    page.get_by_test_id("tr-input-Submit").fill("Envoyer")
    expect(page.get_by_test_id("tr-done").locator("li")).to_have_count(1)

    page.get_by_test_id("tr-input-Submit").fill("")
    expect(page.get_by_test_id("tr-pending").locator("li")).to_have_count(2)
    expect(page.get_by_test_id("tr-done")).to_have_count(0)

    save(page)
    assert mod.definition()["translations"]["languages"]["fr"] == {}


def test_a_translation_lands_in_the_language_that_is_selected(page, api) -> None:
    """Two languages, and typing into the second must not write the first.

    **Which language is selected is the whole test, and it has to be the one
    the picker does not list first.** The picker sorts its tags, so choosing
    `de` out of `{de, fr}` would leave "the selected language" and "the first
    language" the same string again - the first attempt at this test did
    exactly that and a mutant walked straight through it. `fr` is second, so
    a panel that wrote to the first would write German's table.
    """
    mod = module_with_strings(api, "Tab two languages", translations={
        "enabled": True, "source_language": "en",
        "languages": {"fr": {}, "de": {}},
    })
    open_builder(page, mod)
    page.get_by_role("button", name="Translations (2)", exact=True).click()

    page.get_by_test_id("tr-language").select_option("fr")
    page.get_by_test_id("tr-input-Submit").fill("Envoyer")
    save(page)

    stored = mod.definition()["translations"]["languages"]
    assert stored["fr"] == {"Submit": {"text": "Envoyer"}}
    # And German is untouched. Writing to both would pass a check that only
    # looked at French.
    assert stored["de"] == {}


def test_an_edited_string_reappears_in_to_translate(page, api) -> None:
    """p.210: "on edit of a section header's title, will appear in the To
    translate section". Nothing watches for the edit — the table is keyed by
    the source text, so the edited string is a key nothing has an entry for."""
    mod = module_with_strings(api, "Tab edited", translations={
        "enabled": True, "source_language": "en",
        "languages": {"fr": {"Submit": {"text": "Envoyer"}}},
    })
    open_builder(page, mod)
    page.get_by_role("button", name="Translations (1)", exact=True).click()
    expect(page.get_by_test_id("tr-done")).to_contain_text("Submit")

    # Rename the button through the builder, the way an author would.
    # Selected from the Layout tree rather than by clicking the canvas: the
    # tree row and the button itself both answer to "Submit", and §337 says
    # name the control rather than its neighbourhood. Then back to the Widget
    # tab, which is where a widget's settings are.
    page.get_by_role("button", name="Button Submit").click()
    page.get_by_role("button", name="Widget", exact=True).click()
    page.get_by_test_id("button-label").fill("Send it")
    page.get_by_role("button", name="Translations (1)", exact=True).click()

    expect(page.get_by_test_id("tr-pending")).to_contain_text("Send it")
    # And the old translation is kept, out of the way rather than deleted:
    # an edit that is undone should not have cost its translations.
    expect(page.get_by_test_id("tr-stale")).to_contain_text("Submit")


def test_marking_complete_is_saved_and_a_reader_gets_the_translation(
    page, french_page, api,
) -> None:
    """The whole loop, which is the only assertion that covers the seam: type
    a translation in the tab, tick p.210's Mark as complete, save, publish —
    and a French browser gets it.

    Both halves matter. The tick alone could be stored and nothing served; a
    served translation alone would not show that p.210's flag survives the
    round trip.
    """
    mod = module_with_strings(api, "Tab loop", translations={
        "enabled": True, "source_language": "en", "languages": {"fr": {}},
    })
    open_builder(page, mod)
    page.get_by_role("button", name="Translations (1)", exact=True).click()
    page.get_by_test_id("tr-input-Case review").fill("Examen des dossiers")
    page.get_by_test_id("tr-reviewed-Case review").check()
    save(page)

    stored = mod.definition()["translations"]["languages"]["fr"]["Case review"]
    assert stored == {"text": "Examen des dossiers", "reviewed": True}

    publish(mod)
    french_page.goto(viewer_url(mod))
    expect(french_page.get_by_text("Examen des dossiers")).to_be_visible()


def test_the_tick_is_out_of_reach_until_there_is_something_to_tick(page, api) -> None:
    """Marking an empty box as reviewed would record that somebody checked a
    translation that does not exist."""
    mod = module_with_strings(api, "Tab tick")
    open_tab(page, mod)
    page.get_by_test_id("tr-add-language").fill("fr")
    page.get_by_test_id("tr-add").click()

    expect(page.get_by_test_id("tr-reviewed-Submit")).to_be_disabled()
    page.get_by_test_id("tr-input-Submit").fill("Envoyer")
    expect(page.get_by_test_id("tr-reviewed-Submit")).to_be_enabled()


def test_the_tab_warns_when_the_switch_is_off(page, api) -> None:
    """Somebody has just spent ten minutes typing translations nobody is being
    served. Saying so here costs a line; not saying it costs the ten minutes
    twice (§214)."""
    mod = module_with_strings(api, "Tab off", translations={
        "enabled": False, "languages": {"fr": {"Submit": {"text": "Envoyer"}}},
    })
    open_builder(page, mod)
    page.get_by_role("button", name="Translations (1)", exact=True).click()

    expect(page.get_by_test_id("tr-off")).to_contain_text("switched off")
