"""p.165's **Open Workshop module** event (parity `workshop.md` §4, §5).

> "The Open Workshop module event can be used to avoid manually creating a URL,
> as described below. The selected module's interface will appear, allowing
> variable values to be passed from the current module to the chosen module's
> interface variables. When the event is called, the URL uses the current value
> to open the selected module." (p.165)

**The sentence that sizes this unit is "avoid manually creating a URL".** p.165
spells the manual form out immediately below — `?externalId=value` per interface
variable — and §152 already reads it. So the event is that URL built from a
mapping rather than by hand, and the thing worth checking in a browser is that
the two halves agree: the link this event builds must be one `seedFromQuery`
understands.

`interface-query.test.ts` holds which values go in it. What needs a browser is
the rest of the sentence: a new tab (p.90), pointed at the right module, whose
variables arrive seeded.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder, open_module, settled


def target_module(api, name: str) -> Module:
    """A module with one interface variable and a readout of it.

    `external_id` and `interface` are what make a variable part of an interface
    (§116), and they are also exactly what a URL parameter names (§152) — which
    is why one mechanism serves both.
    """
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({
            "readout": {"resolvedName": "CanvasText",
                        "props": {"tag": "p", "text": "REGION={{v_region}}"}},
        }),
        "variables": {
            "v_region": {
                "id": "v_region", "kind": "string", "label": "Region",
                "default": "unset", "external_id": "region", "interface": True,
            },
        },
        "events": {},
    })
    return mod


def source_module(api, name: str, target: Module, *, values=None) -> Module:
    """A module with a button that opens `target`, passing its own variable.

    **`beside=target`, and it is not incidental.** The event itself works across
    projects — a module opens at `/r/{id}`, which names no project — but the
    *panel* lists this project's modules, the same scope the embed widget uses.
    A fixture in two projects tests the event and silently skips the panel.
    """
    mod = Module(api, name, beside=target)
    mod.define({
        "format": 2,
        "layout": layout({
            "ctl": {"resolvedName": "CanvasParameterControl",
                    "props": {"name": "v_pick", "label": "Pick", "control": "text"}},
            "btn": {"resolvedName": "CanvasButton", "props": {"label": "Open it"}},
        }),
        "variables": {
            "v_pick": {"id": "v_pick", "kind": "string", "label": "Pick",
                       "default": "north"},
        },
        "events": {
            "e_1": {
                "id": "e_1", "trigger": {"node": "btn", "on": "click"},
                "effects": [{
                    "type": "open_module",
                    "config": {
                        "module": target.resource_id,
                        "values": {"region": "v_pick"} if values is None else values,
                    },
                }],
            },
        },
    })
    return mod


def viewing(tab):
    """The opened tab, switched to Preview.

    **An editor gets the builder at a module's URL**, which is what every link
    to a module does here and not something this event should change: p.165's
    own instructions for the manual URL say "make sure to be in view mode", and
    view mode is what a *viewer* gets at that same address. So the tab is right
    and the test is the thing that has to say which half it is asking about —
    the builder does not interpolate `{{...}}`, so a readout is only readable
    in Preview.
    """
    preview = tab.get_by_role("button", name="Preview", exact=True)
    expect(preview).to_be_visible(timeout=30000)
    preview.click()
    return tab


def test_the_event_opens_the_module_with_the_value_in_its_url(page, api) -> None:
    """p.165's whole sentence, end to end.

    **Read in the opened tab, not in the URL.** A link with the right query
    string is this unit agreeing with itself; what p.165 promises is that the
    target opens *with that state*, which only the target's own readout can say.
    """
    target = target_module(api, "Open target")
    source = source_module(api, "Open source", target)
    open_module(page, source)
    settled(page)

    with page.context.expect_page() as opened:
        page.get_by_role("button", name="Open it").click()
    tab = opened.value
    tab.wait_for_load_state()

    # p.90: these events open the resource "in a new browser tab".
    assert tab != page
    assert f"/r/{target.resource_id}" in tab.url, tab.url
    expect(viewing(tab).get_by_text("REGION=north", exact=True)).to_be_visible(
        timeout=30000)


def test_the_value_passed_is_the_one_on_screen_now(page, api) -> None:
    """p.165: "the URL uses the **current** value".

    Not the default the source declares — the value the reader has put there,
    which is the difference between a link and a bookmark. The default is
    `north`, so typing something else is what makes this assertion mean
    anything.
    """
    target = target_module(api, "Open target current")
    source = source_module(api, "Open source current", target)
    open_module(page, source)
    settled(page)
    page.get_by_label("Pick").fill("south")

    with page.context.expect_page() as opened:
        page.get_by_role("button", name="Open it").click()
    tab = opened.value
    tab.wait_for_load_state()
    assert "region=south" in tab.url, tab.url
    expect(viewing(tab).get_by_text("REGION=south", exact=True)).to_be_visible(
        timeout=30000)


def test_a_module_opened_with_nothing_keeps_its_own_default(page, api) -> None:
    """**The reason an empty value is left out of the URL rather than sent
    blank.** p.128's precedence rule is that a mapped value wins over the
    child's own definition — so a parameter carrying an empty string would win,
    and the target would show nothing where it declares `unset`.
    """
    target = target_module(api, "Open target default")
    source = source_module(api, "Open source default", target, values={})
    open_module(page, source)
    settled(page)

    with page.context.expect_page() as opened:
        page.get_by_role("button", name="Open it").click()
    tab = opened.value
    tab.wait_for_load_state()
    assert "region=" not in tab.url, tab.url
    expect(viewing(tab).get_by_text("REGION=unset", exact=True)).to_be_visible(
        timeout=30000)


def test_the_panel_offers_the_target_s_interface_and_not_this_module_s(
    page, api
) -> None:
    """p.165: "The selected module's interface will appear."

    **The one question about an event that this module's own document cannot
    answer**, which is why the panel fetches the target: the server validates
    that each mapped value names a variable *this* module declares and
    deliberately not that the target declares the external ID, because that
    lives in the target's document.

    The source's own variable is called `Pick` and the target's is `Region`, so
    a panel listing the wrong module's interface has something to be wrong
    about.
    """
    target = target_module(api, "Open target panel")
    source = source_module(api, "Open source panel", target)
    open_builder(page, source)
    settled(page)
    page.get_by_role("button", name="Events (1)").click()
    page.get_by_role("button", name="Button · Open it Clicked · 1 effect").click()

    expect(page.get_by_test_id("effect-open-module")).to_have_value(
        target.resource_id
    )
    block = page.get_by_test_id("effect-open-module-interface")
    # One row, for the target's one interface variable — keyed by its external
    # ID, and holding the source variable it was mapped to.
    picker = block.locator("[data-external-id='region']")
    expect(picker).to_have_value("v_pick")
    expect(block.locator("[data-external-id='pick']")).to_have_count(0)


def test_a_module_cannot_open_itself(page, api) -> None:
    """A module that opens itself in a new tab is a loop a builder can make by
    accident and cannot see until they click it, so it is not offered."""
    target = target_module(api, "Open target self")
    source = source_module(api, "Open source self", target)
    open_builder(page, source)
    settled(page)
    page.get_by_role("button", name="Events (1)").click()
    page.get_by_role("button", name="Button · Open it Clicked · 1 effect").click()

    picker = page.get_by_test_id("effect-open-module")
    values = picker.locator("option").evaluate_all(
        "els => els.map(e => e.value)"
    )
    assert source.resource_id not in values, values
    assert target.resource_id in values, values
