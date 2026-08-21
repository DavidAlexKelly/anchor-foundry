"""The Widget setup tab, organised variables-first (parity `workshop.md` §2;
Foundry p.65-67).

> "The core configuration options of a widget live within the Widget setup tab.
> This is where a module builder will configure the input and output variables
> of a widget … as well as any additional configuration and display options."
> (p.65)

The panel was a flat list of whatever each widget's author wrote first. p.65's
order is the order somebody has to *think* in - the set that populates the
widget, the options that set makes answerable, then what the widget produces -
and Foundry's own worked example is a Filter List, which is why this file
configures one.

**The claim that needs a browser is p.66's progressive disclosure**:

> "This configuration option is revealed in more detail once the Object Set is
> populated; it will then show the property types seen within the initial
> object set." (p.66)

Configuration revealed too early is a panel of empty dropdowns; too late is a
widget that looks unfinishable. Both are things a person sees and neither
raises anything, so both need a real render.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import open_builder


@pytest.fixture
def module(api):
    """A Filter List with **nothing bound**, which is p.65's own starting
    point: "the initial state of a newly added and not yet configured Filter
    List widget".

    Per test rather than shared: the disclosure test binds the object set, and
    a shared module would hand the next test a widget somebody had already
    configured - the fixture bug this repo has now paid for three times.
    """
    mod = Module(api, "Widget setup order")
    type_id = mod.object_type(
        columns=["id", "name"],
        rows=[{"id": "R1", "name": "Ada"}],
        key="id", title="name",
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "flt": {"resolvedName": "CanvasFilterList",
                    "props": {"objectSetVariable": None, "variable": None,
                              "properties": "", "title": ""}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All",
                      "object_set": object_set(type_id)},
            "v_clauses": {"id": "v_clauses", "kind": "array", "label": "Clauses"},
        },
        "events": {},
    })
    return mod


def select_widget(page):
    """Through the Layout panel, for the reason the config-tab suite gives: a
    canvas click lands on whatever is under the pointer."""
    page.locator(".canvas-tree-row").first.click()
    expect(page.get_by_test_id("widget-setup")).to_be_visible(timeout=15000)


def test_the_sections_are_in_p65s_order(page, module) -> None:
    """Inputs, then configuration, then outputs - and asserted as an *order*
    rather than as three presences, because a panel with all three sections in
    the wrong order passes every check that only asks whether they exist."""
    open_builder(page, module)
    select_widget(page)
    page.get_by_test_id("setup-inputs").wait_for()

    # Bind the set so all three sections are on screen at once.
    page.get_by_test_id("setup-inputs").locator("select").select_option("v_all")
    expect(page.get_by_test_id("setup-configuration")).to_be_visible(timeout=15000)

    sections = page.locator(
        '[data-testid="setup-inputs"], [data-testid="setup-configuration"], '
        '[data-testid="setup-outputs"]'
    )
    order = [
        sections.nth(i).get_attribute("data-testid") for i in range(sections.count())
    ]
    assert order == ["setup-inputs", "setup-configuration", "setup-outputs"], order


def test_the_configuration_waits_for_its_input(page, module) -> None:
    """**p.66's disclosure.** The filter options are read from the set's object
    type, so before a set is bound there is nothing to list - and the panel
    says which input it is waiting on rather than showing an empty control."""
    open_builder(page, module)
    select_widget(page)

    expect(page.get_by_test_id("setup-configuration")).to_have_count(0)
    waiting = page.get_by_test_id("setup-waiting")
    expect(waiting).to_be_visible()
    expect(waiting).to_contain_text("object set")

    page.get_by_test_id("setup-inputs").locator("select").select_option("v_all")
    expect(page.get_by_test_id("setup-configuration")).to_be_visible(timeout=15000)
    expect(page.get_by_test_id("setup-waiting")).to_have_count(0)


def test_the_output_stays_available_before_the_input_is_bound(
    page, module
) -> None:
    """**The half that keeps disclosure from being a wall.**

    p.66 hides the *configuration* until the object set is populated. It says
    nothing about the output, and p.67 is explicit that a Filter List's output
    exists from the moment the widget is added - "by default, an output
    variable will be created when adding a Filter List widget". Hiding it
    behind the input would make the widget look less finished than it is.
    """
    open_builder(page, module)
    select_widget(page)

    expect(page.get_by_test_id("setup-waiting")).to_be_visible()
    expect(page.get_by_test_id("setup-outputs")).to_be_visible()


def test_a_widget_with_no_output_shows_no_outputs_heading(page, api) -> None:
    """An empty heading is a promise of a control that does not exist. The
    time series reads a set and draws it; it produces nothing."""
    mod = Module(api, "Widget setup order (series)")
    type_id = mod.object_type(
        columns=["id", "name"], rows=[{"id": "R1", "name": "Ada"}],
        key="id", title="name",
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "ts": {"resolvedName": "CanvasTimeSeries",
                   "props": {"objectSetVariable": "v_all", "interval": "day",
                             "title": ""}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All",
                      "object_set": object_set(type_id)},
        },
        "events": {},
    })

    open_builder(page, mod)
    select_widget(page)
    expect(page.get_by_test_id("setup-inputs")).to_be_visible()
    # Its set is already bound, so the configuration is showing...
    expect(page.get_by_test_id("setup-configuration")).to_be_visible()
    # ...and there is no Outputs section at all.
    expect(page.get_by_test_id("setup-outputs")).to_have_count(0)


# ---- the object-set family (§179) -------------------------------------------
def test_an_object_table_reveals_its_configuration_from_either_input(
    page, api
) -> None:
    """**The rule §178 did not need and this one does.**

    An Object table is populated *either* by a bound object set variable *or*
    by an object type picked directly. Waiting for both would be waiting for
    something nobody is meant to supply - the configuration would never
    appear, and the widget would look permanently unfinishable.

    Bound by the object *type* here, deliberately: it is the half a rule
    written for the Filter List's single input would get wrong.
    """
    mod = Module(api, "Widget setup order (table)")
    type_id = mod.object_type(
        columns=["id", "name"], rows=[{"id": "R1", "name": "Ada"}],
        key="id", title="name",
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "tbl": {"resolvedName": "CanvasObjectTable",
                    "props": {"objectTypeId": type_id, "objectSetVariable": None,
                              "filterProperty": None, "filterParameter": None,
                              "searchParameter": None, "pageSize": 25,
                              "columns": "", "sort": "recent"}},
        }),
        "variables": {},
        "events": {},
    })

    open_builder(page, mod)
    select_widget(page)
    expect(page.get_by_test_id("setup-inputs")).to_be_visible()
    expect(page.get_by_test_id("setup-configuration")).to_be_visible()
    expect(page.get_by_test_id("setup-waiting")).to_have_count(0)


def test_an_object_table_with_neither_input_says_it_takes_either(
    page, api
) -> None:
    """And the message reads as the choice it is. Naming only the first would
    send somebody to fill in a field they do not need and leave the one they
    do."""
    mod = Module(api, "Widget setup order (empty table)")
    mod.object_type(
        columns=["id", "name"], rows=[{"id": "R1", "name": "Ada"}],
        key="id", title="name",
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "tbl": {"resolvedName": "CanvasObjectTable",
                    "props": {"objectTypeId": None, "objectSetVariable": None,
                              "filterProperty": None, "filterParameter": None,
                              "searchParameter": None, "pageSize": 25,
                              "columns": "", "sort": "recent"}},
        }),
        "variables": {},
        "events": {},
    })

    open_builder(page, mod)
    select_widget(page)
    waiting = page.get_by_test_id("setup-waiting")
    expect(waiting).to_be_visible()
    expect(waiting).to_contain_text("an object set or an object type")
    expect(page.get_by_test_id("setup-configuration")).to_have_count(0)


def test_a_pivot_table_shows_all_three_sections(page, api) -> None:
    """The widget that shows why there are three: the set populates the grid,
    the axes are what that set makes answerable, and the drill-down variable
    is "the data that is then produced and output by the widget" (p.65)."""
    mod = Module(api, "Widget setup order (pivot)")
    type_id = mod.object_type(
        columns=["id", "name"], rows=[{"id": "R1", "name": "Ada"}],
        key="id", title="name",
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "pv": {"resolvedName": "CanvasPivotTable",
                   "props": {"objectSetVariable": "v_all", "rowProperty": None,
                             "columnProperty": None, "drilldownVariable": None,
                             "title": ""}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All",
                      "object_set": object_set(type_id)},
        },
        "events": {},
    })

    open_builder(page, mod)
    select_widget(page)
    for section in ("inputs", "configuration", "outputs"):
        expect(page.get_by_test_id(f"setup-{section}")).to_be_visible()


def test_a_metric_card_asks_for_its_set_before_its_label(page, api) -> None:
    """**The reordering p.65 is actually for.** The label describes a number
    this widget cannot produce until something says which set to count, so
    asking for it first asks somebody to name a thing they have not chosen.

    Asserted as containment rather than by position: the claim is that the set
    is an *input* and the label is *configuration*, which is what p.65
    separates - not that one happens to be drawn above the other.
    """
    mod = Module(api, "Widget setup order (metric)")
    type_id = mod.object_type(
        columns=["id", "name"], rows=[{"id": "R1", "name": "Ada"}],
        key="id", title="name",
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "mc": {"resolvedName": "CanvasMetricCard",
                   "props": {"objectSetVariable": "v_all", "aggregation": "count",
                             "property": None, "label": ""}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All",
                      "object_set": object_set(type_id)},
        },
        "events": {},
    })

    open_builder(page, mod)
    select_widget(page)
    expect(page.get_by_test_id("setup-inputs")).to_contain_text("Object set variable")
    expect(page.get_by_test_id("setup-configuration")).to_contain_text("Label")
    expect(page.get_by_test_id("setup-inputs")).not_to_contain_text("Label")


# ---- the widgets that are not populated by an object set (§180) --------------
def test_a_parameter_control_leads_with_what_it_produces(page, api) -> None:
    """**The widget that inverts p.65's shape**, and the reason the sections
    are three rather than a fixed order of two.

    A Filter produces without consuming: its parameter name is what every
    other widget reads, and it has no input at all. So there is no Inputs
    section to lead with, nothing for the configuration to wait on, and the
    panel opens on Outputs. A rule that made configuration wait for an input
    would leave this widget permanently unconfigurable.
    """
    mod = Module(api, "Widget setup order (parameter)")
    mod.define({
        "format": 2,
        "layout": layout({
            "ctl": {"resolvedName": "CanvasParameterControl",
                    "props": {"name": "region", "label": "Region",
                              "control": "text", "datasetId": None,
                              "column": None}},
        }),
        "variables": {},
        "events": {},
    })

    open_builder(page, mod)
    select_widget(page)
    outputs = page.get_by_test_id("setup-outputs")
    expect(outputs).to_be_visible()
    expect(outputs).to_contain_text("Parameter name")
    # Configuration is on screen straight away - it is not waiting for
    # anything, because there is nothing it could wait for.
    expect(page.get_by_test_id("setup-configuration")).to_be_visible()
    expect(page.get_by_test_id("setup-waiting")).to_have_count(0)
    expect(page.get_by_test_id("setup-inputs")).to_have_count(0)


def test_a_dataset_table_waits_for_its_dataset(page, api) -> None:
    """p.66's disclosure with a dataset in the object set's place: the filter
    column is read from the dataset's schema, so before one is chosen there
    are no columns to list."""
    mod = Module(api, "Widget setup order (dataset)")
    # For the dataset the picker offers: `object_type` uploads its seed CSV
    # into this module's project, which is a dataset like any other.
    mod.object_type(
        columns=["id", "name"], rows=[{"id": "R1", "name": "Ada"}],
        key="id", title="name",
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "dt": {"resolvedName": "CanvasDatasetTable",
                   "props": {"datasetId": None, "filterColumn": None,
                             "filterParameter": None, "filterOperator": "equals"}},
        }),
        "variables": {},
        "events": {},
    })

    open_builder(page, mod)
    select_widget(page)
    waiting = page.get_by_test_id("setup-waiting")
    expect(waiting).to_be_visible()
    expect(waiting).to_contain_text("a dataset")
    expect(page.get_by_test_id("setup-configuration")).to_have_count(0)

    page.get_by_test_id("setup-inputs").locator("select").select_option(index=1)
    expect(page.get_by_test_id("setup-configuration")).to_be_visible(timeout=15000)


def test_an_action_form_asks_for_the_action_before_what_it_edits(page, api) -> None:
    """**The panel whose two fields look alike and are not.**

    Both are dropdowns; only one is an input. Until an action type is chosen
    there is no form, so "which variable does it edit" is a question about
    nothing - and leaving *that* unset is a real answer ("whatever the viewer
    picks"), which is why it sits under configuration rather than beside the
    action as a second thing to supply.
    """
    mod = Module(api, "Widget setup order (action form)")
    type_id = mod.object_type(
        columns=["id", "name"], rows=[{"id": "R1", "name": "Ada"}],
        key="id", title="name",
    )
    api.call(
        "POST",
        f"/workspaces/{mod.workspace_id}/action-types",
        {
            "object_type_id": type_id,
            "api_name": f"rename_{uuid.uuid4().hex[:8]}",
            "display_name": "Rename",
            "editable_properties": ["name"],
        },
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "frm": {"resolvedName": "CanvasActionForm",
                    "props": {"actionTypeId": None, "subjectVariable": None}},
        }),
        "variables": {},
        "events": {},
    })

    open_builder(page, mod)
    select_widget(page)
    waiting = page.get_by_test_id("setup-waiting")
    expect(waiting).to_be_visible()
    expect(waiting).to_contain_text("an action")
    expect(page.get_by_test_id("setup-configuration")).to_have_count(0)

    page.get_by_test_id("setup-inputs").locator("select").select_option(index=1)
    configuration = page.get_by_test_id("setup-configuration")
    expect(configuration).to_be_visible(timeout=15000)
    expect(configuration).to_contain_text("Edits")
    expect(page.get_by_test_id("setup-inputs")).not_to_contain_text("Edits")


# ---- the module-composition widgets, and the Button (§181) -------------------
def child_module(api, name: str) -> Module:
    """A one-object module that publishes an interface variable, which is what
    an Embedded module maps onto and a Loop hands each object to (p.127,
    p.134)."""
    card = Module(api, name)
    type_id = card.object_type(
        columns=["id", "name"], rows=[{"id": "R1", "name": "Ada"}],
        key="id", title="name",
    )
    card.define({
        "format": 2,
        "layout": layout({
            "txt": {"resolvedName": "CanvasText", "props": {"tag": "p", "text": "CARD"}},
        }),
        "variables": {
            "v_obj": {"id": "v_obj", "kind": "single_object", "label": "The object",
                      "external_id": "obj",
                      "interface": {"display_name": "Object", "required": True}},
        },
        "events": {},
    })
    card.type_id = type_id
    return card


def test_an_embedded_module_reveals_its_interface_once_a_module_is_chosen(
    page, api
) -> None:
    """**p.127 states this widget's disclosure in its own words**, and puts the
    mapping on the configuration side while it is at it:

    > "Once a child module is selected, the module interface for the child
    > module will be shown in the widget configuration panel."

    The mapping already disappeared before a module was chosen — by rendering
    `null`, which is the silent version of the same thing. Under p.66's rule it
    says which input it is waiting on instead.
    """
    card = child_module(api, "Widget setup order (child)")
    host = Module(api, "Widget setup order (embed)", beside=card)
    host.define({
        "format": 2,
        "layout": layout({
            "emb": {"resolvedName": "CanvasEmbeddedModule",
                    "props": {"moduleId": None, "interface": {}, "title": ""}},
        }),
        "variables": {},
        "events": {},
    })

    open_builder(page, host)
    select_widget(page)
    waiting = page.get_by_test_id("setup-waiting")
    expect(waiting).to_be_visible()
    expect(waiting).to_contain_text("a module")
    expect(page.get_by_test_id("setup-configuration")).to_have_count(0)

    page.get_by_test_id("setup-inputs").locator("select").select_option(card.app_id)
    configuration = page.get_by_test_id("setup-configuration")
    expect(configuration).to_be_visible(timeout=15000)
    # p.127's mapping, and it is in the configuration section rather than
    # beside the module picker.
    expect(configuration).to_contain_text("Object", timeout=15000)


def test_a_loop_waits_for_the_set_and_the_module_together(page, api) -> None:
    """**The first widget that needs `requires` in its original all-of form.**

    §179 taught `requires` a *choice* for the Object table, which takes a set
    *or* a type. A Loop takes a set **and** a module: "Receives each object"
    reads the module's published interface (p.134) and the paging options count
    items from the set, so neither input alone leaves anything to configure.

    The message is asserted for its conjunction, not just for both names —
    "a set or a module" contains both words too, and would tell somebody they
    were finished when they were half finished.
    """
    card = child_module(api, "Widget setup order (loop child)")
    host = Module(api, "Widget setup order (loop)", beside=card)
    host.define({
        "format": 2,
        "layout": layout({
            "loop": {"resolvedName": "CanvasLoopSection",
                     "props": {"objectSetVariable": None, "moduleId": None,
                               "itemVariable": None, "interface": {},
                               "paging": "limit", "maxItems": 12, "pageSize": 12,
                               "display": "list", "maxColumns": 3,
                               "minCardWidth": 220}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All",
                      "object_set": object_set(card.type_id)},
        },
        "events": {},
    })

    open_builder(page, host)
    select_widget(page)
    waiting = page.get_by_test_id("setup-waiting")
    expect(waiting).to_be_visible()
    expect(waiting).to_contain_text("an object set and a module")
    expect(page.get_by_test_id("setup-configuration")).to_have_count(0)

    # One input is not enough - the half-bound state is the one an all-of rule
    # gets wrong, and it is invisible unless something stops here.
    page.get_by_test_id("loop-set").select_option("v_all")
    expect(page.get_by_test_id("setup-waiting")).to_be_visible()
    expect(page.get_by_test_id("setup-waiting")).to_contain_text("a module")
    expect(page.get_by_test_id("setup-configuration")).to_have_count(0)

    page.get_by_test_id("loop-module").select_option(card.app_id)
    configuration = page.get_by_test_id("setup-configuration")
    expect(configuration).to_be_visible(timeout=15000)
    expect(page.get_by_test_id("loop-item")).to_be_visible()
    expect(page.get_by_test_id("setup-waiting")).to_have_count(0)


def test_a_button_leads_with_the_variable_it_reads(page, api) -> None:
    """p.65 in full: the tab configures "the input and output variables of a
    widget … **as well as** any additional configuration and display options".

    A Button's label, icon and style are display options by that sentence's own
    words; the variable it reads to decide whether it is pressable is an input,
    and so goes first. There is no `requires` — "Always" is a real answer, so a
    panel that waited for it would never open.
    """
    mod = Module(api, "Widget setup order (button)")
    mod.define({
        "format": 2,
        "layout": layout({
            "btn": {"resolvedName": "CanvasButton",
                    "props": {"label": "Go", "icon": "", "style": "primary",
                              "enabledVariable": None}},
        }),
        "variables": {
            "v_ok": {"id": "v_ok", "kind": "string", "label": "Ready"},
        },
        "events": {},
    })

    open_builder(page, mod)
    select_widget(page)
    inputs = page.get_by_test_id("setup-inputs")
    expect(inputs).to_contain_text("Pressable when")
    expect(inputs).not_to_contain_text("Label")
    expect(page.get_by_test_id("setup-configuration")).to_contain_text("Label")
    # Nothing is bound and the configuration is on screen regardless.
    expect(page.get_by_test_id("setup-waiting")).to_have_count(0)
