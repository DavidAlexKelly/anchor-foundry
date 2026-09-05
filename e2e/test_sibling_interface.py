"""p.164's two claims about embedded modules talking to each other (parity
`workshop.md` §4).

> "Use module interface variables to communicate between a parent and child
> module **or between sibling embedded modules**. These shared interface
> variables can back shared state, such as a selected object, a selected tab, or
> whether an overlay is shown. **Embedded modules may modify the value of
> interface variables through events**, allowing other places that reference
> these variables to respond to the updated value." (p.164)

Both rows were ◑ for the same reason, written in the roadmap itself: *"works by
construction … but **untested**, so it is a claim about the design rather than a
demonstrated behaviour."* This file is that distinction being settled.

**Nothing here is new capability.** The write path is `CanvasParameterProvider`'s
`link`: a child's `set_variable` on a bound id routes to the host's setter, and
the host's resolved values come back down as the children's inputs. Whether that
loop actually closes — through two nested editors, a variable resolve and a
render — is not something reading it can decide, which is exactly what "by
construction" was admitting.

One fixture answers both, because they are one mechanism seen from two sides:
the same child embedded twice, both mapped to one host variable.
"""
from __future__ import annotations

import pytest

from api import Module, layout
from conftest import eventually, open_module, settled


@pytest.fixture(scope="module")
def modules(api):
    """A child that can *write* its interface variable, embedded twice.

    The child's own default is `north`, the host's is `west`, and the button
    writes `south` — three distinct values, so every assertion below says which
    of the three won rather than "something changed".
    """
    child = Module(api, "Sibling child")
    child.define({
        "format": 2,
        "layout": layout({
            "btn": {"resolvedName": "CanvasButton", "props": {"label": "Send south"}},
            "txt": {"resolvedName": "CanvasText",
                    "props": {"tag": "p", "text": "CHILD={{v_region}}"}},
        }),
        "variables": {
            "v_region": {
                "id": "v_region", "kind": "string", "label": "Region",
                "default": "north",
                "external_id": "region",
                "interface": {"display_name": "Region"},
            },
        },
        "events": {
            "e_1": {
                "id": "e_1", "trigger": {"node": "btn", "on": "click"},
                # p.164's "may modify the value of interface variables through
                # events". Written against the child's *own* variable id — the
                # child knows nothing about the host, which is the point.
                "effects": [{"type": "set_variable",
                             "config": {"variable": "v_region", "value": "south"}}],
            },
        },
    })

    host = Module(api, "Sibling host", beside=child)
    host.define({
        "format": 2,
        "layout": layout({
            "a": {"resolvedName": "CanvasEmbeddedModule",
                  "props": {"moduleId": child.app_id, "title": "A",
                            "interface": {"region": "v_host_region"}}},
            "b": {"resolvedName": "CanvasEmbeddedModule",
                  "props": {"moduleId": child.app_id, "title": "B",
                            "interface": {"region": "v_host_region"}}},
            "txt": {"resolvedName": "CanvasText",
                    "props": {"tag": "p", "text": "HOST={{v_host_region}}"}},
        }),
        "variables": {
            "v_host_region": {"id": "v_host_region", "kind": "string",
                              "label": "Region", "default": "west"},
        },
        "events": {},
    })
    return host, child


def child_texts(page):
    """What each embedded copy is showing, in document order."""
    return page.locator(".canvas-embedded").locator("p").filter(
        has_text="CHILD="
    ).all_inner_texts()


def host_text(page) -> str:
    return page.get_by_text("HOST=", exact=False).first.inner_text()


def test_both_copies_start_on_the_hosts_value(page, modules):
    """p.127's precedence, and the baseline that makes the rest mean something.

    The host says `west` and the child's own default is `north`, so two copies
    reading `west` is the mapping working before anybody has clicked anything.
    Without this, a later assertion that both say `south` could be satisfied by
    two children that were never connected to the host at all.
    """
    host, _ = modules
    open_module(page, host)
    settled(page)

    eventually(lambda: child_texts(page),
               lambda t: t == ["CHILD=west", "CHILD=west"],
               what="both embedded copies on the host's value")
    assert host_text(page) == "HOST=west"


def test_a_child_writes_its_interface_variable_up_to_the_host(page, modules):
    """p.164: "Embedded modules may modify the value of interface variables
    through events."

    **Read on the host's own widget**, not inside the embed. A child showing its
    own write is the child agreeing with itself; what p.164 promises is that the
    value crossed the boundary, and only the host's readout can say that.
    """
    host, _ = modules
    open_module(page, host)
    settled(page)
    eventually(lambda: host_text(page), lambda t: t == "HOST=west",
               what="the host's starting value")

    page.locator(".canvas-embedded").first.get_by_role(
        "button", name="Send south"
    ).click()

    eventually(lambda: host_text(page), lambda t: t == "HOST=south",
               what="the host's variable, written from inside the embedded module")


def test_one_embed_writes_and_its_sibling_reads(page, modules):
    """p.164's "or between sibling embedded modules", which is the row that has
    been ◑ on "works by construction" since §114.

    **The second copy is the assertion.** The two embeds know nothing about each
    other — neither names the other, and the only thing they share is a host
    variable both are mapped to. So a value appearing in B after a click in A is
    the whole claim: it went up through the host's setter, was resolved, and
    came back down the other side.
    """
    host, _ = modules
    open_module(page, host)
    settled(page)
    eventually(lambda: child_texts(page),
               lambda t: t == ["CHILD=west", "CHILD=west"],
               what="both copies before the click")

    page.locator(".canvas-embedded").first.get_by_role(
        "button", name="Send south"
    ).click()

    eventually(lambda: child_texts(page),
               lambda t: t == ["CHILD=south", "CHILD=south"],
               what="the sibling copy showing what the other one wrote")
