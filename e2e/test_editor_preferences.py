"""p.20's personal editor preferences (§432; `code-repositories` p.20).

    "In the Settings tab, code authors can configure their personal editor
     preferences and repository administrators can control the repository's
     behavior and policies."

The rules are in `apps/web/src/lib/editor-preferences.test.ts`. What needs a
browser is the part no pure function can hold:

  * that a preference set on the Settings tab reaches *Monaco*, which is the
    only thing that makes it a preference rather than a stored number;
  * that it survives a reload, because a setting that does not is a control
    that looks like it works (§214);
  * and that p.20's two halves are told apart on the screen — the personal one
    says it is this browser's, the administrative one says it is the
    project's.
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


def commit(mod: Module, repo: dict, files: dict[str, str]) -> dict:
    return mod.api.call(
        "POST", f"{mod.base}/repositories/{repo['id']}/commits",
        {"branch": "main", "files": files, "message": "a change"},
    )


def a_repository(api, name: str) -> dict:
    mod = project(api, name)
    repo = repository(mod, f"Transforms {mod.tag}")
    commit(mod, repo, {
        "src/a.sql": f"-- output: d_{uuid.uuid4().hex[:6]}\nSELECT 1 AS id\n",
    })
    return repo


def open_settings(page, repo: dict) -> None:
    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=settings")
    expect(page.get_by_test_id("editor-preferences")).to_be_visible(timeout=30000)


def open_editor(page, repo: dict) -> None:
    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=files&file=src/a.sql")
    expect(page.locator(".code-editor-loading")).to_have_count(0, timeout=30000)
    expect(page.locator(".view-lines").first).to_be_visible(timeout=30000)


def editor_font_size(page) -> str:
    """What Monaco is actually rendering at.

    **Read off the rendered lines, not off the preference.** A test that
    checked the `<select>` would be checking that a dropdown remembers its own
    value, which is not the feature.
    """
    return page.locator(".view-lines").first.evaluate(
        "el => getComputedStyle(el).fontSize"
    )


def test_a_font_size_reaches_the_editor(page, api) -> None:
    """**The unit, in one setting.** A preference nothing reads is a number in
    a browser's storage."""
    repo = a_repository(api, "Prefs font")

    open_editor(page, repo)
    before = editor_font_size(page)

    open_settings(page, repo)
    page.get_by_test_id("pref-font-size").select_option("18")

    open_editor(page, repo)
    eventually(lambda: editor_font_size(page), lambda size: size == "18px",
               what="Monaco to render at the size that was chosen")
    assert before != "18px"


def test_a_preference_survives_a_reload(page, api) -> None:
    """A setting that is forgotten on reload is a control that looks like it
    works, which is worse than one that is absent (§214)."""
    repo = a_repository(api, "Prefs reload")

    open_settings(page, repo)
    page.get_by_test_id("pref-font-size").select_option("16")
    page.get_by_test_id("pref-minimap").click()

    page.reload()
    expect(page.get_by_test_id("pref-font-size")).to_have_value("16", timeout=30000)
    expect(page.get_by_test_id("pref-minimap")).to_be_checked()


def minimap_width(page) -> int:
    """**Its width, not its presence.** Monaco renders the minimap container
    either way and gives it no width when it is off, so a test that counted
    elements would find one whatever the preference said."""
    return page.evaluate(
        "() => { const m = document.querySelector('.minimap');"
        " return m ? Math.round(m.getBoundingClientRect().width) : 0; }"
    )


def test_the_minimap_is_a_preference_rather_than_a_decision(page, api) -> None:
    """The editor had `minimap: { enabled: false }` written into it. p.20 makes
    that somebody's choice rather than this file's."""
    repo = a_repository(api, "Prefs minimap")

    open_editor(page, repo)
    eventually(lambda: minimap_width(page), lambda w: w == 0,
               what="no minimap by default")

    open_settings(page, repo)
    page.get_by_test_id("pref-minimap").click()

    open_editor(page, repo)
    eventually(lambda: minimap_width(page), lambda w: w > 0,
               what="the minimap to appear once it is asked for")


def test_reset_puts_everything_back(page, api) -> None:
    repo = a_repository(api, "Prefs reset")

    open_settings(page, repo)
    # Nothing to reset yet, and the button says so rather than disappearing.
    expect(page.get_by_test_id("pref-reset")).to_be_disabled()

    page.get_by_test_id("pref-font-size").select_option("18")
    page.get_by_test_id("pref-tab-size").select_option("8")
    page.get_by_test_id("pref-word-wrap").click()
    expect(page.get_by_test_id("pref-reset")).to_be_enabled()

    page.get_by_test_id("pref-reset").click()
    expect(page.get_by_test_id("pref-font-size")).to_have_value("12.5")
    expect(page.get_by_test_id("pref-tab-size")).to_have_value("2")
    expect(page.get_by_test_id("pref-word-wrap")).not_to_be_checked()
    expect(page.get_by_test_id("pref-reset")).to_be_disabled()

    # And it is the stored value that was reset, not just the controls.
    page.reload()
    expect(page.get_by_test_id("pref-font-size")).to_have_value("12.5", timeout=30000)


def test_the_two_kinds_of_setting_say_which_they_are(page, api) -> None:
    """p.20 divides this tab, and the tab has to divide too.

    A personal preference and a governance setting under one heading is how
    somebody comes to think their font size is everybody's business — or, the
    way round that matters, that the review gate is only theirs.
    """
    repo = a_repository(api, "Prefs scope")

    open_settings(page, repo)
    personal = page.get_by_test_id("editor-preferences-scope")
    expect(personal).to_contain_text("browser")
    expect(personal).to_contain_text("account")

    expect(page.get_by_test_id("settings-admin-scope")).to_contain_text("project")


def test_a_broken_stored_value_does_not_lose_the_others(page, api) -> None:
    """**What a hand-edited or out-of-date storage entry does.**

    The rule is proved in the unit tests; this is the browser end of it,
    because the reader lives here and a page that threw on a bad string would
    take the Settings tab with it.
    """
    repo = a_repository(api, "Prefs broken")

    open_settings(page, repo)
    page.evaluate(
        "() => localStorage.setItem('anchor.editor.preferences',"
        " '{\"fontSize\":\"huge\",\"tabSize\":4}')"
    )
    page.reload()

    expect(page.get_by_test_id("editor-preferences")).to_be_visible(timeout=30000)
    # The unreadable one falls back; the readable one survives beside it.
    expect(page.get_by_test_id("pref-font-size")).to_have_value("12.5")
    expect(page.get_by_test_id("pref-tab-size")).to_have_value("4")
