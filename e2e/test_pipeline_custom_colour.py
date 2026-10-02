"""p.38's Custom color on the pipeline graph (§682; `data-lineage` p.38).

> "Custom color: Allows you to select nodes and assign them a color by
> clicking on the Color button." (p.38)

Which colour a node takes, the legend's order and the palette are
`node-colouring.test.ts`; that a saved graph keeps them is
`test_saved_graphs.py`. What needs a browser is the gesture: select cards,
choose a colour, and see the cards, the colouring and the legend follow - and
the link carry it, since a graph coloured by hand is a picture made to send.
"""
from __future__ import annotations

from playwright.sync_api import expect

from test_pipeline_colouring import coloured, open_graph  # noqa: F401


def cards(page, kind: str):
    return page.locator(f"[data-testid='graph-node'][data-kind='{kind}']")


def test_selected_cards_take_the_colour_chosen(page, coloured) -> None:
    open_graph(page, coloured)
    # Nothing selected is nothing to colour.
    expect(page.get_by_test_id("graph-paint")).to_have_count(0)
    first, second = cards(page, "model").nth(0), cards(page, "model").nth(1)
    first.click()
    second.click(modifiers=["Control"])
    expect(second).to_have_attribute("data-selected", "true")
    page.get_by_test_id("graph-paint").select_option("red")

    # The colouring moves to show what was given, and the control resets so
    # the same colour can be given again to the next selection.
    expect(page.get_by_test_id("graph-colouring")).to_have_value("custom")
    expect(page.get_by_test_id("graph-paint")).to_have_value("")
    expect(first).to_have_attribute("data-colour", "paint:red")
    expect(second).to_have_attribute("data-colour", "paint:red")
    expect(cards(page, "dataset").first).to_have_attribute("data-colour", "unpainted")
    expect(page.get_by_test_id("legend-paint:red")).to_have_attribute("data-count", "2")
    expect(page.get_by_test_id("legend-unpainted")).to_contain_text("No colour given")

    # One of them made green: the other keeps its red.
    first.click()
    page.get_by_test_id("graph-paint").select_option("green")
    expect(first).to_have_attribute("data-colour", "paint:green")
    expect(second).to_have_attribute("data-colour", "paint:red")
    keys = [row.get_attribute("data-testid") for row in page.locator("[data-testid^='legend-']").all()]
    assert keys == ["legend-paint:red", "legend-paint:green", "legend-unpainted"], keys

    # The link carries the colours, so a reload - or whoever it is sent to -
    # sees the same picture.
    node = first.get_attribute("data-node")
    page.wait_for_function(
        "node => new URLSearchParams(location.search).getAll('paint').includes(node + '@green')",
        arg=node)
    page.reload()
    expect(page.get_by_test_id("graph-colouring")).to_have_value("custom")
    expect(page.locator(f"[data-node='{node}']")).to_have_attribute("data-colour", "paint:green")


def test_no_colour_takes_a_colour_back(page, coloured) -> None:
    open_graph(page, coloured)
    card = cards(page, "dataset").first
    card.click()
    page.get_by_test_id("graph-paint").select_option("teal")
    expect(card).to_have_attribute("data-colour", "paint:teal")
    page.get_by_test_id("graph-paint").select_option("clear")
    expect(card).to_have_attribute("data-colour", "unpainted")
    expect(page.get_by_test_id("legend-paint:teal")).to_have_count(0)
