"""The module interface: one external ID, reached three ways (parity §3.4).

Foundry documents embedding, URL initialisation and state saving as three
features. They are one mechanism — a variable's **external ID** — and the whole
point of building it this way is that the three cannot drift apart:

    "The module interface is the set of variables that are able to be mapped to
     variables from a parent module when embedded, and initialized from the
     URL. You can think of the module interface as the API for a Workshop
     module." (docs/pal/foundry_workshop.pdf p.163)

So this is deliberately **one** module with **one** interface variable, asked
about twice. The spec's instruction is the reason: "If any of the three needs
its own mechanism, the design is wrong." A separate fixture per consumer would
pass just as happily against three unrelated implementations, which is exactly
the outcome the design is trying to avoid.

**State saving is the third consumer and is not built yet** (`workshop.md` §7).
When it is, its assertion belongs in this file against this fixture — not in a
new one.

What the server refuses is tested in `apps/api/tests/test_canvas.py`: an
external ID the child does not publish, a kind mismatch, a required variable
left unmapped. Those are decided when the author saves, so they never reach a
browser.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import WEB_BASE, eventually, no_console_errors, open_module, settled

COUNTS = {"north": 4, "south": 2}


@pytest.fixture(scope="module")
def modules(api):
    """A child whose table is filtered by an interface variable, and a host
    that passes a *different* value into it.

    The child's own default is `north` and the host passes `south`, and the two
    regions have different row counts. That is what makes the precedence rule
    checkable by counting rows: p.127 says "default variable values of mapped
    variables defined in the child module will not be used", so a child showing
    four rows would mean its own default had won.
    """
    rows = [
        {"id": f"{region[0].upper()}{i}", "region": region, "name": f"Site {region} {i}"}
        for region, count in COUNTS.items()
        for i in range(1, count + 1)
    ]
    child = Module(api, "Interface child")
    type_id = child.object_type(
        columns=["id", "region", "name"], rows=rows, key="id", title="name"
    )
    child.define({
        "format": 2,
        "layout": layout({
            "txt": {"resolvedName": "CanvasText",
                    "props": {"tag": "p", "text": "CHILD MODULE"}},
            "tbl": {"resolvedName": "CanvasObjectTable",
                    "props": {"objectSetVariable": "v_filtered", "columns": "id,region",
                              "pageSize": 25}},
        }),
        "variables": {
            # The interface variable. `external_id` is the public name; `v_region`
            # is private and never appears in a URL or a mapping.
            "v_region": {
                "id": "v_region", "kind": "string", "label": "Region",
                "default": "north",
                "external_id": "region",
                "interface": {"display_name": "Region to show"},
            },
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All sites",
                      "object_set": object_set(type_id)},
            "v_filtered": {
                "id": "v_filtered", "kind": "object_set", "label": "Filtered",
                "derivation": {"transform": "filter_set", "inputs": ["v_all", "v_region"],
                               "config": {"property": "region", "op": "eq"}},
            },
        },
        "events": {},
    })

    host = Module(api, "Interface host", beside=child)
    host.define({
        "format": 2,
        "layout": layout({
            "emb": {"resolvedName": "CanvasEmbeddedModule",
                    "props": {"moduleId": child.app_id, "title": "Embedded",
                              # Keyed by the child's *external* ID, valued by the
                              # host's own variable id. That asymmetry is the
                              # boundary: a public name translated to a private one.
                              "interface": {"region": "v_host_region"}}},
        }),
        "variables": {
            "v_host_region": {"id": "v_host_region", "kind": "string",
                              "label": "Region", "default": "south"},
        },
        "events": {},
    })
    return host, child


def test_a_host_backs_an_embedded_modules_interface_variable(page, modules):
    """Assertion one: the value crosses the boundary, and the host's definition
    wins over the child's own default (p.122, p.127)."""
    host, _ = modules
    open_module(page, host)

    embedded = page.locator(".canvas-embedded")
    expect(embedded).to_be_visible()
    expect(embedded.get_by_text("CHILD MODULE")).to_be_visible()

    # South, because the host said so — not north, which is what the child
    # would show on its own. Counting rows rather than reading a value, because
    # the question is whether the passed value actually *did* anything.
    rows = page.locator(".canvas-embedded table tbody tr")
    eventually(lambda: rows.count(), lambda n: n == COUNTS["south"],
               what="embedded rows filtered by the host's value")
    assert not no_console_errors(page)


def test_the_same_external_id_initialises_the_module_from_a_url(page, modules):
    """Assertion two: the same name, reached the other way (p.165).

    `?region=south` against the child *directly* — no host involved — and the
    child's own default of north gives way to it. Same external ID, same
    variable, different consumer.
    """
    _, child = modules

    # First without the query parameter, so the default is established as the
    # thing being overridden rather than assumed.
    open_module(page, child)
    rows = page.locator(".canvas-block table tbody tr")
    eventually(lambda: rows.count(), lambda n: n == COUNTS["north"],
               what="the child's own default of north")

    page.goto(f"{WEB_BASE}{child.url}?region=south")
    preview = page.get_by_role("button", name="Preview", exact=True)
    expect(preview).to_be_visible()
    preview.click()
    settled(page)
    eventually(lambda: rows.count(), lambda n: n == COUNTS["south"],
               what="the region seeded from the URL")


def test_a_query_parameter_that_is_not_an_interface_variable_does_nothing(page, modules):
    """The refusal half, and the reason it matters: an external ID with the
    interface toggle off is a name for state saving, not a public input. If
    every query parameter seeded every variable, anyone who could write a link
    could set any of them."""
    _, child = modules
    page.goto(f"{WEB_BASE}{child.url}?v_region=south&nosuch=south")
    preview = page.get_by_role("button", name="Preview", exact=True)
    expect(preview).to_be_visible()
    preview.click()
    settled(page)

    # The private variable id is not a way in, so the default still stands.
    rows = page.locator(".canvas-block table tbody tr")
    eventually(lambda: rows.count(), lambda n: n == COUNTS["north"],
               what="the default, because neither parameter names the interface")
