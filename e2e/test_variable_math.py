"""Math operations and numeric comparisons on Workshop variables (§564;
`foundry_workshop` p.140-141).

    "Add: Returns the sum of given numeric values or variables. … Divide …
     Round Nearest: Returns the rounded value to a specified precision …"
     (p.140)

    "Greater than: Runs a boolean check on if the first given numeric value
     or variable is greater than the second given numeric value(s) or
     variable(s)." (p.141)

The arithmetic is `apps/api/tests/test_variable_math.py`. What needs a
browser is the panel building one, and a derived number reaching a widget.
A is typed into the panel as text, as the panel keeps it, and is still 12.
"""
from __future__ import annotations

import re

from playwright.sync_api import expect

from api import Module, layout
from conftest import WEB_BASE, eventually, open_module, settled


def derived(vid: str, transform: str, inputs: list[str], kind="number", **config) -> dict:
    return {"id": vid, "kind": kind, "label": vid.capitalize(),
            "derivation": {"transform": transform, "inputs": inputs, "config": config}}


def build(api, name: str) -> Module:
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({"txt": {"resolvedName": "CanvasText", "props": {
            "tag": "p", "text": "sum {{sum}} | ratio {{rounded}} | big {{big}}"}}}),
        "variables": {
            "a": {"id": "a", "kind": "number", "label": "A", "default": "12"},
            "b": {"id": "b", "kind": "number", "label": "B", "default": 5},
            "sum": derived("sum", "add", ["a", "b"]),
            "ratio": derived("ratio", "divide", ["a", "b"]),
            "rounded": derived("rounded", "round_nearest", ["ratio"], precision=1),
            "big": derived("big", "greater_than", ["sum", "a"], kind="boolean"),
            "total": {"id": "total", "kind": "number", "label": "Total"},
        },
        "events": {},
    })
    return mod


def test_derived_numbers_reach_the_page(page, api) -> None:
    open_module(page, build(api, "Math reaches"))
    expect(page.get_by_text("sum 17 | ratio 2.4 | big true")).to_be_visible(timeout=20000)


def test_the_panel_builds_a_math_operation(page, api) -> None:
    mod = build(api, "Math panel")
    page.goto(f"{WEB_BASE}{mod.url}")
    expect(page.get_by_role("button", name="Preview", exact=True)).to_be_visible(timeout=30000)
    page.get_by_role("button", name="Variables", exact=False).first.click()
    page.get_by_text("Total", exact=True).first.click()
    page.get_by_role("button", name="Make this derived").click()
    page.get_by_label("Computed by").select_option("round_nearest")
    page.get_by_role("combobox", name=re.compile(r"^Value")).select_option("ratio")
    page.get_by_test_id("math-precision").fill("2")
    save_and_expect(page, mod, {"transform": "round_nearest", "inputs": ["ratio"],
                                "config": {"precision": 2}})
    page.get_by_label("Computed by").select_option("subtract")
    page.get_by_role("combobox", name=re.compile(r"^From")).select_option("sum")
    page.get_by_role("combobox", name=re.compile(r"^Take away")).first.select_option("a")
    # Another slot opens for a second number to take away.
    expect(page.get_by_role("combobox", name=re.compile(r"^Take away"))).to_have_count(2)
    save_and_expect(page, mod, {"transform": "subtract", "inputs": ["sum", "a"], "config": {}})


def test_an_edit_made_while_a_save_refetches_is_kept(page, api) -> None:
    """**A Save must not undo what is typed straight after it.**

    A Save refetches the module, and the builder used to reset its panels from
    whatever came back. That is the document just sent, so the reset could only
    lose something: an edit made between the PUT returning and the refetch
    landing went back to the saved value, and the next Save wrote the old value
    over it. It surfaced as `test_the_panel_builds_a_math_operation` going red
    on an unrelated change (#468), because that test edits straight after
    saving.

    The refetch is held rather than slowed, for `test_action_sections`' reason:
    a sleeping route handler blocks Playwright's dispatcher.
    """
    mod = build(api, "Math refetch")
    page.goto(f"{WEB_BASE}{mod.url}")
    expect(page.get_by_role("button", name="Preview", exact=True)).to_be_visible(timeout=30000)
    page.get_by_role("button", name="Variables", exact=False).first.click()
    page.get_by_text("Total", exact=True).first.click()
    page.get_by_role("button", name="Make this derived").click()
    page.get_by_label("Computed by").select_option("round_nearest")
    page.get_by_role("combobox", name=re.compile(r"^Value")).select_option("ratio")
    page.get_by_test_id("math-precision").fill("2")

    held = []
    the_module = re.compile(r"/canvas-apps/[^/?]+(\?.*)?$")

    def hold(route):
        if route.request.method == "GET":
            held.append(route)
        else:
            route.continue_()

    page.route(the_module, hold)
    try:
        save_and_expect(page, mod, {"transform": "round_nearest", "inputs": ["ratio"],
                                    "config": {"precision": 2}})
        page.get_by_label("Computed by").select_option("subtract")
        page.get_by_role("combobox", name=re.compile(r"^From")).select_option("sum")
        page.get_by_role("combobox", name=re.compile(r"^Take away")).first.select_option("a")
        assert held, "the save did not refetch the module"
    finally:
        if held:
            with page.expect_response(
                lambda r: the_module.search(r.url) and r.request.method == "GET"
            ):
                for route in held:
                    route.continue_()
        # After the release: unrouting first lets Playwright continue the held
        # requests itself, and the release then fails as already handled.
        page.unroute(the_module)

    # The refetch has landed. The edit made while it was held is still there...
    expect(page.get_by_label("Computed by")).to_have_value("subtract")
    # ...and it is what the next Save writes.
    save_and_expect(page, mod, {"transform": "subtract", "inputs": ["sum", "a"], "config": {}})


def save_and_expect(page, mod, derivation: dict) -> None:
    with page.expect_response(
        lambda r: "/definition" in r.url and r.request.method in ("PUT", "POST")
    ) as saved:
        page.get_by_role("button", name="Save", exact=True).click()
    assert saved.value.ok, saved.value.status
    settled(page)
    eventually(lambda: mod.definition()["variables"]["total"].get("derivation"),
               lambda d: d == derivation, what=f"{derivation['transform']}, saved")
