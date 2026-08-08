"""Drag-to-resize sections (roadmap 1.4, `STATUS.md` §109).

The last item on 1.4, and the one that could only ever be checked in a browser:
its whole substance is a pointer gesture and what it writes.

**The claim under test is that dragging is a way of typing.** The handle writes
the same `weights` prop the Settings field edits, so after a drag the field
shows the new numbers — a resize that stored pixels somewhere else would look
identical here and disagree the first time the window changed size.

Builder-only, deliberately: a viewer dragging a divider would be editing the
saved document, which decision 0002 rules out.
"""
from __future__ import annotations

import pytest

from playwright.sync_api import expect

from api import Module, layout
from conftest import eventually, no_console_errors, open_builder, open_module

MIN_PERCENT = 8  # MIN_SHARE in widgets.tsx, as a percentage


@pytest.fixture(scope="module")
def module(api):
    built = Module(api, "Layout")
    built.define(
        {
            "format": 2,
            "layout": {
                "ROOT": {
                    "type": {"resolvedName": "CanvasContainer"},
                    "isCanvas": True, "props": {},
                    "nodes": ["cols", "rows", "flat"], "linkedNodes": {},
                },
                # Two sections, one per axis: a handle that resized the wrong
                # axis would look right in a column section and do nothing in a
                # row one.
                "cols": {
                    "type": {"resolvedName": "CanvasSection"},
                    "props": {"direction": "columns", "weights": "1,1", "gap": 12},
                    "parent": "ROOT", "nodes": ["a", "b"], "isCanvas": True,
                },
                "a": {"type": {"resolvedName": "CanvasText"},
                      "props": {"tag": "p", "text": "Left"}, "parent": "cols", "nodes": []},
                "b": {"type": {"resolvedName": "CanvasText"},
                      "props": {"tag": "p", "text": "Right"}, "parent": "cols", "nodes": []},
                # A height, because a row section without one has no free
                # space for `flex-grow` to share out - so its proportions do
                # nothing and a handle would move a boundary nothing can see.
                # That was true of *every* row section until the first version
                # of this test asked one to change shape; see `STATUS.md` §109.
                "rows": {
                    "type": {"resolvedName": "CanvasSection"},
                    "props": {"direction": "rows", "weights": "1,1", "gap": 12,
                              "minHeight": 300},
                    "parent": "ROOT", "nodes": ["c", "d"], "isCanvas": True,
                },
                # A second row section with no height: its proportions cannot
                # apply, so it must not offer a handle either.
                "flat": {
                    "type": {"resolvedName": "CanvasSection"},
                    "props": {"direction": "rows", "weights": "1,1", "gap": 12},
                    "parent": "ROOT", "nodes": ["e", "f"], "isCanvas": True,
                },
                "e": {"type": {"resolvedName": "CanvasText"},
                      "props": {"tag": "p", "text": "Flat top"}, "parent": "flat", "nodes": []},
                "f": {"type": {"resolvedName": "CanvasText"},
                      "props": {"tag": "p", "text": "Flat bottom"}, "parent": "flat",
                      "nodes": []},
                "c": {"type": {"resolvedName": "CanvasText"},
                      "props": {"tag": "p", "text": "Top"}, "parent": "rows", "nodes": []},
                "d": {"type": {"resolvedName": "CanvasText"},
                      "props": {"tag": "p", "text": "Bottom"}, "parent": "rows", "nodes": []},
            },
            "variables": {},
            "events": {},
        }
    )
    return built


def handles(page):
    return page.locator(".canvas-section-handle")


def parts(page, section=0):
    return page.locator(".canvas-section-parts").nth(section).locator(
        "> .canvas-section-part"
    )


def widths(page, section=0) -> list[float]:
    return [
        parts(page, section).nth(i).bounding_box()["width"]
        for i in range(parts(page, section).count())
    ]


def heights(page, section=0) -> list[float]:
    return [
        parts(page, section).nth(i).bounding_box()["height"]
        for i in range(parts(page, section).count())
    ]


def drag(page, handle, dx: float, dy: float) -> None:
    """A real pointer drag. `mouse.move` in steps rather than one jump: the
    handler listens for `pointermove`, and a single teleport produces one event
    at the destination, which is not what a drag looks like."""
    box = handle.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] / 2 + dx, box["y"] + box["height"] / 2 + dy,
                    steps=10)
    page.mouse.up()


def test_a_handle_sits_between_parts_and_only_in_the_builder(page, module):
    open_builder(page, module)
    # Three sections of two parts each — but the heightless row section offers
    # no handle, because its proportions cannot apply. An affordance that
    # promises nothing is worse than no affordance.
    expect(handles(page)).to_have_count(2)
    assert not no_console_errors(page)

    open_module(page, module)  # Preview
    # **Presence before absence.** Waiting for the parts first is what stops
    # "no handles" being true of a page that has not drawn yet.
    expect(parts(page)).to_have_count(2)
    expect(handles(page)).to_have_count(0)  # a viewer does not edit the layout


def test_dragging_a_column_handle_moves_the_boundary(page, module):
    open_builder(page, module)
    expect(handles(page)).to_have_count(2)
    before = widths(page, 0)
    assert abs(before[0] - before[1]) < 2, "starts even"

    drag(page, handles(page).first, dx=120, dy=0)
    after = eventually(lambda: widths(page, 0), lambda got: got[0] > before[0] + 80,
                       what="the widened column")
    assert after[0] > before[0] + 80, after
    assert after[1] < before[1] - 80, after
    # The pair keeps its combined share: dragging one divider must not take
    # space from anything outside it.
    assert abs(sum(after) - sum(before)) < 4, (before, after)


def test_a_drag_writes_the_same_numbers_the_settings_field_edits(page, module):
    """The whole claim: dragging is a way of typing, not a second description
    of the layout living somewhere else."""
    open_builder(page, module)
    expect(handles(page)).to_have_count(2)
    before = widths(page, 0)
    drag(page, handles(page).first, dx=120, dy=0)
    eventually(lambda: widths(page, 0), lambda got: got[0] > before[0] + 80,
               what="the widened column")

    # Select the section so its settings panel is showing, then read the field.
    page.locator(".canvas-section").first.locator(".canvas-section-label").first.click()
    field = page.get_by_placeholder("equal")
    expect(field).to_be_visible()
    value = eventually(lambda: field.input_value(), lambda got: "," in got,
                       what="the proportions field")

    numbers = [float(n) for n in value.split(",")]
    assert len(numbers) == 2, value
    assert numbers[0] > numbers[1], f"the left column was widened: {value}"
    # Readable, not float noise — a layout the document can describe.
    assert all(len(n.split(".")[-1]) <= 2 for n in value.split(",") if "." in n), value


def test_dragging_a_row_handle_moves_the_vertical_boundary(page, module):
    open_builder(page, module)
    expect(handles(page)).to_have_count(2)
    before = heights(page, 1)
    drag(page, handles(page).nth(1), dx=0, dy=60)
    after = eventually(lambda: heights(page, 1), lambda got: got[0] > before[0] + 30,
                       what="the taller row")
    assert after[0] > before[0] + 30, (before, after)
    assert after[1] < before[1] - 30, (before, after)


def test_a_part_cannot_be_dragged_away_entirely(page, module):
    """A part dragged to nothing leaves no handle to grab and no way back
    except the Settings field — an unrecoverable state reached by an ordinary
    gesture."""
    open_builder(page, module)
    expect(handles(page)).to_have_count(2)
    total = sum(widths(page, 0))
    start = widths(page, 0)
    drag(page, handles(page).first, dx=-4000, dy=0)

    after = eventually(lambda: widths(page, 0), lambda got: got[0] < start[0] / 2,
                       what="the collapsed column")
    assert after[0] > total * (MIN_PERCENT / 100) * 0.8, after
    assert handles(page).count() == 2, "and the handle is still grabbable"

    # And it comes back: the clamp is a floor, not a trap.
    drag(page, handles(page).first, dx=4000, dy=0)
    eventually(lambda: widths(page, 0), lambda got: got[0] > after[0] * 2,
               what="the column dragged back")


def test_the_handle_is_operable_from_the_keyboard(page, module):
    """A splitter only a mouse can move is one a keyboard user cannot use at
    all, and the layout is the least recoverable part of the builder."""
    open_builder(page, module)
    expect(handles(page)).to_have_count(2)
    before = widths(page, 0)

    handle = handles(page).first
    handle.focus()
    assert handle.get_attribute("role") == "separator"
    assert handle.get_attribute("aria-orientation") == "vertical"
    starting = int(handle.get_attribute("aria-valuenow"))

    for _ in range(3):
        page.keyboard.press("ArrowRight")
    after = eventually(lambda: widths(page, 0), lambda got: got[0] > before[0] + 10,
                       what="the column widened by keyboard")
    assert int(handle.get_attribute("aria-valuenow")) > starting

    for _ in range(3):
        page.keyboard.press("ArrowLeft")
    eventually(lambda: widths(page, 0), lambda got: abs(got[0] - before[0]) < 4,
               what="the column returned")
    assert after[0] > before[0]
