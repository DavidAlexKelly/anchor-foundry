"""p.76's recompute behaviours and p.85's Recompute event (parity
`workshop.md` §3.5, §4.2; Foundry p.76, p.85).

> "**Only when triggered by an event**: The variable value is recomputed only
> when explicitly triggered by a recompute {variable name} event.
>
> **On module load, and when triggered by an event**: The variable value is
> recomputed when the module is initially loaded, and when explicitly triggered
> by a recompute {variable name} event." (p.76)

The bookkeeping — which variables hold, what goes on the wire, what comes back
into memory — is checked in `apps/web/src/components/canvas/recompute.test.ts`,
and the evaluator's half in `test_workshop_variables.py`. What needs a browser
is the **loop between them**: the browser sends what it remembers, the server
answers with it, the browser remembers the answer. Neither side's tests can see
that loop, and the failure it produces has no error — a variable that is
silently one resolve out of date.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import open_module


def module_with(api, name: str, behaviour: str):
    """A control writing `v_in`, a derived `v_out` that copies it, and a button
    that recomputes `v_out`.

    `concat` of one input is the simplest derivation that is visibly a
    *function* of something: when `v_out` stops following `v_in`, it is holding.
    """
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({
            "ctl": {"resolvedName": "CanvasParameterControl",
                    "props": {"name": "v_in", "label": "In", "control": "text"}},
            "btn": {"resolvedName": "CanvasButton", "props": {"label": "Recompute"}},
            "readout": {"resolvedName": "CanvasText",
                        "props": {"tag": "p", "text": "IN={{v_in}} OUT={{v_out}}"}},
        }),
        "variables": {
            "v_in": {"id": "v_in", "kind": "string", "label": "In", "default": "one"},
            "v_out": {"id": "v_out", "kind": "string", "label": "Out",
                      "recompute": behaviour,
                      "derivation": {"transform": "concat", "inputs": ["v_in"]}},
        },
        "events": {
            "e_1": {"id": "e_1", "trigger": {"node": "btn", "on": "click"},
                    "effects": [{"type": "recompute", "config": {"variable": "v_out"}}]},
        },
    })
    return mod


def readout(page, text: str) -> None:
    """Wait for the readout to say exactly this — §189's ordering rule."""
    expect(page.get_by_text(text, exact=True)).to_be_visible(timeout=15000)


def test_on_load_and_event_computes_once_then_holds(page, api) -> None:
    """p.76's third option, both halves.

    It computes at load, so the reader sees a real value rather than a blank;
    and then it stops following its input, which is the whole of "holds".
    """
    mod = module_with(api, "Recompute on load", "on_load_and_event")
    open_module(page, mod)

    readout(page, "IN=one OUT=one")

    page.get_by_label("In").fill("two")
    # The input moved and the output did not. **This is the assertion the
    # feature exists for**, and it is a claim about something *not* happening -
    # so it waits for `IN=two` first, which proves a full resolve completed
    # with the new input and came back leaving the output alone.
    readout(page, "IN=two OUT=one")


def test_an_event_lets_it_recompute(page, api) -> None:
    """p.85's event, and the other half of "holds": it is not frozen, it is
    waiting."""
    mod = module_with(api, "Recompute event", "on_load_and_event")
    open_module(page, mod)

    readout(page, "IN=one OUT=one")
    page.get_by_label("In").fill("two")
    readout(page, "IN=two OUT=one")

    page.get_by_role("button", name="Recompute").click()
    readout(page, "IN=two OUT=two")


def test_it_holds_again_after_recomputing(page, api) -> None:
    """**The loop, which is the reason this needs a browser.**

    A recompute that forgot to re-remember would leave the variable recomputing
    on every resolve from then on — indistinguishable from Automatic, and
    invisible in any single-step test. So: recompute, change the input again,
    and check it has gone back to holding.
    """
    mod = module_with(api, "Recompute reholds", "on_load_and_event")
    open_module(page, mod)

    # §189's ordering rule, and this test is what taught it again: typing before
    # the first resolve lands means the browser has captured nothing yet, so
    # `v_out` is computed from "two" and the test sees `OUT=two` - a real
    # behaviour, but not the one under test.
    readout(page, "IN=one OUT=one")
    page.get_by_label("In").fill("two")
    readout(page, "IN=two OUT=one")
    page.get_by_role("button", name="Recompute").click()
    readout(page, "IN=two OUT=two")

    page.get_by_label("In").fill("three")
    readout(page, "IN=three OUT=two")


def test_only_on_event_has_no_value_until_an_event_fires(page, api) -> None:
    """p.76's second option, and the one place it differs from the third.

    "Recomputed **only** when explicitly triggered" — so at load it has never
    been computed, and computing it there would make the two options identical
    on the single occasion they are not.
    """
    mod = module_with(api, "Recompute only on event", "only_on_event")
    open_module(page, mod)

    # Empty, not "one". The interpolation of a null variable is the empty
    # string, so the readout says what it has: nothing yet.
    readout(page, "IN=one OUT=")

    page.get_by_role("button", name="Recompute").click()
    readout(page, "IN=one OUT=one")


def test_automatic_still_follows_its_input(page, api) -> None:
    """The control group, and the one that would catch a held value leaking
    onto a variable that never asked for one."""
    mod = Module(api, "Recompute automatic")
    mod.define({
        "format": 2,
        "layout": layout({
            "ctl": {"resolvedName": "CanvasParameterControl",
                    "props": {"name": "v_in", "label": "In", "control": "text"}},
            "readout": {"resolvedName": "CanvasText",
                        "props": {"tag": "p", "text": "IN={{v_in}} OUT={{v_out}}"}},
        }),
        "variables": {
            "v_in": {"id": "v_in", "kind": "string", "label": "In", "default": "one"},
            "v_out": {"id": "v_out", "kind": "string", "label": "Out",
                      "derivation": {"transform": "concat", "inputs": ["v_in"]}},
        },
        "events": {},
    })
    open_module(page, mod)

    readout(page, "IN=one OUT=one")
    page.get_by_label("In").fill("two")
    readout(page, "IN=two OUT=two")
