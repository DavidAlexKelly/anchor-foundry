"""p.85's Reset {variable} value (parity `workshop.md` §4.2; Foundry p.85).

> "Reset {variable name} value events will set the value of the chosen variable
> to its default value, which is the value configured in the variable
> definition. This option is offered for static variables." (p.85)

The ordering arithmetic — a Set and a Reset of one variable, whichever came
last winning — is checked directly in
`apps/web/src/components/canvas/events.test.ts`. What needs a browser is the
claim underneath the implementation: that **forgetting the viewer's value is
the same thing as restoring the definition's**. That is a statement about what
the server does with an absent value, and the only honest way to ask it is to
change a value, reset it, and look.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import open_module


def module_with(api, name: str):
    """A parameter control writing a variable, a readout showing it, and a
    button that resets it.

    The control is what makes this checkable: something has to *move the
    variable off its default* before a Reset can be seen to put it back.
    """
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({
            "ctl": {"resolvedName": "CanvasParameterControl",
                    "props": {"name": "v_word", "label": "Word", "control": "text"}},
            "btn": {"resolvedName": "CanvasButton", "props": {"label": "Reset"}},
            "readout": {"resolvedName": "CanvasText",
                        "props": {"tag": "p", "text": "WORD={{v_word}}"}},
        }),
        "variables": {
            "v_word": {"id": "v_word", "kind": "string", "label": "Word",
                       "default": "north"},
        },
        "events": {
            "e_1": {"id": "e_1", "trigger": {"node": "btn", "on": "click"},
                    "effects": [{"type": "reset_variable",
                                 "config": {"variable": "v_word"}}]},
        },
    })
    return mod


def readout(page, text: str) -> None:
    """Wait for the readout to say exactly this.

    The §189 ordering rule: variables resolve on the server, so an assertion
    made before the round trip is an assertion about a value on its way
    somewhere else.
    """
    expect(page.get_by_text(text, exact=True)).to_be_visible(timeout=15000)


def test_a_reset_puts_the_variable_back_to_its_definition(page, api) -> None:
    """p.85's sentence, end to end.

    **The implementation forgets the viewer's value rather than writing the
    default**, and this is the check that the two are the same thing: the
    server resolves an unbound static variable as `values.get(vid, default)`,
    so an absent value *is* the definition's. If that ever stopped being true
    this test would fail and the unit tests would not.
    """
    mod = module_with(api, "Reset basic")
    open_module(page, mod)

    readout(page, "WORD=north")

    box = page.get_by_label("Word")
    box.fill("south")
    readout(page, "WORD=south")

    page.get_by_role("button", name="Reset").click()
    readout(page, "WORD=north")


def test_a_reset_is_not_a_write_of_an_empty_value(page, api) -> None:
    """The failure the deletion exists to avoid.

    An implementation that "reset" by writing `""` — the obvious way to clear a
    control — would leave the readout empty rather than back at `north`, and
    would look correct in the builder for any variable whose default happens to
    be blank. Asserted as the *default* rather than as "not empty", so it
    cannot pass by writing some other value either.
    """
    mod = module_with(api, "Reset not empty")
    open_module(page, mod)

    readout(page, "WORD=north")
    page.get_by_label("Word").fill("south")
    readout(page, "WORD=south")

    page.get_by_role("button", name="Reset").click()
    # Not `WORD=` and not `WORD=south`.
    readout(page, "WORD=north")
    expect(page.get_by_text("WORD=", exact=True)).to_have_count(0)


def test_a_reset_after_a_set_in_the_same_click_wins(page, api) -> None:
    """p.80's configured order, driven through the real runtime rather than
    through `run` alone: the two effects are applied by *different*
    capabilities — one a write, one a deletion — and the later one has to be
    the one that survives the round trip."""
    mod = Module(api, "Reset ordering")
    mod.define({
        "format": 2,
        "layout": layout({
            "btn": {"resolvedName": "CanvasButton", "props": {"label": "Both"}},
            "readout": {"resolvedName": "CanvasText",
                        "props": {"tag": "p", "text": "WORD={{v_word}}"}},
        }),
        "variables": {
            "v_word": {"id": "v_word", "kind": "string", "label": "Word",
                       "default": "north"},
        },
        "events": {
            "e_1": {"id": "e_1", "trigger": {"node": "btn", "on": "click"},
                    "effects": [
                        {"type": "set_variable",
                         "config": {"variable": "v_word", "value": "south"}},
                        {"type": "reset_variable", "config": {"variable": "v_word"}},
                    ]},
        },
    })
    open_module(page, mod)

    readout(page, "WORD=north")
    page.get_by_role("button", name="Both").click()
    # The Set never reaches the server: the Reset that follows it discards the
    # pending write rather than racing it.
    readout(page, "WORD=north")
