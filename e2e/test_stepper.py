"""p.312-313's Stepper (parity `workshop.md` §7).

> "The Stepper widget can be used to help navigate the user through a
> multi-step workflow, displaying and tracking progress as they walk through a
> sequence of steps." (p.312)

> "**Type**: **Linear**: Users are required to complete the steps in order.
> **Non-linear**: Users can freely navigate between steps and complete them in
> any order." (p.312)

> "**Steps**… **Label**… **On click**… **Is completed**: Set a boolean variable
> to be used a check to determine when a step has been completed. **Icon**…
> **Template**: **Text only**… **Use icons**… **Show step number**… **Completed
> color**… **Active color**." (p.313)

The rules are `apps/web/src/components/canvas/stepper.test.ts`, mutation-tested
without a browser: which step is active, what counts as completed, whether a
step can be reached, and when a step number appears.

**What needs a browser is that progress is read rather than held.** p.313 makes
completion a boolean variable the *module* owns, so the interesting failures
are ones only a running page has: a stepper that remembered its own progress
and drifted from the variables beside it, a linear step that could be clicked
before its predecessors, and a colour that names a state nothing paints.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder, open_module, settled

STEPS = [
    {"label": "Pick a site", "completedVariable": "v_d1", "icon": "search"},
    {"label": "Confirm details", "completedVariable": "v_d2", "icon": "edit"},
    {"label": "Submit", "completedVariable": "v_d3", "icon": "tick"},
]


def build(
    api,
    name: str,
    props: dict | None = None,
    *,
    done: tuple[bool, ...] = (False, False, False),
    defaults: bool = True,
    extra_effects: list[dict] | None = None,
):
    """One stepper, a button per step that completes it, and a marker.

    The buttons are what make completion *the module's*: nothing the stepper
    does sets a completion variable, which is the design p.313 describes and
    the thing a browser can actually check.

    The marker is p.313's On click, and it doubles as §202's clock - asserting
    that a click did **not** fire needs a point after which it definitely would
    have.
    """
    nodes = {
        "stp": {
            "resolvedName": "CanvasStepper",
            "props": {"steps": STEPS, "stepperType": "linear", "template": "text",
                      "showStepNumber": False, "completedColour": "", "activeColour": "",
                      **(props or {})},
        },
        "echo": {"resolvedName": "CanvasText",
                 "props": {"tag": "p", "text": "clicked: [{{v_mark}}] clock: [{{v_clock}}]"}},
        "clk": {"resolvedName": "CanvasButton", "props": {"label": "Tick the clock"}},
    }
    events = {
        # p.313's On click, carrying both halves of the payload the widget
        # sends: a step's number *and* its label. One would leave the other
        # free to be anything.
        "e_click": {
            "id": "e_click", "trigger": {"node": "stp", "on": "click"},
            "effects": [{"type": "set_variable",
                         "config": {"variable": "v_mark", "value": "{{step}}/{{label}}"}}],
        },
        "e_clock": {
            "id": "e_clock", "trigger": {"node": "clk", "on": "click"},
            "effects": [
                *(extra_effects or []),
                {"type": "set_variable",
                 "config": {"variable": "v_clock", "value": "ticked"}},
            ],
        },
    }
    variables = {
        "v_mark": {"id": "v_mark", "kind": "string", "label": "Mark", "default": "no"},
        # **A separate variable from the marker.** A clock that shared it would
        # make "the click did nothing" pass because the evidence had been
        # overwritten rather than because nothing wrote it.
        "v_clock": {"id": "v_clock", "kind": "string", "label": "Clock", "default": "no"},
    }
    for index, finished in enumerate(done, start=1):
        variables[f"v_d{index}"] = {
            "id": f"v_d{index}", "kind": "boolean", "label": f"Step {index} done",
            # `defaults=False` leaves the key off entirely, which is a boolean
            # variable nothing has ever written - a different thing from one
            # holding `false`, and the one a fresh module actually starts in.
            **({"default": finished} if defaults else {}),
        }
    mod = Module(api, name)
    mod.define({"format": 2, "layout": layout(nodes), "variables": variables,
                "events": events})
    return mod


def steps(page):
    return page.get_by_test_id("step")


def step_at(page, index: int):
    return steps(page).nth(index)


def test_it_draws_one_step_per_configured_step(page, api) -> None:
    mod = build(api, "Stepper basic")
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("stepper")).to_be_visible()
    expect(steps(page)).to_have_count(3)
    expect(step_at(page, 0)).to_contain_text("Pick a site")
    expect(step_at(page, 2)).to_contain_text("Submit")


def test_a_step_with_no_label_is_not_drawn(page, api) -> None:
    """A numbered circle with nothing beside it is a step nobody can identify,
    and the workflow it belongs to is the thing being navigated. Asserted on a
    document a raw JSON edit can produce, which is where such a step comes
    from."""
    mod = build(api, "Stepper blank label", {"steps": [
        STEPS[0], {"completedVariable": "v_d2"}, {"label": "   "}, STEPS[2],
    ]})
    open_module(page, mod)
    settled(page)

    expect(steps(page)).to_have_count(2)
    expect(step_at(page, 1)).to_contain_text("Submit")
    # And the numbering closes up rather than leaving a gap where the dropped
    # steps were - p.313's "ordered numbers" are of the steps that exist.
    expect(step_at(page, 1).get_by_test_id("step-mark")).to_have_text("2")


def test_a_stepper_with_no_steps_says_so(page, api) -> None:
    mod = build(api, "Stepper empty", {"steps": []})
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("stepper")).to_have_count(0)
    expect(page.get_by_text("Stepper - add steps in Settings")).to_be_visible()


def test_progress_is_read_from_the_module_s_variables(page, api) -> None:
    """**The widget's whole design.** p.313 makes completion "a boolean
    variable to be used a check", so what the stepper shows is whatever those
    variables say - not something it worked out for itself and now holds."""
    mod = build(api, "Stepper progress", done=(True, False, False))
    open_module(page, mod)
    settled(page)

    expect(step_at(page, 0)).to_have_attribute("data-state", "completed")
    expect(step_at(page, 1)).to_have_attribute("data-state", "active")
    expect(step_at(page, 2)).to_have_attribute("data-state", "upcoming")


def test_completing_a_step_moves_the_active_one(page, api) -> None:
    """The same fact through a change rather than a starting state: a module
    that writes a completion variable moves the stepper, without the stepper
    being told."""
    # The button completes step one, which is how a real workflow does it: the
    # module writes the variable and the stepper finds out by reading it.
    mod = build(api, "Stepper advance", extra_effects=[
        {"type": "set_variable", "config": {"variable": "v_d1", "value": True}},
    ])
    open_module(page, mod)
    settled(page)

    expect(step_at(page, 0)).to_have_attribute("data-state", "active")
    page.get_by_role("button", name="Tick the clock").click()
    expect(page.get_by_text("clock: [ticked]")).to_be_visible()

    expect(step_at(page, 0)).to_have_attribute("data-state", "completed")
    expect(step_at(page, 1)).to_have_attribute("data-state", "active")


def test_a_finished_workflow_highlights_nothing(page, api) -> None:
    """Every step complete means there is no step left to be on. A stepper that
    kept its last step active would look unfinished to the person who had just
    finished it."""
    mod = build(api, "Stepper finished", done=(True, True, True))
    open_module(page, mod)
    settled(page)

    expect(steps(page)).to_have_count(3)
    expect(page.locator("[data-testid='step'][data-state='active']")).to_have_count(0)
    expect(page.locator("[data-testid='step'][data-state='completed']")).to_have_count(3)


def test_a_variable_nothing_has_written_is_not_completion(page, api) -> None:
    """A boolean variable with no default holds nothing at all, and a step that
    counted that as done would open every workflow with every stage ticked."""
    mod = build(api, "Stepper unwritten", defaults=False)
    open_module(page, mod)
    settled(page)

    expect(step_at(page, 0)).to_have_attribute("data-state", "active")
    expect(page.locator("[data-testid='step'][data-state='completed']")).to_have_count(0)


def test_a_step_with_no_completion_variable_is_never_complete(page, api) -> None:
    """p.313's Is completed is optional, and a step without one is a step
    nothing can finish - so the workflow stops there rather than sailing past
    it."""
    mod = build(api, "Stepper unbound", {"steps": [
        {"label": "Pick a site", "completedVariable": "v_d1"},
        {"label": "Unbound"},
        {"label": "Submit", "completedVariable": "v_d3"},
    ]}, done=(True, False, True))
    open_module(page, mod)
    settled(page)

    expect(step_at(page, 1)).to_have_attribute("data-state", "active")
    # And the third stays unreachable even though its own variable says done:
    # p.312's linear rule is about the steps *before* it.
    expect(step_at(page, 2)).to_have_attribute("data-reachable", "no")


# ---- p.312's Type ------------------------------------------------------------
def test_a_linear_stepper_will_not_let_a_later_step_be_clicked(page, api) -> None:
    """p.312: "users are required to complete the steps in order". Asserted as
    the event **not** firing, against a clock - a disabled attribute is what the
    widget writes, and what matters is that a viewer cannot get past it."""
    mod = build(api, "Stepper linear", done=(False, False, False))
    open_module(page, mod)
    settled(page)

    expect(step_at(page, 2)).to_have_attribute("data-reachable", "no")
    page.get_by_test_id("step-2").click(force=True)
    page.get_by_role("button", name="Tick the clock").click()
    expect(page.get_by_text("clock: [ticked]")).to_be_visible()
    # The clock has ticked, so a click that was going to fire has had its turn.
    expect(page.get_by_text("clicked: [no]")).to_be_visible()


def test_a_non_linear_stepper_lets_any_step_be_clicked(page, api) -> None:
    """p.312's other type: "users can freely navigate between steps and
    complete them in any order"."""
    mod = build(api, "Stepper non-linear", {"stepperType": "non_linear"})
    open_module(page, mod)
    settled(page)

    expect(step_at(page, 2)).to_have_attribute("data-reachable", "yes")
    page.get_by_test_id("step-2").click()
    expect(page.get_by_text("clicked: [3/Submit]")).to_be_visible()


def test_the_first_step_is_always_reachable(page, api) -> None:
    """Nothing precedes it, so "in order" has nothing to say - and a workflow
    whose first step could not be started would be unusable."""
    mod = build(api, "Stepper first step")
    open_module(page, mod)
    settled(page)

    expect(step_at(page, 0)).to_have_attribute("data-reachable", "yes")
    page.get_by_test_id("step-0").click()
    expect(page.get_by_text("clicked: [1/Pick a site]")).to_be_visible()


def test_a_step_already_finished_can_be_gone_back_to(page, api) -> None:
    """"In order" constrains how far forward somebody may go, not whether they
    may return - and a completed step is exactly the one worth re-reading."""
    mod = build(api, "Stepper go back", done=(True, True, False))
    open_module(page, mod)
    settled(page)

    expect(step_at(page, 0)).to_have_attribute("data-state", "completed")
    page.get_by_test_id("step-0").click()
    expect(page.get_by_text("clicked: [1/Pick a site]")).to_be_visible()


def test_an_unreachable_step_is_still_shown(page, api) -> None:
    """A workflow whose later stages were invisible would tell a viewer nothing
    about how much is left, which is half of what p.312 says the widget is for.
    The linear rule is about clicking, not about drawing."""
    mod = build(api, "Stepper shows all")
    open_module(page, mod)
    settled(page)

    expect(steps(page)).to_have_count(3)
    expect(step_at(page, 2)).to_be_visible()
    expect(step_at(page, 2)).to_contain_text("Submit")


# ---- p.313's Template and Show step number -----------------------------------
def test_the_text_template_numbers_every_step(page, api) -> None:
    """p.313's "Text only: Displays ordered numbers for each step"."""
    mod = build(api, "Stepper numbers")
    open_module(page, mod)
    settled(page)

    marks = page.get_by_test_id("step-mark")
    expect(marks.nth(0)).to_have_text("1")
    expect(marks.nth(2)).to_have_text("3")


def test_the_icon_template_drops_the_number_and_keeps_the_name(page, api) -> None:
    """p.313's Icon is a *name*, and this platform has no icon set to draw one
    from - so the name travels as the mark's accessible label rather than being
    lost, the call §210's Object Set Title made for the same reason."""
    mod = build(api, "Stepper icons", {"template": "icons"})
    open_module(page, mod)
    settled(page)

    mark = page.get_by_test_id("step-mark").first
    assert (mark.text_content() or "").strip() == "", mark.text_content()
    expect(mark).to_have_attribute("aria-label", "search")


def test_show_step_number_puts_the_number_back(page, api) -> None:
    """p.313: "toggle on to **also** display step numbers… when set to linear
    stepper type and set to use icons"."""
    mod = build(api, "Stepper icons numbered",
                {"template": "icons", "showStepNumber": True, "stepperType": "linear"})
    open_module(page, mod)
    settled(page)

    mark = page.get_by_test_id("step-mark").first
    expect(mark).to_have_text("1")
    # Still an icon step: the number is *also* displayed, so the name stays.
    expect(mark).to_have_attribute("aria-label", "search")


def test_show_step_number_means_nothing_without_an_order(page, api) -> None:
    """The other half of p.313's condition, and the half a single test would
    have let through: a non-linear workflow has no order for a number to
    mean."""
    mod = build(api, "Stepper icons unordered",
                {"template": "icons", "showStepNumber": True, "stepperType": "non_linear"})
    open_module(page, mod)
    settled(page)

    mark = page.get_by_test_id("step-mark").first
    assert (mark.text_content() or "").strip() == "", mark.text_content()


def test_show_step_number_adds_nothing_to_the_text_template(page, api) -> None:
    """That template already *is* the numbers, so "also display" is a no-op -
    and asserting it is what stops the toggle from growing a second meaning."""
    plain = build(api, "Stepper text plain")
    open_module(page, plain)
    settled(page)
    expect(page.get_by_test_id("step-mark").first).to_have_text("1")

    toggled = build(api, "Stepper text toggled", {"showStepNumber": True})
    open_module(page, toggled)
    settled(page)
    expect(page.get_by_test_id("step-mark").first).to_have_text("1")


# ---- p.313's colours ---------------------------------------------------------
def test_the_completed_and_active_colours_are_painted(page, api) -> None:
    """p.313's Completed color and Active color. Two different colours in one
    document, because a widget painting both states the same shows no progress
    at all - which is the widget's entire job."""
    mod = build(api, "Stepper colours",
                {"completedColour": "rgb(1, 2, 3)", "activeColour": "rgb(4, 5, 6)"},
                done=(True, False, False))
    open_module(page, mod)
    settled(page)

    marks = page.get_by_test_id("step-mark")
    expect(marks.nth(0)).to_have_css("background-color", "rgb(1, 2, 3)")
    expect(marks.nth(1)).to_have_css("background-color", "rgb(4, 5, 6)")
    # The upcoming step takes neither, so a rule that painted every mark would
    # be visible here rather than merely plausible.
    upcoming = marks.nth(2).evaluate("el => getComputedStyle(el).backgroundColor")
    assert upcoming not in ("rgb(1, 2, 3)", "rgb(4, 5, 6)"), upcoming


def test_a_document_with_no_colours_still_tells_the_states_apart(page, api) -> None:
    """The defaults live in `stepper.ts` and are asserted there by name; what a
    browser adds is that they reach the page and differ once drawn."""
    mod = build(api, "Stepper default colours", done=(True, False, False))
    open_module(page, mod)
    settled(page)

    marks = page.get_by_test_id("step-mark")
    completed = marks.nth(0).evaluate("el => getComputedStyle(el).backgroundColor")
    active = marks.nth(1).evaluate("el => getComputedStyle(el).backgroundColor")
    upcoming = marks.nth(2).evaluate("el => getComputedStyle(el).backgroundColor")
    assert completed != active, completed
    assert completed != upcoming and active != upcoming, (completed, active, upcoming)


# ---- the builder -------------------------------------------------------------
def test_a_step_s_completion_variable_counts_as_a_usage(page, api) -> None:
    """**The larger half of this unit.** A step's binding lives inside the
    `steps` array, where the flat `REFERENCE_PROPS` scan cannot see it - so
    before `NESTED_REFERENCE_PROPS` the panel reported the variable as used by
    nothing and offered to delete it, after which every step read as never
    completed. §185's and §190's failure, by a route neither of their guards
    reaches."""
    mod = build(api, "Stepper usage")
    open_builder(page, mod)
    settled(page)

    page.get_by_role("button", name="Variables", exact=False).first.click()
    row = page.locator(".vars-row", has_text="Step 1 done").first
    expect(row.locator(".vars-usage")).not_to_have_text("unused")
    # And a variable the stepper does *not* name still reads as unused, so the
    # check above is about the binding rather than about the widget existing.
    spare = page.locator(".vars-row", has_text="Clock").first
    expect(spare.locator(".vars-usage")).to_have_text("unused")


def test_the_settings_panel_offers_only_boolean_variables(page, api) -> None:
    """p.313 says "a boolean variable", and a picker offering the string ones
    would be a binding the module can hold and the widget can never read as
    complete."""
    mod = build(api, "Stepper settings")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Stepper").first.click()
    picker = page.get_by_test_id("stepper-done-0")
    expect(picker).to_be_visible()
    options = picker.locator("option").all_text_contents()
    assert "Step 1 done" in options, options
    assert "Mark" not in options, options


def test_the_step_editor_adds_and_removes_steps(page, api) -> None:
    """p.313's Steps are a list an author edits, and the editor is the only
    place the `steps` prop is written - so a save that loses one is a workflow
    silently missing a stage."""
    mod = build(api, "Stepper editor")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Stepper").first.click()
    expect(page.get_by_test_id("stepper-steps")).to_be_visible()
    page.get_by_test_id("stepper-add").click()
    expect(page.get_by_test_id("stepper-label-3")).to_have_value("Step 4")
    expect(steps(page)).to_have_count(4)

    page.get_by_test_id("stepper-remove-0").click()
    expect(steps(page)).to_have_count(3)
    expect(page.get_by_test_id("stepper-label-0")).to_have_value("Confirm details")


@pytest.mark.parametrize("mode", ["linear", "non_linear"])
def test_no_step_is_clickable_in_the_builder(page, api, mode: str) -> None:
    """Edit mode is for authoring, so a click selects the widget rather than
    running its events - including on a step p.312's rule would allow."""
    mod = build(api, f"Stepper builder {mode}", {"stepperType": mode})
    open_builder(page, mod)
    settled(page)

    expect(page.get_by_test_id("step-0")).to_be_disabled()
