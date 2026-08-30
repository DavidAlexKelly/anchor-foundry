"""The typed variable graph (roadmap phase 2, item 1.2; decision 0002).

No database. This is a graph and a set of pure transforms.

What is under test is the set of failures decision 0002 exists to remove, each
of which Canvas commits today:

  - a widget bound to a variable nothing declares (reads as "no filter", so the
    widget shows *more* rows than it should, silently and forever),
  - a variable deleted out from under the things using it,
  - a derivation that depends on itself.

Plus the semantics that two implementations would get quietly different -
what `if_else` calls true, and what `cast` refuses rather than blanking.
"""
from __future__ import annotations

import os
import uuid
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import workshop_variables as wv  # noqa: E402


def var(vid: str, kind: str = "string", **extra) -> dict:
    return {"id": vid, "kind": kind, "label": extra.pop("label", vid), **extra}


def module(variables: dict, layout: dict | None = None) -> dict:
    return {"format": 2, "layout": layout or {}, "variables": variables, "events": {}}


def node(props: dict) -> dict:
    return {"type": {"resolvedName": "CanvasParameterControl"}, "props": props}


# ---- declaring ---------------------------------------------------------------
def test_a_plain_variable_round_trips() -> None:
    parsed = wv.parse({"v_a": var("v_a", label="Region", default="north")})
    assert parsed["v_a"].label == "Region"
    assert parsed["v_a"].default == "north"
    assert parsed["v_a"].derived is False


def test_a_key_that_disagrees_with_its_id_is_refused() -> None:
    """Two statements of the same fact, and no correct reading when they
    differ: references use the id, the builder indexes by the key."""
    with pytest.raises(wv.VariableError, match="key and the id must match"):
        wv.parse({"v_a": var("v_b")})


def test_an_unknown_kind_names_the_ones_that_exist() -> None:
    with pytest.raises(wv.VariableError, match="object_set"):
        wv.parse({"v_a": var("v_a", kind="colour")})


def test_a_variable_without_a_label_is_refused() -> None:
    """The label is what the builder shows and what refusals name. A blank one
    makes every message about this variable unreadable."""
    with pytest.raises(wv.VariableError, match="needs a label"):
        wv.parse({"v_a": {"id": "v_a", "kind": "string", "label": "  "}})


# ---- derivations -------------------------------------------------------------
def test_derived_variables_compute_in_dependency_order() -> None:
    variables = wv.parse(
        {
            "v_first": var("v_first", label="First"),
            "v_last": var("v_last", label="Last"),
            "v_full": var(
                "v_full",
                label="Full name",
                derivation={
                    "transform": "concat",
                    "inputs": ["v_first", "v_last"],
                    "config": {"separator": " "},
                },
            ),
            "v_greeting": var(
                "v_greeting",
                label="Greeting",
                derivation={
                    "transform": "concat",
                    "inputs": ["v_hello", "v_full"],
                    "config": {"separator": ", "},
                },
            ),
            "v_hello": var("v_hello", label="Hello", default="Hi"),
        }
    )
    resolved = wv.evaluate(variables, {"v_first": "Ada", "v_last": "Lovelace"})
    assert resolved["v_full"] == "Ada Lovelace"
    # Chained: a derivation reading another derivation, declared before it.
    assert resolved["v_greeting"] == "Hi, Ada Lovelace"


def test_evaluation_order_is_the_same_every_time() -> None:
    """A recomputation order that varied run to run would make a bug in a
    transform reproduce only sometimes."""
    variables = wv.parse(
        {
            "v_a": var("v_a"),
            "v_b": var("v_b"),
            "v_c": var("v_c", derivation={"transform": "concat", "inputs": ["v_a", "v_b"]}),
        }
    )
    orders = {tuple(wv.evaluation_order(variables)) for _ in range(5)}
    assert len(orders) == 1
    order = wv.evaluation_order(variables)
    assert order.index("v_c") > max(order.index("v_a"), order.index("v_b"))


def test_a_cycle_is_refused_and_named(caplog) -> None:
    """The precedent is Models item 7. The reason is sharper here: there is no
    run loop to notice, so a cycle is either an infinite recompute in the
    browser or a value depending on its own previous value."""
    with pytest.raises(wv.VariableError) as raised:
        wv.parse(
            {
                "v_a": var("v_a", label="Alpha",
                           derivation={"transform": "concat", "inputs": ["v_b"]}),
                "v_b": var("v_b", label="Beta",
                           derivation={"transform": "concat", "inputs": ["v_a"]}),
            }
        )
    message = str(raised.value)
    assert "loop" in message
    # Named by label, not by id: the person reading has never seen v_a.
    assert "Alpha" in message and "Beta" in message


def test_a_variable_that_reads_itself_is_refused() -> None:
    with pytest.raises(wv.VariableError, match="reads itself"):
        wv.parse({"v_a": var("v_a", label="Alpha",
                             derivation={"transform": "concat", "inputs": ["v_a"]})})


def test_a_derivation_reading_a_variable_that_does_not_exist_is_refused() -> None:
    with pytest.raises(wv.VariableError, match="does not declare"):
        wv.parse({"v_a": var("v_a", label="Alpha",
                             derivation={"transform": "concat", "inputs": ["v_gone"]})})


def test_a_transform_configured_with_the_wrong_number_of_inputs_is_refused() -> None:
    """At save rather than at view: an app that renders a blank card because
    if_else got two inputs instead of three is a bug with no visible cause."""
    with pytest.raises(wv.VariableError, match="exactly three inputs"):
        wv.parse(
            {
                "v_a": var("v_a"),
                "v_b": var("v_b"),
                "v_c": var("v_c", derivation={"transform": "if_else",
                                              "inputs": ["v_a", "v_b"]}),
            }
        )


def test_the_ontology_transform_says_it_is_not_built_rather_than_failing_oddly() -> None:
    """An aggregate over a set needs the instance store, so it is a round trip
    rather than a pure function. Returning None for it would make every caller
    guess which of its results were real.

    `object_property` used to be the other example here and is now built (§84):
    its premise was that a `single_object` variable holds a key to fetch, and
    it holds the object the viewer picked, so there is no round trip to wait
    for. See the tests at the bottom of this file."""
    with pytest.raises(wv.VariableError, match="not built yet"):
        wv.parse({"v_a": var("v_a", derivation={"transform": "object_set_aggregation"})})


# ---- what the transforms mean ------------------------------------------------
def test_a_value_supplied_for_a_derived_variable_is_ignored() -> None:
    """A derived variable is a function of its inputs. Honouring an override
    would let one document show two different things depending on which the
    reader believed."""
    variables = wv.parse(
        {
            "v_a": var("v_a"),
            "v_b": var("v_b", derivation={"transform": "concat", "inputs": ["v_a"]}),
        }
    )
    resolved = wv.evaluate(variables, {"v_a": "real", "v_b": "smuggled"})
    assert resolved["v_b"] == "real"


def test_if_else_treats_zero_and_empty_string_as_values_not_as_absence() -> None:
    """Deliberately not Python truthiness. A numeric filter of zero is a thing
    somebody typed; treating it as "nothing entered" would make the app behave
    as though the filter were off."""
    variables = wv.parse(
        {
            "v_cond": var("v_cond", kind="number"),
            "v_yes": var("v_yes", default="yes"),
            "v_no": var("v_no", default="no"),
            "v_out": var("v_out", derivation={"transform": "if_else",
                                              "inputs": ["v_cond", "v_yes", "v_no"]}),
        }
    )
    assert wv.evaluate(variables, {"v_cond": 0})["v_out"] == "yes"
    assert wv.evaluate(variables, {"v_cond": ""})["v_out"] == "yes"
    assert wv.evaluate(variables, {"v_cond": False})["v_out"] == "no"
    assert wv.evaluate(variables, {})["v_out"] == "no", "absent is the only absence"


def test_concat_renders_nothing_as_nothing_rather_than_as_debris() -> None:
    variables = wv.parse(
        {
            "v_a": var("v_a"),
            "v_b": var("v_b"),
            "v_c": var("v_c", derivation={"transform": "concat", "inputs": ["v_a", "v_b"],
                                          "config": {"separator": "-"}}),
        }
    )
    assert wv.evaluate(variables, {"v_a": "north"})["v_c"] == "north-"
    assert "None" not in str(wv.evaluate(variables, {})["v_c"])


def test_concat_writes_booleans_the_way_the_rest_of_the_stack_does() -> None:
    """`str(True)` is "True"; every other layer here speaks JSON."""
    variables = wv.parse(
        {
            "v_a": var("v_a", kind="boolean"),
            "v_c": var("v_c", derivation={"transform": "concat", "inputs": ["v_a"]}),
        }
    )
    assert wv.evaluate(variables, {"v_a": True})["v_c"] == "true"


def test_a_cast_that_cannot_convert_refuses_and_names_the_value() -> None:
    """Blanking would show as an empty card, and the reader would go looking at
    the widget rather than at the variable feeding it."""
    variables = wv.parse(
        {
            "v_a": var("v_a", label="Capacity"),
            "v_n": var("v_n", kind="number", label="Capacity as number",
                       derivation={"transform": "cast", "inputs": ["v_a"],
                                   "config": {"to": "number"}}),
        }
    )
    assert wv.evaluate(variables, {"v_a": "42"})["v_n"] == 42
    with pytest.raises(wv.VariableError, match="banana"):
        wv.evaluate(variables, {"v_a": "banana"})


def test_a_cast_of_nothing_is_nothing_not_a_refusal() -> None:
    """An unset filter is not a conversion failure. Refusing here would make an
    app unopenable until the viewer had touched every control."""
    variables = wv.parse(
        {
            "v_a": var("v_a"),
            "v_n": var("v_n", kind="number",
                       derivation={"transform": "cast", "inputs": ["v_a"],
                                   "config": {"to": "number"}}),
        }
    )
    assert wv.evaluate(variables, {})["v_n"] is None


def test_is_empty_and_its_negation_agree() -> None:
    variables = wv.parse(
        {
            "v_a": var("v_a"),
            "v_e": var("v_e", kind="boolean",
                       derivation={"transform": "is_empty", "inputs": ["v_a"]}),
            "v_f": var("v_f", kind="boolean",
                       derivation={"transform": "is_not_empty", "inputs": ["v_a"]}),
        }
    )
    for value in [None, "", [], "north", 0]:
        resolved = wv.evaluate(variables, {"v_a": value})
        assert resolved["v_e"] is not resolved["v_f"], f"disagreed on {value!r}"


# ---- what uses what ----------------------------------------------------------
def test_usages_finds_widgets_and_derivations() -> None:
    variables = wv.parse(
        {
            "v_region": var("v_region", label="Region"),
            "v_label": var("v_label", label="Label",
                           derivation={"transform": "concat", "inputs": ["v_region"]}),
        }
    )
    layout = {
        "ROOT": {"type": {"resolvedName": "CanvasContainer"}, "nodes": ["f1", "m1"]},
        "f1": node({"filterParameter": "v_region"}),
        "m1": node({"searchParameter": "v_region"}),
    }
    found = wv.usages(layout, variables)
    assert len(found["v_region"]) == 3
    assert {u["prop"] for u in found["v_region"]} == {
        "filterParameter", "searchParameter", "derivation",
    }
    assert found["v_label"] == []


def test_deleting_a_variable_a_widget_uses_is_refused_at_save() -> None:
    """The failure decision 0002 exists to remove. Today the widget silently
    reads as "no filter" - so it shows everything, which looks like data rather
    than like a bug."""
    layout = {"f1": node({"filterParameter": "v_region"})}
    with pytest.raises(wv.VariableError) as raised:
        wv.validate_module(module({}, layout))
    assert "v_region" in str(raised.value)
    assert "show everything" in str(raised.value)


def test_deleting_a_variable_a_derivation_reads_is_refused_the_same_way() -> None:
    with pytest.raises(wv.VariableError, match="does not declare"):
        wv.validate_module(
            module({"v_b": var("v_b", label="Beta",
                               derivation={"transform": "concat", "inputs": ["v_region"]})})
        )


def test_every_prop_that_names_a_variable_is_checked() -> None:
    """The list of reference props is the whole of what protects a binding, and
    a prop missing from it is a binding nothing checks. Two were missing:
    `subjectVariable`, since the inline action form arrived in §87, and
    `drilldownVariable` when the chart gained one.

    Written as a loop over the list rather than a case each, because the thing
    that goes wrong is somebody adding a ninth prop and not a ninth test."""
    for prop in wv.REFERENCE_PROPS:
        layout = {"w1": node({prop: "v_gone"})}
        with pytest.raises(wv.VariableError, match="v_gone") as raised:
            wv.validate_module(module({}, layout))
        assert "does not declare" in str(raised.value), prop


# ---- nested references (p.313's Stepper) -------------------------------------
def test_a_variable_named_inside_a_list_prop_is_checked() -> None:
    """§219's Stepper is the first widget whose bindings are not top-level props.

    A step's "Is completed" variable lives inside the `steps` array, where the
    flat scan cannot see it - so before `NESTED_REFERENCE_PROPS` this saved
    happily and the widget then read a variable the module does not declare.
    """
    # A loop over an empty catalogue passes - the failure this whole unit is
    # about is a binding nobody catalogued, so the loop cannot be the only
    # thing asserting the catalogue is not empty.
    assert wv.NESTED_REFERENCE_PROPS.get("steps") == ("completedVariable",)
    for prop, inners in wv.NESTED_REFERENCE_PROPS.items():
        for inner in inners:
            layout = {"w1": node({prop: [{"label": "One", inner: "v_gone"}]})}
            with pytest.raises(wv.VariableError, match="v_gone") as raised:
                wv.validate_module(module({}, layout))
            assert "does not declare" in str(raised.value), f"{prop}.{inner}"


def test_a_variable_named_inside_a_list_prop_counts_as_a_usage() -> None:
    """The other half, and the one that bites quietly: a usage nothing counts
    is a variable the Variables panel offers to delete, after which every step
    reads as never completed and nothing anywhere says why."""
    layout = {"w1": node({"steps": [
        {"label": "One"},
        {"label": "Two", "completedVariable": "v_done"},
    ]})}
    found = wv.usages(layout, wv.parse({"v_done": var("v_done", kind="boolean")}))
    # Named by index, not just by node: "used by the Stepper" is not enough to
    # find which step to unbind before deleting.
    assert found["v_done"] == [{"node": "w1", "prop": "steps[1].completedVariable"}]


def test_a_list_prop_holding_junk_names_no_variables() -> None:
    """The tolerance §212 argued for, one level deeper. A saved document can
    hold anything, and a scan that threw on it would make a module with one bad
    step impossible to open rather than impossible to save."""
    layout = {"w1": node({"steps": "not a list"}), "w2": node({"steps": [None, 7, {}]})}
    assert wv.usages(layout, wv.parse({"v_done": var("v_done", kind="boolean")})) == {
        "v_done": []
    }
    assert wv.dangling_references(layout, {}) == []


def test_a_nested_prop_that_is_not_catalogued_is_not_a_reference() -> None:
    """Only the catalogued inner keys carry variable ids. A step's `label`
    holding the text `v_done` is a label, and refusing that save - or counting
    it as a usage - would be the mirror of the mistake above."""
    layout = {"w1": node({"steps": [{"label": "v_gone", "icon": "v_gone"}]})}
    assert wv.validate_module(module({}, layout)) == {}


def test_a_prop_that_merely_looks_like_a_reference_is_not_one() -> None:
    """Only the declared reference props carry variable ids. A column called
    `v_region` in somebody's data is not a binding, and treating it as one
    would refuse saves for no reason."""
    layout = {"f1": node({"column": "v_region", "label": "Region"})}
    assert wv.validate_module(module({}, layout)) == {}


# ---- v1 documents ------------------------------------------------------------
def test_a_v1_definition_is_left_alone() -> None:
    """A bare Craft.js map has no variables to validate, and refusing to save
    one would break every app not yet converted."""
    v1 = {"ROOT": {"type": {"resolvedName": "CanvasContainer"}, "nodes": ["f1"]},
          "f1": node({"filterParameter": "region"})}
    assert wv.validate_module(v1) == {}


def test_a_v2_document_with_no_variables_is_fine() -> None:
    assert wv.validate_module(module({})) == {}


# ---- the one thing mirrored between two runtimes ------------------------------
def test_the_reference_prop_list_agrees_with_the_browser_s_copy() -> None:
    """`REFERENCE_PROPS` exists twice: here, where it decides what the API
    refuses, and in `lib/workshop-module.ts`, where it decides what the builder
    *shows* as a usage.

    Drift makes the builder wrong rather than the document wrong - it would
    offer to delete a variable a widget binds to, and the save would then be
    refused by the server with a message the panel had just implied was
    impossible. Asserted mechanically, the same way `test_property_types.py`
    asserts its mirrored file, because this list is short and will grow widget
    by widget through item 1.5 - which is exactly when one copy gets updated
    and the other does not.
    """
    import re

    web = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "web", "src", "lib", "workshop-module.ts",
    )
    source = open(web).read()
    block = re.search(r"export const REFERENCE_PROPS = \[(.*?)\]", source, re.S)
    assert block, "REFERENCE_PROPS not found in workshop-module.ts - has it been renamed?"
    in_browser = tuple(re.findall(r'"([^"]+)"', block.group(1)))
    assert in_browser == wv.REFERENCE_PROPS, (
        f"browser has {in_browser}, API has {wv.REFERENCE_PROPS}"
    )


def test_the_nested_reference_catalogue_agrees_with_the_browser_s_copy() -> None:
    """The same mirror, for the same reason, one level deeper.

    `NESTED_REFERENCE_PROPS` decides what the API refuses; the browser's copy
    decides what the builder counts as a usage, what the lineage graph draws an
    arrow for, and what a paste into another module rewrites. Four browser-side
    readers of one list, which is precisely the count that makes drift here
    cost more than drift in the flat one.
    """
    import re

    web = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "web", "src", "lib", "workshop-module.ts",
    )
    source = open(web).read()
    block = re.search(
        r"export const NESTED_REFERENCE_PROPS: Record<string, readonly string\[\]> = \{(.*?)\n\};",
        source,
        re.S,
    )
    assert block, "NESTED_REFERENCE_PROPS not found in workshop-module.ts - renamed?"
    in_browser = {
        outer: tuple(re.findall(r'"([^"]+)"', inner))
        for outer, inner in re.findall(r"\n  (\w+): \[([^\]]*)\]", block.group(1))
    }
    assert in_browser == {k: tuple(v) for k, v in wv.NESTED_REFERENCE_PROPS.items()}, (
        f"browser has {in_browser}, API has {wv.NESTED_REFERENCE_PROPS}"
    )


#: Props whose name follows the convention below but which do **not** hold a
#: variable id of *this* module. One entry, and it earns its exemption: a Loop
#: layout's `itemVariable` is the **child module's** external ID for the
#: interface variable that receives each object (p.135), so it names something
#: in a different document entirely. Listed rather than pattern-matched away,
#: because an exemption nobody can see is how the next one gets added quietly.
NOT_A_LOCAL_VARIABLE = ("itemVariable",)


def test_every_variable_prop_is_a_known_reference() -> None:
    """**The guard the drift check above could not be.**

    That one asserts the two copies of `REFERENCE_PROPS` agree. It cannot
    notice a prop missing from *both*, and twice that is exactly what happened:
    `collapsedWhen` (§185) and `tabVariable` (§190) each shipped holding a
    variable id that nothing counted as a usage. The failure is silent in both
    directions - a module can bind to a variable it never declared and save
    happily, and the Variables panel reports the backing variable as used by
    nothing and offers to delete it.

    So this checks the list against the *builder* instead of against its own
    mirror. Every prop a settings panel reads whose name ends in `Variable`,
    `Parameter` or `When` must be a known reference or a named exception.

    **It is a naming convention, and asserting it is what makes it one.** A
    prop holding a variable id and called `foo` still slips through; the answer
    to that is to call it `fooVariable`, and this test is the reason to. The
    three suffixes are the ones already in use, and the failure says so.
    """
    import re

    widgets = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "web", "src", "components", "canvas", "widgets.tsx",
    )
    source = open(widgets).read()
    # Every prop a settings panel *reads*. Not every identifier in the file: a
    # local called `setVariable` is not a prop, and matching bare names would
    # make this fail on a rename that changed nothing.
    read_by_panels = set(re.findall(r"node\.data\.props\.([A-Za-z_]+)", source))
    assert read_by_panels, "no settings-panel props found - has widgets.tsx moved?"
    looks_like_a_variable = {
        prop for prop in read_by_panels
        if prop.endswith(("Variable", "Parameter", "When"))
    }
    # **The vacuity guard.** A completeness check that finds nothing passes,
    # and this repo has now met that failure three times in one session.
    assert len(looks_like_a_variable) >= 8, (
        f"only {sorted(looks_like_a_variable)} match the convention - either the "
        "scan broke or the convention did"
    )
    unknown = sorted(
        looks_like_a_variable - set(wv.REFERENCE_PROPS) - set(NOT_A_LOCAL_VARIABLE)
    )
    assert not unknown, (
        f"{', '.join(unknown)} look like variable references and are in neither "
        "REFERENCE_PROPS nor NOT_A_LOCAL_VARIABLE. A prop holding a variable id "
        "that is not a known reference cannot be counted as a usage, so the "
        "variable it names can be deleted out from under it"
    )


def test_every_nested_field_that_names_a_variable_is_a_known_reference() -> None:
    """**The guard the one above cannot be**, and §219 is why it exists.

    That one scans `node.data.props.X` - what a settings panel reads - so it
    only ever sees *top-level* props. A Stepper step's `completedVariable`
    holds a variable id and follows the convention exactly, and that scan
    cannot see it: the name never appears as a prop, because it is a key inside
    an element of one. The failure it lets through is §185's and §190's, by a
    route neither of their guards reaches.

    So this scans the **model modules** instead - `components/canvas/*.ts`,
    where the pure-module pattern puts every widget's shapes. A field typed
    `string` whose name ends in `Variable`, `Parameter` or `When` must be a
    catalogued nested reference or a named exception.

    Typed `string` on purpose: `mintVariable: () => string` is a factory and
    `filterParameter: "write"` is a classification, and neither holds an id.
    """
    import glob
    import re

    canvas = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "web", "src", "components", "canvas",
    )
    files = [f for f in glob.glob(os.path.join(canvas, "*.ts")) if not f.endswith(".test.ts")]
    assert len(files) >= 20, f"only {len(files)} model modules - has the directory moved?"
    fields: set[str] = set()
    for path in files:
        fields |= set(
            re.findall(
                r"^\s+([A-Za-z_]*(?:Variable|Parameter|When))\??:\s*string\b",
                open(path).read(),
                re.M,
            )
        )
    # The vacuity guard, and the number is honestly one: `completedVariable` is
    # the first nested reference this platform has. What the assertion is for
    # is the day the scan stops matching - a rename of the directory, a change
    # of file extension, a shape declared inline instead of as an interface -
    # because a completeness check over an empty set passes forever.
    assert len(fields) >= 1, (
        "no variable-shaped model fields found - the scan broke, not the convention"
    )
    catalogued = {inner for inners in wv.NESTED_REFERENCE_PROPS.values() for inner in inners}
    unknown = sorted(fields - catalogued - set(wv.REFERENCE_PROPS) - set(NOT_A_LOCAL_VARIABLE))
    assert not unknown, (
        f"{', '.join(unknown)} name variables from inside a widget's own shape and are "
        "in no reference catalogue. Nothing counts them as a usage, so the variable "
        "each names can be deleted out from under the widget that reads it - add the "
        "holding prop to NESTED_REFERENCE_PROPS in both runtimes"
    )


def _bound_section(props: dict) -> dict:
    return {
        "ROOT": {"type": {"resolvedName": "CanvasContainer"}, "nodes": ["sec"]},
        "sec": {"type": {"resolvedName": "CanvasSection"}, "props": props, "nodes": []},
    }


def test_a_section_collapse_binding_counts_as_a_usage() -> None:
    """p.82's "Boolean variable backing the collapse state" is a binding like
    any other, and counted as none until §191."""
    layout = _bound_section({"direction": "columns", "collapsible": True,
                             "collapsedWhen": "v_b"})
    variables = wv.parse({"v_b": var("v_b", kind="boolean")})
    assert wv.usages(layout, variables)["v_b"] == [{"node": "sec", "prop": "collapsedWhen"}]


def test_a_tab_selection_binding_counts_as_a_usage() -> None:
    """p.84's tab variable, same argument. §190 checked that it *resolved* at
    save time and not that it was *used* - so the panel would offer to delete
    it, and the next save would be refused for an edit made earlier."""
    layout = _bound_section({"direction": "tabs", "tabVariable": "v_s"})
    variables = wv.parse({"v_s": var("v_s")})
    assert wv.usages(layout, variables)["v_s"] == [{"node": "sec", "prop": "tabVariable"}]


def test_binding_a_collapse_to_a_variable_that_is_not_declared_is_refused() -> None:
    """The other direction, and the one that used to save happily."""
    layout = _bound_section({"direction": "columns", "collapsible": True,
                             "collapsedWhen": "v_gone"})
    with pytest.raises(wv.VariableError, match="does not declare|binds to"):
        wv.validate_module({"format": 2, "layout": layout, "variables": {}, "events": {}})


# ---- object sets: the variable kind Workshop is actually built on -------------
# The roadmap calls this "the item that decides whether Workshop parity is
# real". The shape being tested is the one a person builds: a dataset becomes
# an object type, an object-set variable draws from that type, a filter
# variable narrows it, and a table reads the narrowed set.

TYPE_ID = "11111111-1111-1111-1111-111111111111"


def object_set_var(vid: str, **extra) -> dict:
    return var(vid, kind="object_set", **extra)


def test_an_object_set_variable_resolves_to_a_definition_not_to_rows() -> None:
    """Rows in a variable would make a saved app a saved session. The variable
    describes the set; `/object-sets/evaluate` turns it into instances."""
    variables = wv.parse(
        {
            "v_sites": object_set_var(
                "v_sites", label="All sites",
                object_set={"object_type_id": TYPE_ID, "filters": []},
            )
        }
    )
    resolved = wv.evaluate(variables, {})
    assert resolved["v_sites"] == {"object_type_id": TYPE_ID, "filters": []}


def test_a_filter_variable_narrows_the_set_a_table_reads() -> None:
    """The canonical Workshop interaction: a Filter List and an Object Table
    reading *the same* set, rather than each filtering its own copy."""
    variables = wv.parse(
        {
            "v_sites": object_set_var(
                "v_sites", label="All sites",
                object_set={"object_type_id": TYPE_ID, "filters": []},
            ),
            "v_region": var("v_region", label="Region"),
            "v_visible": object_set_var(
                "v_visible", label="Sites in region",
                derivation={
                    "transform": "filter_set",
                    "inputs": ["v_sites", "v_region"],
                    "config": {"property": "region", "op": "eq"},
                },
            ),
        }
    )
    resolved = wv.evaluate(variables, {"v_region": "north"})
    assert resolved["v_visible"] == {
        "object_type_id": TYPE_ID,
        "filters": [{"property": "region", "op": "eq", "value": "north"}],
    }
    # And the base set is untouched - one variable narrowing another must not
    # mutate the thing it read, or a second consumer of the base would silently
    # get the narrowed one.
    assert resolved["v_sites"]["filters"] == []


def test_an_unset_filter_shows_everything_rather_than_nothing() -> None:
    """A viewer who has not touched the filter yet should see the whole set.
    Filtering for `region = null` would make every app open empty and look
    broken.

    This is *not* the failure decision 0002 removed - that was a binding to a
    variable nothing declared, which the save path refuses outright. This is a
    declared variable with no value yet, which is an ordinary state.
    """
    variables = wv.parse(
        {
            "v_sites": object_set_var(
                "v_sites", label="All sites",
                object_set={"object_type_id": TYPE_ID, "filters": []},
            ),
            "v_region": var("v_region", label="Region"),
            "v_visible": object_set_var(
                "v_visible", label="Visible",
                derivation={"transform": "filter_set", "inputs": ["v_sites", "v_region"],
                            "config": {"property": "region"}},
            ),
        }
    )
    for empty in ({}, {"v_region": None}, {"v_region": ""}, {"v_region": []}):
        assert wv.evaluate(variables, empty)["v_visible"]["filters"] == [], empty


def test_filters_chain_so_two_controls_narrow_one_set() -> None:
    variables = wv.parse(
        {
            "v_sites": object_set_var(
                "v_sites", label="All sites",
                object_set={"object_type_id": TYPE_ID, "filters": []},
            ),
            "v_region": var("v_region", label="Region"),
            "v_status": var("v_status", label="Status"),
            "v_by_region": object_set_var(
                "v_by_region", label="By region",
                derivation={"transform": "filter_set", "inputs": ["v_sites", "v_region"],
                            "config": {"property": "region"}},
            ),
            "v_visible": object_set_var(
                "v_visible", label="Visible",
                derivation={"transform": "filter_set", "inputs": ["v_by_region", "v_status"],
                            "config": {"property": "status"}},
            ),
        }
    )
    resolved = wv.evaluate(variables, {"v_region": "north", "v_status": "open"})
    assert [f["property"] for f in resolved["v_visible"]["filters"]] == ["region", "status"]


def test_an_object_set_variable_with_no_type_is_refused() -> None:
    with pytest.raises(wv.VariableError, match="names no object type"):
        wv.parse({"v_sites": object_set_var("v_sites", label="All sites")})


def test_an_object_set_that_is_both_derived_and_given_a_type_is_refused() -> None:
    """Two answers to "where do these rows come from" and no rule for which
    wins."""
    with pytest.raises(wv.VariableError, match="not both"):
        wv.parse(
            {
                "v_a": object_set_var("v_a", label="A",
                                      object_set={"object_type_id": TYPE_ID, "filters": []}),
                "v_b": object_set_var(
                    "v_b", label="B",
                    object_set={"object_type_id": TYPE_ID, "filters": []},
                    derivation={"transform": "filter_set", "inputs": ["v_a", "v_a"],
                                "config": {"property": "x"}},
                ),
            }
        )


def test_a_string_variable_carrying_an_object_set_is_refused() -> None:
    with pytest.raises(wv.VariableError, match="only object_set variables"):
        wv.parse({"v_a": var("v_a", object_set={"object_type_id": TYPE_ID})})


def test_an_invalid_set_definition_is_refused_at_save_not_at_read() -> None:
    """The same validation `/object-sets/evaluate` applies, moved to the moment
    somebody can still fix it."""
    with pytest.raises(wv.VariableError):
        wv.parse(
            {
                "v_sites": object_set_var(
                    "v_sites", label="All sites",
                    object_set={"object_type_id": "not-a-uuid", "filters": []},
                )
            }
        )


def test_filter_set_refuses_an_operator_the_two_stores_disagree_about() -> None:
    """`gt` is refused by `object_sets` because Postgres casts and OpenSearch
    compares text. A derivation must not be a way around that."""
    with pytest.raises(wv.VariableError, match="operator"):
        wv.parse(
            {
                "v_sites": object_set_var("v_sites", label="Sites",
                                          object_set={"object_type_id": TYPE_ID}),
                "v_n": var("v_n", label="N"),
                "v_big": object_set_var(
                    "v_big", label="Big",
                    derivation={"transform": "filter_set", "inputs": ["v_sites", "v_n"],
                                "config": {"property": "capacity", "op": "gt"}},
                ),
            }
        )


def test_filtering_something_that_is_not_a_set_says_so() -> None:
    variables = wv.parse(
        {
            "v_text": var("v_text", label="Some text"),
            "v_region": var("v_region", label="Region"),
            "v_bad": object_set_var(
                "v_bad", label="Bad",
                derivation={"transform": "filter_set", "inputs": ["v_text", "v_region"],
                            "config": {"property": "region"}},
            ),
        }
    )
    with pytest.raises(wv.VariableError, match="not an object set"):
        wv.evaluate(variables, {"v_text": "hello", "v_region": "north"})


# ---- events (roadmap phase 2, item 1.3) --------------------------------------
from src.services import workshop_events as we  # noqa: E402


def event(eid: str, node: str = "btn", on: str = "click", effects=None) -> dict:
    return {"id": eid, "trigger": {"node": node, "on": on}, "effects": effects or []}


def set_var(target: str, value=None) -> dict:
    return {"type": "set_variable", "config": {"variable": target, "value": value}}


def test_an_event_declares_a_trigger_and_ordered_effects() -> None:
    variables = wv.parse({"v_a": var("v_a", label="A")})
    events = we.parse(
        {"e_1": event("e_1", effects=[set_var("v_a", "x"),
                                      {"type": "open_url", "config": {"url": "https://x.test"}}])},
        layout={"btn": node({})},
        variables=variables,
    )
    assert [e.type for e in events["e_1"].effects] == ["set_variable", "open_url"]


def test_an_event_on_a_widget_that_is_not_there_is_refused() -> None:
    """It can never fire, so it is not an event - it is a fragment of a
    previous design that will confuse whoever reads the document next."""
    with pytest.raises(we.EventError, match="does not contain"):
        we.parse({"e_1": event("e_1", node="gone")}, layout={"btn": node({})})


def test_setting_a_variable_the_module_does_not_declare_is_refused() -> None:
    variables = wv.parse({"v_a": var("v_a", label="A")})
    with pytest.raises(we.EventError, match="does not declare"):
        we.parse({"e_1": event("e_1", effects=[set_var("v_gone")])},
                 layout={"btn": node({})}, variables=variables)


def test_setting_a_derived_variable_is_refused_and_says_what_to_set_instead() -> None:
    """A derived variable is a function of its inputs. Honouring the write
    would let one document show two different things depending on which the
    reader believed - the same rule `evaluate` enforces for viewer values."""
    variables = wv.parse(
        {
            "v_a": var("v_a", label="Source"),
            "v_b": var("v_b", label="Computed",
                       derivation={"transform": "concat", "inputs": ["v_a"]}),
        }
    )
    with pytest.raises(we.EventError) as raised:
        we.parse({"e_1": event("e_1", effects=[set_var("v_b")])},
                 layout={"btn": node({})}, variables=variables)
    assert "computed from other variables" in str(raised.value)
    assert "Computed" in str(raised.value), "named by label, not by id"


def test_an_unbuilt_effect_says_so_rather_than_saving_a_dead_click() -> None:
    # `navigate` was the example here until item 1.4 built it, and `run_action`
    # until the second half of 1.3. `export` is the one still waiting, on a
    # download surface the viewer route does not have.
    with pytest.raises(we.EventError, match="not built yet"):
        we.parse({"e_1": event("e_1", effects=[{"type": "export", "config": {}}])},
                 layout={"btn": node({})})


def test_a_url_a_browser_should_not_follow_is_refused() -> None:
    """An app author is not necessarily trusted by everyone who opens the app,
    and a published app is opened by the whole workspace."""
    with pytest.raises(we.EventError, match="not a link a browser will open"):
        we.parse(
            {"e_1": event("e_1", effects=[
                {"type": "open_url", "config": {"url": "javascript:alert(1)"}}])},
            layout={"btn": node({})},
        )


def test_events_for_one_trigger_come_back_in_a_stated_order() -> None:
    """Two events on one trigger both writing variables have to run in a
    stated order, or the app behaves differently between reloads."""
    events = we.parse(
        {
            "e_2": event("e_2", node="btn"),
            "e_1": event("e_1", node="btn"),
            "e_3": event("e_3", node="other"),
        },
        layout={"btn": node({}), "other": node({})},
    )
    assert [e.id for e in we.for_node(events, "btn", "click")] == ["e_1", "e_2"]


def test_the_save_path_refuses_a_bad_event_too() -> None:
    """Events are validated through `validate_module`, so a document with a
    dead trigger cannot be saved at all."""
    with pytest.raises(wv.VariableError, match="does not contain"):
        wv.validate_module(
            {"format": 2, "layout": {}, "variables": {},
             "events": {"e_1": event("e_1", node="gone")}}
        )


# ---- pages and navigate (roadmap phase 2, item 1.4) --------------------------
def page_node(title: str = "Page") -> dict:
    return {"type": {"resolvedName": "CanvasPage"}, "props": {"title": title}, "nodes": []}


def layout_with_pages(*page_ids: str, extra: dict | None = None) -> dict:
    layout = {"ROOT": {"type": {"resolvedName": "CanvasContainer"},
                       "nodes": [*page_ids, *(extra or {})]}}
    for pid in page_ids:
        layout[pid] = page_node(pid)
    layout.update(extra or {})
    return layout


def test_pages_are_read_from_the_layout_in_the_order_it_lists_them() -> None:
    """Read rather than stored beside it, the same way usages are: a second
    copy of the fact disagrees the moment something deletes a node without
    knowing to update it. The order is ROOT's child order, which is what
    somebody arranged in the builder."""
    layout = layout_with_pages("p_two", "p_one", extra={"tabs": node({})})
    assert we.pages(layout) == ["p_two", "p_one"]


def test_a_layout_with_no_pages_has_none() -> None:
    assert we.pages({"ROOT": {"type": {"resolvedName": "CanvasContainer"}, "nodes": ["t"]},
                     "t": node({})}) == []


def test_navigate_is_built_now_and_accepted() -> None:
    events = we.parse(
        {"e_1": event("e_1", node="tabs", effects=[
            {"type": "navigate", "config": {"page": "p_one"}}])},
        layout=layout_with_pages("p_one", extra={"tabs": node({})}),
    )
    assert events["e_1"].effects[0].type == "navigate"


def test_navigating_to_a_widget_that_is_not_a_page_is_refused() -> None:
    """Not a smaller version of navigating to a page - it is a click that would
    do nothing, and saying so at save is the only moment anybody can fix it."""
    with pytest.raises(we.EventError, match="a widget rather than a page"):
        we.parse(
            {"e_1": event("e_1", node="tabs", effects=[
                {"type": "navigate", "config": {"page": "tbl"}}])},
            layout=layout_with_pages("p_one", extra={"tabs": node({}), "tbl": node({})}),
        )


def test_navigating_to_a_page_that_is_not_there_is_refused() -> None:
    with pytest.raises(we.EventError, match="does not contain"):
        we.parse(
            {"e_1": event("e_1", node="tabs", effects=[
                {"type": "navigate", "config": {"page": "p_gone"}}])},
            layout=layout_with_pages("p_one", extra={"tabs": node({})}),
        )


# ---- run_action (roadmap 1.3, second half) -----------------------------------
def run_action(subject: str = "v_obj", action: str = "a_1", values=None) -> dict:
    return {"type": "run_action",
            "config": {"action": action, "subject": subject,
                       "values": {"status": "done"} if values is None else values}}


def subject_vars(kind: str = "single_object") -> dict:
    return wv.parse({"v_obj": var("v_obj", kind=kind, label="Picked")})


def test_run_action_is_built_now_and_accepted() -> None:
    events = we.parse(
        {"e_1": event("e_1", effects=[run_action()])},
        layout={"btn": node({})}, variables=subject_vars(),
    )
    assert [e.type for e in events["e_1"].effects] == ["run_action"]


def test_the_one_effect_still_waiting_on_something_says_so() -> None:
    """`export` remains refused, blocked on something real rather than on
    effort: the viewer route has no download surface."""
    with pytest.raises(we.EventError, match="not built yet"):
        we.parse({"e_1": event("e_1", effects=[{"type": "export", "config": {}}])},
                 layout={"btn": node({})})


def test_an_action_needs_an_object_to_act_on() -> None:
    with pytest.raises(we.EventError, match="variable holding the object"):
        we.parse({"e_1": event("e_1", effects=[
            {"type": "run_action", "config": {"action": "a_1", "values": {"s": "x"}}}])},
            layout={"btn": node({})}, variables=subject_vars())


def test_a_subject_that_does_not_hold_an_object_is_refused() -> None:
    """A text variable holding a primary key looks equivalent and is not: the
    action executes against an instance id, so the two disagree the first time
    somebody types a key into the box."""
    with pytest.raises(we.EventError, match="rather than an object") as raised:
        we.parse({"e_1": event("e_1", effects=[run_action()])},
                 layout={"btn": node({})}, variables=subject_vars(kind="string"))
    assert "Picked" in str(raised.value), "named by label, not by id"


def test_a_subject_the_module_does_not_declare_is_refused() -> None:
    with pytest.raises(we.EventError, match="does not declare"):
        we.parse({"e_1": event("e_1", effects=[run_action(subject="v_missing")])},
                 layout={"btn": node({})}, variables=subject_vars())


def test_an_action_with_nothing_to_write_is_refused() -> None:
    """`validate_submitted_values` refuses an empty write, so saving this
    would save an event that fails every single time it is clicked."""
    with pytest.raises(we.EventError, match="nothing to do"):
        we.parse({"e_1": event("e_1", effects=[run_action(values={})])},
                 layout={"btn": node({})}, variables=subject_vars())


def test_a_value_that_is_not_text_is_refused() -> None:
    """Values are templates - `{{value}}` reads from the trigger. A number
    would work by accident and stop working the moment somebody added a token
    to it."""
    with pytest.raises(we.EventError, match="values are text"):
        we.parse({"e_1": event("e_1", effects=[run_action(values={"count": 3})])},
                 layout={"btn": node({})}, variables=subject_vars())


def test_an_action_the_workspace_does_not_have_is_refused_when_saving() -> None:
    with pytest.raises(we.EventError, match="does not have"):
        we.parse({"e_1": event("e_1", effects=[run_action(action="a_gone")])},
                 layout={"btn": node({})}, variables=subject_vars(),
                 actions={"a_1": ["status"]})


def test_writing_a_property_the_action_does_not_make_editable_is_refused() -> None:
    """The write would be refused at click time with the same sentence. Saying
    it now is the difference between the person who made the mistake finding
    out and somebody else."""
    with pytest.raises(we.EventError, match="does not make editable"):
        we.parse({"e_1": event("e_1", effects=[run_action(values={"owner": "me"})])},
                 layout={"btn": node({})}, variables=subject_vars(),
                 actions={"a_1": ["status"]})


def test_without_the_workspace_the_document_is_still_checked_against_itself() -> None:
    """Reading a saved module does not pass `actions`, so an action deleted
    since it was saved must not stop the module opening - while the refusals
    that depend only on the document still hold. A record of what somebody
    built does not become invalid because live state moved."""
    we.parse({"e_1": event("e_1", effects=[run_action(action="a_long_gone")])},
             layout={"btn": node({})}, variables=subject_vars())
    with pytest.raises(we.EventError, match="rather than an object"):
        we.parse({"e_1": event("e_1", effects=[run_action(action="a_long_gone")])},
                 layout={"btn": node({})}, variables=subject_vars(kind="string"))


# ---- overlays (roadmap phase 2, item 1.4) ------------------------------------
def overlay_node(title: str = "Overlay") -> dict:
    return {"type": {"resolvedName": "CanvasOverlay"}, "props": {"title": title}, "nodes": []}


def test_overlays_are_read_from_the_layout_like_pages() -> None:
    layout = {
        "ROOT": {"type": {"resolvedName": "CanvasContainer"}, "nodes": ["p_a", "o_a", "tbl"]},
        "p_a": page_node("A"), "o_a": overlay_node("Detail"), "tbl": node({}),
    }
    assert we.pages(layout) == ["p_a"]
    assert we.overlays(layout) == ["o_a"]


def test_navigate_accepts_an_overlay_as_well_as_a_page() -> None:
    """One effect, two destinations. What differs is what the browser does:
    a page replaces, an overlay covers and can be closed back."""
    layout = {
        "ROOT": {"type": {"resolvedName": "CanvasContainer"}, "nodes": ["p_a", "o_a", "btn"]},
        "p_a": page_node("A"), "o_a": overlay_node("Detail"), "btn": node({}),
    }
    events = we.parse(
        {"e_1": event("e_1", effects=[{"type": "navigate", "config": {"page": "o_a"}}])},
        layout=layout,
    )
    assert events["e_1"].effects[0].config["page"] == "o_a"


def test_closing_an_overlay_is_its_own_effect() -> None:
    """Not "navigate to nothing": closing returns you to the page underneath,
    which navigate has no way to name."""
    events = we.parse(
        {"e_1": event("e_1", effects=[{"type": "close_overlay", "config": {}}])},
        layout={"btn": node({})},
    )
    assert events["e_1"].effects[0].type == "close_overlay"


def test_navigating_to_a_plain_widget_still_names_both_kinds() -> None:
    layout = {
        "ROOT": {"type": {"resolvedName": "CanvasContainer"}, "nodes": ["p_a", "tbl"]},
        "p_a": page_node("A"), "tbl": node({}),
    }
    with pytest.raises(we.EventError, match="page or an overlay"):
        we.parse(
            {"e_1": event("e_1", node="tbl", effects=[
                {"type": "navigate", "config": {"page": "tbl"}}])},
            layout=layout,
        )


# ---- the module header (roadmap phase 2, item 1.4) ---------------------------
def header_node(title: str = "") -> dict:
    return {"type": {"resolvedName": "CanvasHeader"}, "props": {"title": title}, "nodes": []}


def test_a_header_is_read_from_the_layout_like_a_page() -> None:
    layout = {
        "ROOT": {"type": {"resolvedName": "CanvasContainer"}, "nodes": ["h", "p_a"]},
        "h": header_node("Sites"), "p_a": page_node("A"),
    }
    assert we.headers(layout) == ["h"]
    # And it is not a page: a header is always showing, so navigating to it
    # would mean nothing.
    assert we.pages(layout) == ["p_a"]


def test_one_header_is_fine() -> None:
    layout = {
        "ROOT": {"type": {"resolvedName": "CanvasContainer"}, "nodes": ["h", "p_a"]},
        "h": header_node("Sites"), "p_a": page_node("A"),
    }
    assert wv.validate_module(module({}, layout)) == {}


def test_a_second_header_is_refused_and_the_message_counts_them() -> None:
    """Two nodes both claiming to be *the* module-wide toolbar is a document
    no renderer can settle, so the refusal happens where every route passes."""
    layout = {
        "ROOT": {"type": {"resolvedName": "CanvasContainer"}, "nodes": ["h1", "h2", "p_a"]},
        "h1": header_node("Sites"), "h2": header_node("Also sites"), "p_a": page_node("A"),
    }
    with pytest.raises(wv.VariableError) as raised:
        wv.validate_module(module({}, layout))
    assert "one header" in str(raised.value)
    assert "has 2" in str(raised.value)


def test_navigating_to_a_header_is_refused() -> None:
    """It is always showing. A click that "goes to" it would do nothing."""
    layout = {
        "ROOT": {"type": {"resolvedName": "CanvasContainer"}, "nodes": ["h", "btn"]},
        "h": header_node("Sites"), "btn": node({}),
    }
    with pytest.raises(we.EventError, match="page or an overlay"):
        we.parse(
            {"e_1": event("e_1", effects=[{"type": "navigate", "config": {"page": "h"}}])},
            layout=layout,
        )


# ---- the Button widget (roadmap 1.5, and 1.3's missing trigger source) --------
def test_a_button_gated_on_a_variable_counts_as_a_usage() -> None:
    """`enabledVariable` is a reference like any other, so deleting the
    variable a button is gated on is refused rather than quietly making the
    button permanently pressable."""
    layout = {"btn": {"type": {"resolvedName": "CanvasButton"},
                      "props": {"label": "Clear", "enabledVariable": "v_selected"},
                      "nodes": []}}
    declared = wv.parse({"v_selected": var("v_selected", label="Selected")})
    found = wv.usages(layout, declared)
    assert found["v_selected"] == [{"node": "btn", "prop": "enabledVariable"}]
    assert wv.validate_module(
        module({"v_selected": var("v_selected", label="Selected")}, layout)
    ) != {}


def test_a_button_gated_on_a_variable_nothing_declares_is_refused() -> None:
    layout = {"btn": {"type": {"resolvedName": "CanvasButton"},
                      "props": {"label": "Clear", "enabledVariable": "v_gone"},
                      "nodes": []}}
    with pytest.raises(wv.VariableError, match="does not declare"):
        wv.validate_module(module({}, layout))


# ---- narrow_set: the Filter List's derivation (roadmap 1.5) ------------------
def narrowing_module() -> dict[str, wv.Variable]:
    return wv.parse(
        {
            "v_sites": object_set_var(
                "v_sites", label="All sites",
                object_set={"object_type_id": TYPE_ID, "filters": []},
            ),
            "v_clauses": var("v_clauses", kind="array", label="Chosen filters"),
            "v_visible": object_set_var(
                "v_visible", label="Visible",
                derivation={"transform": "narrow_set", "inputs": ["v_sites", "v_clauses"]},
            ),
        }
    )


def test_narrow_set_applies_the_clauses_a_widget_wrote() -> None:
    """A Filter List narrows on properties the *viewer* picks, so what varies
    is the list of clauses rather than one configured property."""
    variables = narrowing_module()
    resolved = wv.evaluate(variables, {"v_clauses": [
        {"property": "region", "op": "eq", "value": "north"},
        {"property": "status", "op": "in", "value": ["open", "closed"]},
    ]})
    assert resolved["v_visible"]["filters"] == [
        {"property": "region", "op": "eq", "value": "north"},
        {"property": "status", "op": "in", "value": ["open", "closed"]},
    ]


def test_narrow_set_with_nothing_chosen_is_the_whole_set() -> None:
    """Not an empty one: a viewer who has touched nothing should see
    everything, the rule `filter_set` already follows."""
    variables = narrowing_module()
    for empty in ({}, {"v_clauses": None}, {"v_clauses": []}):
        assert wv.evaluate(variables, empty)["v_visible"]["filters"] == [], empty


def test_narrow_set_keeps_the_filters_the_base_set_already_had() -> None:
    variables = wv.parse(
        {
            "v_sites": object_set_var(
                "v_sites", label="Open sites",
                object_set={"object_type_id": TYPE_ID,
                            "filters": [{"property": "status", "op": "eq", "value": "open"}]},
            ),
            "v_clauses": var("v_clauses", kind="array", label="Chosen filters"),
            "v_visible": object_set_var(
                "v_visible", label="Visible",
                derivation={"transform": "narrow_set", "inputs": ["v_sites", "v_clauses"]},
            ),
        }
    )
    resolved = wv.evaluate(
        variables, {"v_clauses": [{"property": "region", "op": "eq", "value": "north"}]}
    )
    assert [f["property"] for f in resolved["v_visible"]["filters"]] == ["status", "region"]


def test_narrow_set_refuses_clauses_it_cannot_mean_rather_than_dropping_them() -> None:
    """The clauses come from a browser, so they get the same parse every set
    gets. A dropped clause is a set wider than the viewer asked for."""
    variables = narrowing_module()
    with pytest.raises(wv.VariableError, match="not supported yet"):
        wv.evaluate(variables, {"v_clauses": [
            {"property": "capacity", "op": "gt", "value": 40}]})
    with pytest.raises(wv.VariableError, match="unknown filter operator"):
        wv.evaluate(variables, {"v_clauses": [
            {"property": "region", "op": "regex", "value": "^n"}]})
    with pytest.raises(wv.VariableError, match="no value"):
        wv.evaluate(variables, {"v_clauses": [{"property": "region", "op": "eq"}]})


def test_narrow_set_refuses_something_that_is_not_a_list() -> None:
    variables = narrowing_module()
    with pytest.raises(wv.VariableError, match="list of filter clauses"):
        wv.evaluate(variables, {"v_clauses": {"property": "region"}})


def test_narrow_set_needs_two_inputs() -> None:
    with pytest.raises(wv.VariableError, match="narrow_set needs exactly two inputs"):
        wv.parse({
            "v_sites": object_set_var(
                "v_sites", label="All sites",
                object_set={"object_type_id": TYPE_ID, "filters": []},
            ),
            "v_visible": object_set_var(
                "v_visible", label="Visible",
                derivation={"transform": "narrow_set", "inputs": ["v_sites"]},
            ),
        })


# ---- object_property, and what a single_object variable holds (§84) ----------
CLICKED = {
    "object_type_id": TYPE_ID,
    "primary_key": "S1",
    "properties": {"name": "Aberdeen Yard", "status": "open"},
}


def picking_module() -> dict[str, wv.Variable]:
    return wv.parse(
        {
            "v_site": var("v_site", kind="single_object", label="Selected site"),
            "v_name": var("v_name", label="Name",
                          derivation={"transform": "object_property", "inputs": ["v_site"],
                                      "config": {"property": "name"}}),
        }
    )


def test_a_property_of_the_object_a_viewer_picked() -> None:
    resolved = wv.evaluate(picking_module(), {"v_site": CLICKED})
    assert resolved["v_name"] == "Aberdeen Yard"


def test_the_primary_key_is_readable_by_name() -> None:
    """It is not in `properties` - a row's key is its own field - so without
    this it would be the one thing about an object an app could not show."""
    variables = wv.parse({
        "v_site": var("v_site", kind="single_object", label="Selected site"),
        "v_key": var("v_key", label="Key",
                     derivation={"transform": "object_property", "inputs": ["v_site"],
                                 "config": {"property": "primary_key"}}),
    })
    assert wv.evaluate(variables, {"v_site": CLICKED})["v_key"] == "S1"


def test_nothing_picked_reads_as_empty_rather_than_failing() -> None:
    """A detail panel before the first click is an ordinary state."""
    for empty in ({}, {"v_site": None}, {"v_site": ""}):
        assert wv.evaluate(picking_module(), empty)["v_name"] is None, empty


def test_a_property_that_the_object_does_not_have_is_empty() -> None:
    assert wv.evaluate(
        wv.parse({
            "v_site": var("v_site", kind="single_object", label="Selected site"),
            "v_x": var("v_x", label="Capacity",
                       derivation={"transform": "object_property", "inputs": ["v_site"],
                                   "config": {"property": "capacity"}}),
        }),
        {"v_site": CLICKED},
    )["v_x"] is None


def test_reading_a_property_of_something_that_is_not_an_object_is_refused() -> None:
    """A wired-wrongly document, not an ordinary state - a variable holding a
    string cannot have properties, and rendering blank would hide it."""
    with pytest.raises(wv.VariableError, match="not an object"):
        wv.evaluate(picking_module(), {"v_site": "S1"})


def test_object_property_chains_into_another_transform() -> None:
    """The point of it being a transform rather than a widget feature: the
    property feeds the same graph everything else does."""
    variables = wv.parse({
        "v_site": var("v_site", kind="single_object", label="Selected"),
        "v_name": var("v_name", label="Name",
                      derivation={"transform": "object_property", "inputs": ["v_site"],
                                  "config": {"property": "name"}}),
        "v_status": var("v_status", label="Status",
                        derivation={"transform": "object_property", "inputs": ["v_site"],
                                    "config": {"property": "status"}}),
        "v_label": var("v_label", label="Label",
                       derivation={"transform": "concat", "inputs": ["v_name", "v_status"],
                                   "config": {"separator": " - "}}),
    })
    assert wv.evaluate(variables, {"v_site": CLICKED})["v_label"] == "Aberdeen Yard - open"


def test_object_property_needs_one_input_and_a_property() -> None:
    with pytest.raises(wv.VariableError, match="exactly one input"):
        wv.parse({"v_a": var("v_a", label="A"), "v_b": var("v_b", label="B"),
                  "v_x": var("v_x", label="X",
                             derivation={"transform": "object_property",
                                         "inputs": ["v_a", "v_b"],
                                         "config": {"property": "name"}})})
    with pytest.raises(wv.VariableError, match="needs a property to read"):
        wv.parse({"v_a": var("v_a", kind="single_object", label="A"),
                  "v_x": var("v_x", label="X",
                             derivation={"transform": "object_property", "inputs": ["v_a"],
                                         "config": {}})})


def test_an_aggregation_over_a_set_is_still_refused_and_says_why() -> None:
    """The other store transform did not move: it needs the instance store,
    which `/object-sets/aggregate` is what answers."""
    with pytest.raises(wv.VariableError, match="not built yet"):
        wv.parse({"v_set": object_set_var(
                      "v_set", label="Set",
                      object_set={"object_type_id": TYPE_ID, "filters": []}),
                  "v_n": var("v_n", kind="number", label="Count",
                             derivation={"transform": "object_set_aggregation",
                                         "inputs": ["v_set"], "config": {}})})


def test_a_row_click_may_write_the_whole_object() -> None:
    events = we.parse(
        {"e_1": event("e_1", node="tbl", on="row_select", effects=[
            {"type": "set_variable", "config": {"variable": "v_site", "from": "object"}}])},
        layout={"tbl": node({})},
        variables=wv.parse({"v_site": var("v_site", kind="single_object", label="Site")}),
    )
    assert events["e_1"].effects[0].config["from"] == "object"


def test_an_entry_may_be_committed_with_the_enter_key() -> None:
    """p.465's "Event on enter: set event(s) to be triggered when the enter key
    is pressed", as a trigger of its own.

    Distinct from `change`, which fires per keystroke. The whole point of
    p.465's setting is to run something **once**, when the entry is finished,
    and a widget that could only announce `change` could not express it.
    """
    events = we.parse(
        {"e_1": event("e_1", node="txt", on="submit", effects=[set_var("v_a", "x")])},
        layout={"txt": node({})},
        variables=wv.parse({"v_a": var("v_a", label="A")}),
    )
    assert events["e_1"].on == "submit"


def test_a_trigger_this_platform_does_not_have_is_refused() -> None:
    """Including the one `submit` was nearly called. The vocabulary is closed so
    a document cannot carry a trigger nothing will ever fire — which would be a
    wiring that looks configured and never runs."""
    with pytest.raises(we.EventError, match="expected one of"):
        we.parse(
            {"e_1": event("e_1", node="txt", on="enter")},
            layout={"txt": node({})},
        )


def test_writing_from_an_unknown_source_is_refused() -> None:
    with pytest.raises(we.EventError, match="expected one of"):
        we.parse(
            {"e_1": event("e_1", effects=[
                {"type": "set_variable", "config": {"variable": "v_a", "from": "row"}}])},
            layout={"btn": node({})},
        )


def test_writing_from_a_source_and_a_value_at_once_is_refused() -> None:
    """Two ways of saying what to write, and no rule for which wins."""
    with pytest.raises(we.EventError, match="one or the other"):
        we.parse(
            {"e_1": event("e_1", effects=[
                {"type": "set_variable",
                 "config": {"variable": "v_a", "from": "object", "value": "{{name}}"}}])},
            layout={"btn": node({})},
        )


# ---- widget visibility (roadmap 1.7) -----------------------------------------
def test_a_section_shown_only_when_a_variable_is_truthy_counts_as_a_usage() -> None:
    """`visibleWhen` is a reference like any other, so deleting the variable a
    section's visibility depends on is refused rather than quietly making the
    section permanent."""
    layout = {"sec": {"type": {"resolvedName": "CanvasSection"},
                      "props": {"direction": "rows", "visibleWhen": "v_any"},
                      "nodes": []}}
    declared = wv.parse({"v_any": var("v_any", kind="boolean", label="Anything chosen")})
    assert wv.usages(layout, declared)["v_any"] == [{"node": "sec", "prop": "visibleWhen"}]


def test_a_visibility_binding_to_a_variable_nothing_declares_is_refused() -> None:
    layout = {"sec": {"type": {"resolvedName": "CanvasSection"},
                      "props": {"visibleWhen": "v_gone"}, "nodes": []}}
    with pytest.raises(wv.VariableError, match="does not declare"):
        wv.validate_module(module({}, layout))


# ---- external IDs and the module interface (parity workshop.md §3.4) ---------
# One mechanism behind three features Foundry documents separately: embedding,
# URL initialisation, and state saving (p.163, p.165, p.202). These test the
# mechanism; the three consumers are tested where they live.
def test_a_variable_can_carry_an_external_id() -> None:
    variables = wv.parse({"v_a": var("v_a", external_id="status")})
    assert variables["v_a"].external_id == "status"
    # An external ID alone does not publish it: the interface is a separate
    # toggle, so a stable name for a URL is not also an embedding contract.
    assert variables["v_a"].interface is None
    assert wv.interface_variables(variables) == {}


def test_the_interface_toggle_publishes_a_variable_under_its_external_id() -> None:
    variables = wv.parse(
        {"v_a": var("v_a", external_id="status", interface={"display_name": "Status"})}
    )
    published = wv.interface_variables(variables)
    assert list(published) == ["status"]
    assert published["status"].id == "v_a"
    assert published["status"].interface.display_name == "Status"


def test_the_toggle_is_accepted_as_a_bare_true() -> None:
    """A hand-written document is far likelier to write `true` than an object."""
    variables = wv.parse({"v_a": var("v_a", external_id="status", interface=True)})
    assert variables["v_a"].interface == wv.Interface()


def test_an_interface_variable_without_an_external_id_is_refused() -> None:
    with pytest.raises(wv.VariableError, match="no external ID"):
        wv.parse({"v_a": var("v_a", interface=True)})


def test_an_external_id_that_would_need_url_encoding_is_refused() -> None:
    # It is a query parameter name (p.165), so the documented copy-paste recipe
    # is what breaks if this is let through.
    with pytest.raises(wv.VariableError, match="URL query parameter"):
        wv.parse({"v_a": var("v_a", external_id="my status")})


def test_an_empty_external_id_is_refused_rather_than_read_as_absent() -> None:
    with pytest.raises(wv.VariableError, match="empty external ID"):
        wv.parse({"v_a": var("v_a", external_id="   ")})


def test_two_variables_cannot_share_an_external_id() -> None:
    with pytest.raises(wv.VariableError, match="used by both"):
        wv.parse(
            {
                "v_a": var("v_a", external_id="status", label="First"),
                "v_b": var("v_b", external_id="status", label="Second"),
            }
        )


# ---- precedence: the parent's definition wins (p.122, p.127) -----------------
def test_a_bound_variable_takes_the_hosts_value_and_ignores_its_own_derivation() -> None:
    """Foundry: "Workshop always uses the parent module's variable definition
    and ignores the embedded module's interface variable definition" (p.122)."""
    variables = wv.parse(
        {
            "v_src": var("v_src", default="child"),
            "v_out": var(
                "v_out",
                external_id="out",
                interface=True,
                derivation={"transform": "concat", "inputs": ["v_src"]},
            ),
        }
    )
    # Unbound, the child's own derivation answers.
    assert wv.evaluate(variables, {"v_out": "from host"})["v_out"] == "child"
    # Bound, the host's value does - derivation skipped entirely.
    resolved = wv.evaluate(variables, {"v_out": "from host"}, bound=frozenset({"v_out"}))
    assert resolved["v_out"] == "from host"


def test_a_bound_variable_ignores_the_childs_default() -> None:
    """p.127's first stated consequence of the precedence rule."""
    variables = wv.parse({"v_a": var("v_a", external_id="a", interface=True, default="child")})
    assert wv.evaluate(variables, {}, bound=frozenset({"v_a"}))["v_a"] is None


def test_the_childs_downstream_variables_recompute_from_the_bound_value() -> None:
    """The point of passing a value in: it has to reach what reads it."""
    variables = wv.parse(
        {
            "v_in": var("v_in", external_id="in", interface=True, default="child"),
            "v_label": var(
                "v_label",
                derivation={"transform": "concat", "inputs": ["v_in"], "config": {"separator": ""}},
            ),
        }
    )
    resolved = wv.evaluate(variables, {"v_in": "host"}, bound=frozenset({"v_in"}))
    assert resolved["v_label"] == "host"


# ---- the embed mapping -------------------------------------------------------
def embed_node(module_id: str, mapping: dict | None = None) -> dict:
    props: dict = {"moduleId": module_id}
    if mapping is not None:
        props["interface"] = mapping
    return {"type": {"resolvedName": "CanvasEmbeddedModule"}, "props": props}


def test_the_mapping_is_read_off_the_node() -> None:
    document = {
        "format": 2,
        "layout": {"n1": embed_node("mod-1", {"status": "v_a"})},
        "variables": {"v_a": var("v_a")},
    }
    [embed] = wv.embeds(document)
    assert embed.node == "n1"
    assert embed.module_id == "mod-1"
    assert embed.mapping == {"status": "v_a"}


def test_two_nodes_embedding_one_module_keep_their_own_mappings() -> None:
    """`embedded_modules` returns a set and would lose one of these."""
    document = {
        "format": 2,
        "layout": {
            "n1": embed_node("mod-1", {"status": "v_a"}),
            "n2": embed_node("mod-1", {"status": "v_b"}),
        },
        "variables": {"v_a": var("v_a"), "v_b": var("v_b")},
    }
    assert {e.node: e.mapping["status"] for e in wv.embeds(document)} == {
        "n1": "v_a",
        "n2": "v_b",
    }
    assert wv.embedded_modules(document) == {"mod-1"}


def test_an_unmapped_row_is_dropped_rather_than_refused() -> None:
    """Leaving an interface variable unmapped is legitimate - only `required`
    makes it an error, and that is checked against the child."""
    document = {
        "format": 2,
        "layout": {"n1": embed_node("mod-1", {"status": "", "other": None})},
        "variables": {},
    }
    assert wv.embeds(document)[0].mapping == {}


def test_mapping_to_a_variable_this_module_does_not_declare_is_refused() -> None:
    document = {
        "format": 2,
        "layout": {"n1": embed_node("mod-1", {"status": "v_missing"})},
        "variables": {"v_a": var("v_a")},
    }
    with pytest.raises(wv.VariableError, match="does not declare"):
        wv.validate_module(document)


def test_a_valid_mapping_passes_the_save_path() -> None:
    document = {
        "format": 2,
        "layout": {"n1": embed_node("mod-1", {"status": "v_a"})},
        "variables": {"v_a": var("v_a", label="Status")},
    }
    assert "v_a" in wv.validate_module(document)


# ---- filter_value: reading the filter state back (p.444) ----------------------
def reading_module() -> dict[str, wv.Variable]:
    """A Filter List's clauses, and a label that names what was chosen."""
    return wv.parse(
        {
            "v_clauses": var("v_clauses", kind="array", label="Chosen filters"),
            "v_region": var(
                "v_region", label="Chosen region",
                derivation={"transform": "filter_value", "inputs": ["v_clauses"],
                            "config": {"property": "region"}},
            ),
        }
    )


def test_filter_value_reads_what_the_viewer_chose() -> None:
    """p.444's other half. `narrow_set` *applies* the filter state to a set;
    this reads a value back out of it, which is what "reused in widget
    configurations" means - a heading, a chart title, an action's default."""
    resolved = wv.evaluate(reading_module(), {"v_clauses": [
        {"property": "status", "op": "eq", "value": "open"},
        {"property": "region", "op": "eq", "value": "north"},
    ]})
    assert resolved["v_region"] == "north"


def test_filter_value_on_an_untouched_filter_is_none_not_an_error() -> None:
    """The ordinary state of an app somebody just opened. A derivation that
    raised here would make the first render the broken one - `filter_set`'s
    rule about unset values, one layer up."""
    for empty in ({}, {"v_clauses": None}, {"v_clauses": []}):
        assert wv.evaluate(reading_module(), empty)["v_region"] is None, empty


def test_filter_value_for_a_property_nobody_filtered_on_is_none() -> None:
    resolved = wv.evaluate(reading_module(), {"v_clauses": [
        {"property": "status", "op": "eq", "value": "open"},
    ]})
    assert resolved["v_region"] is None


def test_filter_value_keeps_a_multi_select_whole() -> None:
    """An `in` clause holds several values because the viewer picked several.
    Collapsing that to the first would silently answer a different question."""
    resolved = wv.evaluate(reading_module(), {"v_clauses": [
        {"property": "region", "op": "in", "value": ["north", "south"]},
    ]})
    assert resolved["v_region"] == ["north", "south"]


def test_filter_value_reads_the_first_clause_for_a_property() -> None:
    """Two clauses on one property is a Filter List expressing a range or a
    several-of - one filter with two halves rather than two answers, and
    picking a half here would be this function inventing which one matters."""
    resolved = wv.evaluate(reading_module(), {"v_clauses": [
        {"property": "region", "op": "eq", "value": "north"},
        {"property": "region", "op": "eq", "value": "south"},
    ]})
    assert resolved["v_region"] == "north"


def test_filter_value_refuses_something_that_is_not_a_clause_list() -> None:
    with pytest.raises(wv.VariableError, match="filter clauses"):
        wv.evaluate(reading_module(), {"v_clauses": "north"})


def test_filter_value_needs_one_input_and_a_property() -> None:
    """Refused at *save*, where somebody can still fix it, rather than at view
    time in front of a reader who did not write it."""
    with pytest.raises(wv.VariableError, match="exactly one input"):
        wv.parse({
            "v_a": var("v_a", kind="array"),
            "v_b": var("v_b", kind="array"),
            "v_x": var("v_x", derivation={
                "transform": "filter_value", "inputs": ["v_a", "v_b"],
                "config": {"property": "region"}}),
        })
    with pytest.raises(wv.VariableError, match="needs a property"):
        wv.parse({
            "v_a": var("v_a", kind="array"),
            "v_x": var("v_x", derivation={
                "transform": "filter_value", "inputs": ["v_a"], "config": {}}),
        })


def test_a_filter_can_start_with_a_default_applied() -> None:
    """p.444's **default filters**, and they need nothing new: a variable's
    `default` is where a plain variable starts for every viewer (decision
    0002 §3), and the clause list is a plain variable.

    Worth a test rather than an assumption - "it already works" is exactly the
    claim that turns out to be false, and this is the one line that says it
    does.
    """
    variables = wv.parse(
        {
            "v_clauses": var(
                "v_clauses", kind="array", label="Chosen filters",
                default=[{"property": "region", "op": "eq", "value": "north"}],
            ),
            "v_region": var(
                "v_region", label="Chosen region",
                derivation={"transform": "filter_value", "inputs": ["v_clauses"],
                            "config": {"property": "region"}},
            ),
        }
    )
    assert wv.evaluate(variables, {})["v_region"] == "north"


# ---- time series set variables (p.76, p.582) ---------------------------------
SENSOR = {
    "id": "11111111-2222-3333-4444-555555555555",
    "object_type_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "primary_key": "S1",
    "properties": {"name": "North sensor", "readings": "S1"},
}


def series_module(**config) -> dict:
    """A picked object, and the series one of its properties holds."""
    return wv.parse(
        {
            "v_object": var("v_object", kind="single_object", label="Picked sensor"),
            "v_series": var(
                "v_series", kind="time_series_set", label="Readings",
                derivation={
                    "transform": "object_series", "inputs": ["v_object"],
                    "config": {"property": "readings", **config},
                },
            ),
        }
    )


def test_a_time_series_set_is_a_reference_to_one_objects_property() -> None:
    """p.76: "Stores a time series property of a single object." What comes
    out is the whole question a reader can ask - which object, which property,
    which bucket, which summariser - and `seriesPoints` takes exactly that."""
    resolved = wv.evaluate(series_module(), {"v_object": SENSOR})
    assert resolved["v_series"] == {
        "object_type_id": SENSOR["object_type_id"],
        "instance_id": SENSOR["id"],
        "property": "readings",
        "interval": "day",
        "aggregate": "avg",
    }


def test_a_time_series_set_holds_no_points() -> None:
    """Decision 0009 keeps points in the dataset they arrived in. A variable
    holding points would be the copy that decision refuses, made per viewing
    and per widget - so the resolved value carries a question, never data."""
    resolved = wv.evaluate(series_module(), {"v_object": SENSOR})
    assert "points" not in resolved["v_series"]
    assert set(resolved["v_series"]) == {
        "object_type_id", "instance_id", "property", "interval", "aggregate",
    }


def test_the_bucket_and_summariser_live_on_the_variable() -> None:
    """p.76's "optionally allowing the application of time series transforms
    to it". Two widgets reading one series variable then agree about what a
    point means, which is the difference between a variable and a shortcut."""
    resolved = wv.evaluate(
        series_module(interval="hour", aggregate="max"), {"v_object": SENSOR}
    )
    assert resolved["v_series"]["interval"] == "hour"
    assert resolved["v_series"]["aggregate"] == "max"


def test_nothing_picked_yet_is_an_empty_series_not_an_error() -> None:
    """A detail panel before the first click is an ordinary state, not a
    fault - the same rule `object_property` follows."""
    for empty in ({}, {"v_object": None}, {"v_object": ""}):
        assert wv.evaluate(series_module(), empty)["v_series"] is None, empty


def test_a_series_read_from_a_non_object_is_refused() -> None:
    with pytest.raises(wv.VariableError, match="not an object"):
        wv.evaluate(series_module(), {"v_object": "S1"})


def test_an_object_with_no_id_or_type_cannot_be_asked_for_a_series() -> None:
    """Not a state a viewer can be in: every path that writes a single_object
    writes both. Returning None would render as "no readings yet", a sentence
    about the data when the truth is about the wiring."""
    for broken in (
        {**SENSOR, "id": None},
        {**SENSOR, "object_type_id": None},
        {"properties": {}},
    ):
        with pytest.raises(wv.VariableError, match="no type or no id"):
            wv.evaluate(series_module(), {"v_object": broken})


def test_object_series_needs_one_input_and_a_property() -> None:
    with pytest.raises(wv.VariableError, match="exactly one input"):
        wv.parse({
            "v_a": var("v_a", kind="single_object"),
            "v_b": var("v_b", kind="single_object"),
            "v_x": var("v_x", kind="time_series_set", derivation={
                "transform": "object_series", "inputs": ["v_a", "v_b"],
                "config": {"property": "readings"}}),
        })
    with pytest.raises(wv.VariableError, match="needs a time series property"):
        wv.parse({
            "v_a": var("v_a", kind="single_object"),
            "v_x": var("v_x", kind="time_series_set", derivation={
                "transform": "object_series", "inputs": ["v_a"], "config": {}}),
        })


def test_an_unknown_bucket_or_summariser_is_refused_at_save() -> None:
    """Checked here rather than at read time, because the read is a
    `points_sql` build: an unknown aggregate would surface as a DuckDB parse
    error in front of a viewer, naming a function nobody typed."""
    with pytest.raises(wv.VariableError, match="interval 'fortnight'"):
        series_module(interval="fortnight")
    with pytest.raises(wv.VariableError, match="aggregate 'median'"):
        series_module(aggregate="median")


def test_the_vocabulary_is_the_time_series_services_own() -> None:
    """One list, not two. A bucket this module accepted and `points_sql` did
    not would be refused at read time by the layer with no way to say so."""
    from src.services import time_series

    for interval in time_series.INTERVALS:
        assert series_module(interval=interval) is not None
    for aggregate in time_series.AGGREGATES:
        assert series_module(aggregate=aggregate) is not None


def test_a_time_series_set_that_is_not_derived_is_refused() -> None:
    """There is no static form of a series. One that named no object would
    resolve to whatever `default` held, which for this kind is always a typo."""
    with pytest.raises(wv.VariableError, match="not derived from an object"):
        wv.parse({"v_x": var("v_x", kind="time_series_set", default="S1")})


# ---- routing (p.195-199) -----------------------------------------------------
def routed(vid: str = "v_a", **extra) -> dict:
    """An interface variable configured to appear in the URL."""
    return var(
        vid, external_id=extra.pop("external_id", "region"), interface=True,
        url_behavior=extra.pop("url_behavior", "always"), **extra,
    )


def test_a_variable_says_when_it_belongs_in_the_url() -> None:
    parsed = wv.parse({"v_a": routed()})
    assert parsed["v_a"].url_behavior == "always"


def test_a_variable_that_says_nothing_stays_out_of_the_url() -> None:
    """Foundry's own default, not a caution of ours: routing is opt-in per
    variable, so adding it cannot make an existing module start publishing
    state into the address bar."""
    assert wv.parse({"v_a": var("v_a")})["v_a"].url_behavior == "never"


def test_an_unknown_url_behavior_is_refused_and_names_the_three() -> None:
    with pytest.raises(wv.VariableError, match="url_behavior 'sometimes'"):
        wv.parse({"v_a": routed(url_behavior="sometimes")})


def test_routing_a_variable_that_is_not_on_the_interface_is_refused() -> None:
    """p.198 reads the URL back only for "the external ID of a module interface
    variable", so a routed variable without one would be written out and never
    read back - a shared link restoring everything except what it was shared
    for."""
    with pytest.raises(wv.VariableError, match="not on the module interface"):
        wv.parse({"v_a": var("v_a", url_behavior="always")})
    with pytest.raises(wv.VariableError, match="not on the module interface"):
        # An external ID without the interface toggle is a stable name for
        # state saving and nothing else - `seedFromQuery` already refuses to
        # read one, so writing it would be one end of a link with no other.
        wv.parse({"v_a": var("v_a", external_id="region", url_behavior="always")})


def test_never_needs_no_interface_because_it_writes_nothing() -> None:
    """The refusal is about a promise that cannot be kept. `never` promises
    nothing, so requiring an external ID for it would refuse a document that
    behaves correctly."""
    assert wv.parse({"v_a": var("v_a", url_behavior="never")})["v_a"].url_behavior == "never"


def test_the_kinds_that_cannot_round_trip_are_refused() -> None:
    """p.199's "Unsupported variables types in the URL". Refused at save
    rather than skipped at write time: a builder who ticked "Always in URL"
    and got nothing has no way to tell which end was wrong."""
    for kind, extra in (
        ("single_object", {}),
        ("object_set", {"object_set": {"object_type_id": "t1", "filters": []}}),
        ("time_series_set", {"derivation": {
            "transform": "object_series", "inputs": ["v_o"],
            "config": {"property": "readings"}}}),
        # p.199's other named exclusion. A list needs repeated parameters,
        # which `seedFromQuery` does not read - and writing without reading is
        # exactly what this refusal exists to prevent. The page's own
        # workaround still applies: route a string and use it in the filter's
        # default.
        ("array", {}),
    ):
        with pytest.raises(wv.VariableError, match="cannot be in the URL"):
            wv.parse({
                "v_o": var("v_o", kind="single_object"),
                "v_a": routed(kind=kind, **extra),
            })


def test_every_routable_kind_is_accepted() -> None:
    """A guard on the list itself, from the other side: narrowing it by hand
    cannot quietly stop a scalar being shareable."""
    assert wv.ROUTABLE_KINDS, "the whole point is that some kinds route"
    for kind in wv.ROUTABLE_KINDS:
        assert kind in wv.KINDS, kind
        assert wv.parse({"v_a": routed(kind=kind)})["v_a"].url_behavior == "always"


def test_a_module_says_whether_it_routes_at_all() -> None:
    """One toggle for the whole module (p.195), in the *document* beside the
    per-variable behaviours - so reverting to an old version restores both."""
    assert wv.routing(module({}, {})) is False
    assert wv.routing({**module({}, {}), "routing": {"enabled": True}}) is True
    assert wv.routing({**module({}, {}), "routing": {"enabled": False}}) is False
    assert wv.routing({**module({}, {}), "routing": True}) is True


def test_a_routing_block_nothing_can_read_is_refused_at_save() -> None:
    with pytest.raises(wv.VariableError, match="`routing` must be"):
        wv.validate_module({**module({}, {}), "routing": "yes please"})


# ---- variable-based page selection (p.81) ------------------------------------
def _with_page_selection(value, variables: dict | None = None) -> dict:
    return {**module(variables or {"v_page": var("v_page")}), "page_selection": value}


def test_a_module_says_which_variable_backs_its_page_selection() -> None:
    """p.81's option, in the *document* beside routing and the variables - it
    names one of them, so a revert that restored one without the other would
    leave the setting pointing at nothing."""
    assert wv.page_selection(module({})) is None
    assert wv.page_selection(_with_page_selection("v_page")) == "v_page"


def test_an_absent_or_empty_page_selection_means_none() -> None:
    """Both spellings, because the browser writes the key away rather than
    storing `""` and a document can arrive from anywhere."""
    assert wv.page_selection(_with_page_selection(None)) is None
    assert wv.page_selection(_with_page_selection("")) is None
    assert wv.page_selection(_with_page_selection("   ")) is None


def test_page_selection_naming_a_variable_that_is_not_there_is_refused() -> None:
    """The refusal that earns its keep. A setting pointing at a deleted
    variable is page selection that silently stops working - the module opens
    on its first page and nothing says why."""
    with pytest.raises(wv.VariableError, match="not a variable in this module"):
        wv.validate_module(_with_page_selection("v_gone"))


def test_page_selection_must_name_a_string_variable() -> None:
    """p.81: "a string variable". The value is a page ID, so any other kind
    can only ever fail to match one."""
    # Every kind that is declarable without further configuration. An
    # `object_set` is refused one rule earlier - it needs an object type - so
    # including it here would test that rule rather than this one.
    for kind in ("number", "boolean", "date", "timestamp"):
        with pytest.raises(wv.VariableError, match=f"is a {kind} variable"):
            wv.validate_module(
                _with_page_selection("v_page", {"v_page": var("v_page", kind=kind)})
            )


def test_page_selection_that_is_not_a_string_is_refused() -> None:
    for bad in (True, 7, ["v_page"], {"variable": "v_page"}):
        with pytest.raises(wv.VariableError, match="`page_selection` must be"):
            wv.validate_module(_with_page_selection(bad))


def test_a_valid_page_selection_saves() -> None:
    """The positive case, so the four refusals above are not all this rule
    can do."""
    wv.validate_module(_with_page_selection("v_page"))


def test_page_selection_does_not_check_the_value_against_the_pages() -> None:
    """**Deliberately not checked**, and the asymmetry is the interesting part.

    The variable's *kind* can never work if it is wrong, so the server refuses
    it. The variable's *value* is a page ID resolved at render time, and a page
    can be added or deleted long after a save - so refusing a value that
    currently names no page would make a valid module stop saving because
    somebody renamed a page. p.197's rule ("return to the default page") is a
    rendering decision, and `page-selection.ts` is where it lives.
    """
    document = _with_page_selection("v_page", {"v_page": var("v_page", default="nowhere")})
    document["layout"] = {}  # not one page in the module, let alone that one
    wv.validate_module(document)


def test_a_filter_control_counts_as_a_usage() -> None:
    """The Filter control declares its variable through `name`
    (`workshop_format.DECLARING_PROP`), which after the format-2 conversion
    holds a variable id like every other reference prop - so it belongs in the
    list that decides what may be deleted.

    Missing until routing needed it: `when_visible` asks which variables a
    page's widgets bind, and could not see the one widget whose whole purpose
    is to bind one. The same gap `subjectVariable` had, found the same way.
    """
    variables = wv.parse({"v_a": var("v_a")})
    layout = {"ctl": {"type": {"resolvedName": "CanvasParameterControl"},
                      "props": {"name": "v_a", "label": "Region"}}}
    assert wv.usages(layout, variables)["v_a"] == [{"node": "ctl", "prop": "name"}]


def test_a_filter_control_bound_to_nothing_is_a_dangling_reference() -> None:
    """The failure decision 0002 exists to remove, on the widget that used to
    be exempt from it: a Filter pointed at a variable nothing declares reads as
    no filter at all, so every table it feeds quietly shows everything."""
    broken = wv.dangling_references(
        {"ctl": {"type": {"resolvedName": "CanvasParameterControl"},
                 "props": {"name": "v_gone"}}},
        wv.parse({}),
    )
    assert broken == [{"node": "ctl", "prop": "name", "variable": "v_gone"}]


# ---- state saving (p.200-206) ------------------------------------------------
def savable(vid: str = "v_a", **extra) -> dict:
    return var(
        vid, external_id=extra.pop("external_id", "region"),
        save_state=extra.pop("save_state", True), **extra,
    )


def test_a_variable_says_whether_a_saved_state_keeps_it() -> None:
    assert wv.parse({"v_a": savable()})["v_a"].save_state is True
    assert wv.parse({"v_a": var("v_a")})["v_a"].save_state is False


def test_saving_needs_an_external_id_because_that_is_the_key() -> None:
    """p.203: "Variable values are stored within a saved state via their
    external ID." Foundry's own step 2 is "select a variable and then … add an
    external ID" - the ID is the storage key, not decoration."""
    with pytest.raises(wv.VariableError, match="no key to be stored under"):
        wv.parse({"v_a": var("v_a", save_state=True)})


def test_saving_does_not_need_interface_membership_the_way_routing_does() -> None:
    """The asymmetry worth stating: routing needs the interface because the
    URL is read back by `seedFromQuery`, which only reads interface variables.
    A state is read back by this module, by name - so a stable name is the
    whole requirement."""
    parsed = wv.parse({"v_a": var("v_a", external_id="region", save_state=True)})
    assert parsed["v_a"].save_state is True
    assert parsed["v_a"].interface is None


def test_a_derived_variable_cannot_be_saved_in_a_state() -> None:
    """It is a function of its inputs, so a state holding its value would
    restore an *answer* while the inputs restore the *question* - and the two
    disagree the moment the data behind them moves."""
    with pytest.raises(wv.VariableError, match="derived and cannot be saved"):
        wv.parse({
            "v_in": var("v_in"),
            "v_a": savable(derivation={"transform": "cast", "inputs": ["v_in"],
                                       "config": {"to": "string"}}),
        })


def test_the_kinds_a_state_can_keep_are_p205s_list() -> None:
    """p.205 names Array, Boolean, Date, Object Set, Object Set Filter,
    Numeric, String and Timestamp. **Wider than the URL's list on purpose**: a
    state is a jsonb document, so it can hold a clause list or a set definition
    verbatim where a query string cannot."""
    for kind in wv.SAVABLE_KINDS:
        assert kind in wv.KINDS, kind
    # The two the URL refuses and a state keeps - the difference is the point.
    assert "array" in wv.SAVABLE_KINDS and "array" not in wv.ROUTABLE_KINDS
    assert "object_set" in wv.SAVABLE_KINDS and "object_set" not in wv.ROUTABLE_KINDS
    assert wv.parse({
        "v_a": savable(kind="object_set", object_set={
            "object_type_id": "11111111-2222-3333-4444-555555555555", "filters": []}),
    })["v_a"].save_state is True


def test_a_kind_no_state_can_keep_is_refused() -> None:
    """`time_series_set` is the only unsavable kind, and it is *also* always
    derived - so the kind check has to come first or it can never fire. A
    mutation deleting it survived until the order was fixed, which is the
    clearest possible statement that the branch was dead."""
    with pytest.raises(wv.VariableError, match="is a time_series_set and cannot be saved"):
        wv.parse({
            "v_o": var("v_o", kind="single_object"),
            "v_a": savable(kind="time_series_set", derivation={
                "transform": "object_series", "inputs": ["v_o"],
                "config": {"property": "readings"}}),
        })


def test_savable_variables_are_keyed_by_external_id() -> None:
    """Keyed that way because that is how a state is stored (p.203); reading
    one back has to use the same key or the two halves disagree."""
    variables = wv.parse({
        "v_a": savable("v_a", external_id="region"),
        "v_b": var("v_b", external_id="status"),  # named, not saved
        "v_c": var("v_c"),
    })
    assert set(wv.savable_variables(variables)) == {"region"}
    assert wv.savable_variables(variables)["region"].id == "v_a"


def test_a_module_says_whether_it_saves_state_at_all() -> None:
    assert wv.state_saving(module({}, {})).enabled is False
    assert wv.state_saving({**module({}, {}), "state_saving": True}).enabled is True
    assert wv.state_saving(
        {**module({}, {}), "state_saving": {"enabled": True}}
    ).enabled is True


def test_a_module_can_rename_what_it_calls_a_saved_state() -> None:
    """p.204's "State display name": "If set to a value of `inbox`, module
    consumers will see on-screen references to a saved inbox". Wording only -
    nothing downstream reads these for meaning."""
    settings = wv.state_saving({
        **module({}, {}),
        "state_saving": {"enabled": True, "display_name": "inbox",
                         "display_name_plural": "inboxes"},
    })
    assert (settings.display_name, settings.display_name_plural) == ("inbox", "inboxes")
    # And the defaults are Foundry's own words.
    plain = wv.state_saving({**module({}, {}), "state_saving": True})
    assert (plain.display_name, plain.display_name_plural) == (
        "module state", "module states"
    )


def test_the_page_is_kept_unless_the_module_says_otherwise() -> None:
    """p.200 calls the page "optional"; p.204 makes it a toggle. On by default,
    because a saved view that reopens on a different page is not the view."""
    # Through the *block* path, not the bare `true` shorthand: the shorthand
    # takes the dataclass default and would stay green with the block's own
    # default flipped, which a mutation proved.
    assert wv.state_saving({
        **module({}, {}), "state_saving": {"enabled": True},
    }).include_page is True
    assert wv.state_saving({**module({}, {}), "state_saving": True}).include_page is True
    assert wv.state_saving({
        **module({}, {}), "state_saving": {"enabled": True, "include_page": False},
    }).include_page is False


def test_a_state_saving_block_nothing_can_read_is_refused_at_save() -> None:
    with pytest.raises(wv.VariableError, match="`state_saving` must be"):
        wv.validate_module({**module({}, {}), "state_saving": "yes please"})
    with pytest.raises(wv.VariableError, match="display_name must be a string"):
        wv.state_saving({**module({}, {}), "state_saving": {"display_name": 7}})


# ---- traversing a link between sets (§155's builder half) --------------------
CUSTOMERS = "11111111-1111-1111-1111-111111111111"
ORDERS = "22222222-2222-2222-2222-222222222222"
PLACED_BY = "33333333-3333-3333-3333-333333333333"


def traversing(**config) -> dict:
    return {
        "v_customers": var("v_customers", kind="object_set", label="Customers",
                           object_set={"object_type_id": CUSTOMERS, "filters": []}),
        "v_orders": var(
            "v_orders", kind="object_set", label="Their orders",
            derivation={
                "transform": "traverse_set", "inputs": ["v_customers"],
                "config": {"link_type_id": PLACED_BY, "object_type_id": ORDERS, **config},
            },
        ),
    }


def test_a_set_can_follow_a_link_from_another_set() -> None:
    resolved = wv.evaluate(wv.parse(traversing()), {})
    assert resolved["v_orders"] == {
        "object_type_id": ORDERS,
        "filters": [],
        "via": {"link_type_id": PLACED_BY,
                "base": {"object_type_id": CUSTOMERS, "filters": []}},
    }


def test_the_base_stays_a_reference_rather_than_a_copy() -> None:
    """The whole reason this is a derivation. A builder that inlined the base's
    definition would freeze it, and narrowing the customers afterwards would
    leave the orders reading the set as it was when somebody drew the arrow -
    so the base is followed *after* it has been filtered, not before."""
    variables = wv.parse({
        "v_customers": var("v_customers", kind="object_set", label="Customers",
                           object_set={"object_type_id": CUSTOMERS, "filters": []}),
        "v_region": var("v_region", label="Region"),
        "v_northern": var(
            "v_northern", kind="object_set", label="Northern customers",
            derivation={"transform": "filter_set", "inputs": ["v_customers", "v_region"],
                        "config": {"property": "region", "op": "eq"}},
        ),
        "v_orders": var(
            "v_orders", kind="object_set", label="Their orders",
            derivation={"transform": "traverse_set", "inputs": ["v_northern"],
                        "config": {"link_type_id": PLACED_BY, "object_type_id": ORDERS}},
        ),
    })
    resolved = wv.evaluate(variables, {"v_region": "north"})
    base = resolved["v_orders"]["via"]["base"]
    assert base["object_type_id"] == CUSTOMERS
    assert base["filters"] == [{"property": "region", "op": "eq", "value": "north"}]
    # And they stay on the near side. Copying them across would filter *orders*
    # on `region` - a property they do not have, so the honest answer would be
    # no rows, arrived at by a rule nobody wrote.
    assert resolved["v_orders"]["filters"] == []


def test_a_traversal_can_be_narrowed_afterwards() -> None:
    """All three set transforms speak the same currency - a definition - so a
    traversal composes with narrowing in both directions with no special
    case."""
    variables = wv.parse({
        **traversing(),
        "v_clauses": var("v_clauses", kind="array", label="Filters"),
        "v_narrowed": var(
            "v_narrowed", kind="object_set", label="Narrowed orders",
            derivation={"transform": "narrow_set", "inputs": ["v_orders", "v_clauses"]},
        ),
    })
    resolved = wv.evaluate(variables, {
        "v_clauses": [{"property": "total", "op": "eq", "value": "20"}],
    })
    assert resolved["v_narrowed"]["via"]["link_type_id"] == PLACED_BY
    assert resolved["v_narrowed"]["filters"] == [
        {"property": "total", "op": "eq", "value": "20"}
    ]


def test_a_traversal_needs_one_input_a_link_and_a_landing_type() -> None:
    with pytest.raises(wv.VariableError, match="exactly one input"):
        wv.parse({
            "v_a": var("v_a", kind="object_set",
                       object_set={"object_type_id": CUSTOMERS, "filters": []}),
            "v_b": var("v_b", kind="object_set",
                       object_set={"object_type_id": CUSTOMERS, "filters": []}),
            "v_x": var("v_x", kind="object_set", derivation={
                "transform": "traverse_set", "inputs": ["v_a", "v_b"],
                "config": {"link_type_id": PLACED_BY, "object_type_id": ORDERS}}),
        })
    for missing in ("link_type_id", "object_type_id"):
        config = {"link_type_id": PLACED_BY, "object_type_id": ORDERS}
        del config[missing]
        with pytest.raises(wv.VariableError, match=f"needs a {missing}"):
            wv.parse({
                "v_a": var("v_a", kind="object_set",
                           object_set={"object_type_id": CUSTOMERS, "filters": []}),
                "v_x": var("v_x", kind="object_set", derivation={
                    "transform": "traverse_set", "inputs": ["v_a"], "config": config}),
            })


def test_following_a_link_from_something_that_is_not_a_set_is_refused() -> None:
    variables = wv.parse({
        "v_text": var("v_text", label="Just text"),
        "v_x": var("v_x", kind="object_set", derivation={
            "transform": "traverse_set", "inputs": ["v_text"],
            "config": {"link_type_id": PLACED_BY, "object_type_id": ORDERS}}),
    })
    with pytest.raises(wv.VariableError, match="not an object set"):
        wv.evaluate(variables, {"v_text": "north"})


# ---- p.85's Reset {variable} value -------------------------------------------
def reset_effect(target: str = "v_a") -> dict:
    return {"type": "reset_variable", "config": {"variable": target}}


def _reset_module(variables: dict) -> dict:
    return {"format": 2, "layout": {"btn": node({})},
            "variables": variables, "events": {}}


def test_resetting_a_static_variable_is_accepted() -> None:
    """p.85: "set the value of the chosen variable to its default value, which
    is the value configured in the variable definition"."""
    events = we.parse(
        {"e_1": event("e_1", effects=[reset_effect()])},
        layout={"btn": node({})},
        variables=wv.parse({"v_a": var("v_a", default="north")}),
    )
    assert [e.type for e in events["e_1"].effects] == ["reset_variable"]


def test_reset_needs_a_variable_that_the_module_declares() -> None:
    with pytest.raises(we.EventError, match="needs a variable"):
        we.parse({"e_1": event("e_1", effects=[{"type": "reset_variable", "config": {}}])},
                 layout={"btn": node({})})
    with pytest.raises(we.EventError, match="does not declare"):
        we.parse({"e_1": event("e_1", effects=[reset_effect("v_gone")])},
                 layout={"btn": node({})},
                 variables=wv.parse({"v_a": var("v_a")}))


def test_resetting_a_derived_variable_is_refused() -> None:
    """**p.85 offers Reset "for static variables", and the qualifier is the
    refusal.** A derived variable is a function of its inputs, so "the value
    configured in the variable definition" names something it does not have -
    and a Reset on one would be a click with no effect."""
    variables = wv.parse({
        "v_a": var("v_a", default="north"),
        "v_b": var("v_b", derivation={"transform": "concat", "inputs": ["v_a"]}),
    })
    with pytest.raises(we.EventError, match="derived variable"):
        we.parse({"e_1": event("e_1", effects=[reset_effect("v_b")])},
                 layout={"btn": node({})}, variables=variables)


def test_resetting_an_object_set_with_its_own_definition_is_refused() -> None:
    """The same case by another route: such a variable resolves to its own
    definition whatever the viewer does, so there is nothing to put back."""
    variables = wv.parse({
        "v_set": {"id": "v_set", "kind": "object_set", "label": "Set",
                  "object_set": {"object_type_id": str(uuid.uuid4()), "filters": []}},
    })
    with pytest.raises(we.EventError, match="object set with its own definition"):
        we.parse({"e_1": event("e_1", effects=[reset_effect("v_set")])},
                 layout={"btn": node({})}, variables=variables)


# ---- p.76's recompute behaviours, and p.85's Recompute event ------------------
def _derived(vid: str = "v_b", **extra) -> dict:
    return {"id": vid, "kind": "string", "label": vid,
            "derivation": {"transform": "concat", "inputs": ["v_a"]}, **extra}


def _recompute_vars(**extra) -> dict:
    return {"v_a": var("v_a", default="north"), "v_b": _derived(**extra)}


@pytest.mark.parametrize("behaviour", ["automatic", "only_on_event", "on_load_and_event"])
def test_p76s_three_recompute_behaviours_parse(behaviour: str) -> None:
    parsed = wv.parse(_recompute_vars(recompute=behaviour))
    assert parsed["v_b"].recompute == behaviour


def test_an_absent_behaviour_means_automatic() -> None:
    """A stored "automatic" and a missing field have to mean the same thing, or
    upgrading the platform would change what every module written before this
    existed does."""
    assert wv.parse(_recompute_vars())["v_b"].recompute == "automatic"


def test_an_unknown_behaviour_is_refused() -> None:
    with pytest.raises(wv.VariableError, match="expected one of"):
        wv.parse(_recompute_vars(recompute="sometimes"))


def test_a_static_variable_cannot_configure_recompute() -> None:
    """p.76 offers it on derived definitions only - a static variable holds
    what somebody typed, so there is nothing to defer."""
    with pytest.raises(wv.VariableError, match="is static, so it has nothing to recompute"):
        wv.parse({"v_a": var("v_a", recompute="only_on_event")})


def test_an_object_set_definition_cannot_configure_recompute() -> None:
    """p.76 says so in its own words: "The Object set definition variable
    definition type does not offer recompute behavior configuration"."""
    with pytest.raises(wv.VariableError, match="does not offer recompute behaviour"):
        wv.parse({
            "v_set": {"id": "v_set", "kind": "object_set", "label": "Set",
                      "recompute": "only_on_event",
                      "object_set": {"object_type_id": str(uuid.uuid4()), "filters": []}},
        })


def test_automatic_is_accepted_on_anything_because_it_changes_nothing() -> None:
    """The one behaviour that is not a *setting*: it is what every variable
    already does, so refusing it on a static variable would refuse a document
    that says nothing."""
    wv.parse({"v_a": var("v_a", recompute="automatic")})


# ---- what the evaluator does with a held value --------------------------------
def test_an_automatic_variable_recomputes_every_time() -> None:
    variables = wv.parse(_recompute_vars())
    resolved = wv.evaluate(variables, {"v_a": "south"}, held={"v_b": "stale"})
    # The held value is ignored: this variable did not ask to hold one.
    assert resolved["v_b"] == "south"


def test_a_held_variable_keeps_what_it_last_computed() -> None:
    variables = wv.parse(_recompute_vars(recompute="on_load_and_event"))
    resolved = wv.evaluate(variables, {"v_a": "south"}, held={"v_b": "north"})
    assert resolved["v_b"] == "north"


def test_on_load_and_event_computes_when_nothing_is_held() -> None:
    """p.76: "recomputed when the module is initially loaded"."""
    variables = wv.parse(_recompute_vars(recompute="on_load_and_event"))
    assert wv.evaluate(variables, {"v_a": "south"})["v_b"] == "south"


def test_only_on_event_does_not_compute_at_load() -> None:
    """**The one place the two behaviours differ**, and the reason they are two
    options rather than one. p.76: recomputed "only when explicitly triggered"
    - so computing it at load would make this identical to the other."""
    variables = wv.parse(_recompute_vars(recompute="only_on_event"))
    assert wv.evaluate(variables, {"v_a": "south"})["v_b"] is None


def test_a_held_value_is_what_downstream_variables_read() -> None:
    """**The reason the held value goes to the server at all.**

    Freezing it in the browser would leave the variable showing one number
    while its dependants recomputed from a fresh copy - two different answers
    to the same question on one page.
    """
    variables = wv.parse({
        "v_a": var("v_a", default="north"),
        "v_b": _derived("v_b", recompute="only_on_event"),
        "v_c": {"id": "v_c", "kind": "string", "label": "C",
                "derivation": {"transform": "concat", "inputs": ["v_b"]}},
    })
    resolved = wv.evaluate(variables, {"v_a": "south"}, held={"v_b": "held"})
    assert resolved["v_b"] == "held"
    assert resolved["v_c"] == "held"


def test_a_static_variable_resolves_normally_whatever_its_behaviour_says() -> None:
    """The guard that keeps the held branch to *derived* variables.

    `parse` refuses a behaviour on a static variable, so this state cannot be
    reached through a document - which is exactly why the guard needs a test of
    its own. `evaluate` is a public function over `Variable` objects, and
    without the `derivation is not None` half a static variable marked this way
    falls into the held branch and resolves to **None** instead of its value:
    a control that silently stops reporting what somebody typed into it.

    Built by hand rather than parsed, deliberately. Going through `parse` could
    only ever produce the refusal, which is a different test (and is above).
    """
    variables = {
        "v_a": wv.Variable(id="v_a", kind="string", label="A", default="typed",
                           recompute="only_on_event"),
    }
    assert wv.evaluate(variables, {})["v_a"] == "typed"
    assert wv.evaluate(variables, {"v_a": "chosen"})["v_a"] == "chosen"


# ---- p.85's event arriving: `recompute_now` -----------------------------------
def test_only_on_event_computes_when_the_event_asks() -> None:
    """**The whole point of `only_on_event`, and the case an absence cannot
    express.**

    Its state at load and its state the instant an event fires are both "nothing
    held". If the ask were spelled as a missing `held` entry, this call would be
    byte-identical to a fresh page, and the event would do nothing forever.
    """
    variables = wv.parse(_recompute_vars(recompute="only_on_event"))
    resolved = wv.evaluate(
        variables, {"v_a": "south"}, recompute_now=frozenset({"v_b"}),
    )
    assert resolved["v_b"] == "south"


def test_the_ask_wins_over_what_is_held() -> None:
    """So the caller does not have to drop its memory to make an event land -
    which is the thing it cannot do unambiguously for `only_on_event`."""
    variables = wv.parse(_recompute_vars(recompute="on_load_and_event"))
    resolved = wv.evaluate(
        variables, {"v_a": "south"}, held={"v_b": "north"},
        recompute_now=frozenset({"v_b"}),
    )
    assert resolved["v_b"] == "south"


def test_an_ask_recomputes_only_the_variable_it_names() -> None:
    """A Recompute event names one variable (p.85). Everything else still holds,
    or the event would be a page refresh wearing a variable's name."""
    variables = wv.parse({
        "v_a": var("v_a", default="north"),
        "v_b": _derived("v_b", recompute="only_on_event"),
        "v_c": {"id": "v_c", "kind": "string", "label": "C", "recompute": "only_on_event",
                "derivation": {"transform": "concat", "inputs": ["v_a"]}},
    })
    resolved = wv.evaluate(
        variables, {"v_a": "south"}, held={"v_b": "held b", "v_c": "held c"},
        recompute_now=frozenset({"v_b"}),
    )
    assert resolved["v_b"] == "south"
    assert resolved["v_c"] == "held c"


def test_an_ask_for_an_automatic_variable_changes_nothing() -> None:
    """It recomputes every time anyway. Worth pinning because the effect is
    refused at save time, so anything arriving here is a document that moved -
    and the answer should be the ordinary one, not a special case."""
    variables = wv.parse(_recompute_vars())
    resolved = wv.evaluate(
        variables, {"v_a": "south"}, recompute_now=frozenset({"v_b"}),
    )
    assert resolved["v_b"] == "south"


def test_a_recomputed_value_is_what_downstream_variables_read() -> None:
    """The same rule as the held case, on the other side of an event: one
    answer to one question on one page."""
    variables = wv.parse({
        "v_a": var("v_a", default="north"),
        "v_b": _derived("v_b", recompute="only_on_event"),
        "v_c": {"id": "v_c", "kind": "string", "label": "C",
                "derivation": {"transform": "concat", "inputs": ["v_b"]}},
    })
    resolved = wv.evaluate(
        variables, {"v_a": "south"}, held={"v_b": "held"},
        recompute_now=frozenset({"v_b"}),
    )
    assert resolved["v_b"] == "south"
    assert resolved["v_c"] == "south"


def test_a_bound_variable_ignores_an_ask_to_recompute() -> None:
    """p.127 again: the host's value wins, and an event in the child cannot
    reach past it - the child's derivation is skipped "derivation and all"."""
    variables = wv.parse(_recompute_vars(recompute="only_on_event"))
    resolved = wv.evaluate(
        variables, {"v_b": "from the host"}, bound=frozenset({"v_b"}),
        recompute_now=frozenset({"v_b"}),
    )
    assert resolved["v_b"] == "from the host"


def test_a_bound_variable_ignores_its_own_recompute_behaviour() -> None:
    """p.127: the host's definition wins and the child's is skipped, "derivation
    and all" - which includes the behaviour that would have held a value."""
    variables = wv.parse(_recompute_vars(recompute="only_on_event"))
    resolved = wv.evaluate(
        variables, {"v_b": "from the host"}, bound=frozenset({"v_b"}), held={"v_b": "held"},
    )
    assert resolved["v_b"] == "from the host"


# ---- p.85's Recompute event ---------------------------------------------------
def test_recomputing_a_held_variable_is_accepted() -> None:
    variables = wv.parse(_recompute_vars(recompute="only_on_event"))
    events = we.parse(
        {"e_1": event("e_1", effects=[{"type": "recompute", "config": {"variable": "v_b"}}])},
        layout={"btn": node({})}, variables=variables,
    )
    assert [e.type for e in events["e_1"].effects] == ["recompute"]


def test_recompute_needs_a_declared_variable() -> None:
    with pytest.raises(we.EventError, match="needs a variable"):
        we.parse({"e_1": event("e_1", effects=[{"type": "recompute", "config": {}}])},
                 layout={"btn": node({})})
    with pytest.raises(we.EventError, match="does not declare"):
        we.parse(
            {"e_1": event("e_1",
                          effects=[{"type": "recompute", "config": {"variable": "v_x"}}])},
            layout={"btn": node({})}, variables=wv.parse(_recompute_vars()),
        )


def test_recomputing_a_static_variable_is_refused() -> None:
    """p.85 offers Recompute "for non-static variable types" - the exact
    complement of Reset, which it offers for static ones."""
    with pytest.raises(we.EventError, match="which is static"):
        we.parse(
            {"e_1": event("e_1",
                          effects=[{"type": "recompute", "config": {"variable": "v_a"}}])},
            layout={"btn": node({})}, variables=wv.parse(_recompute_vars()),
        )


def test_recomputing_an_automatic_variable_is_refused() -> None:
    """**The sharper refusal, and the one p.85 only implies.** A variable on
    Automatic already recomputes when its inputs change (p.76), so an event
    aimed at one is a click with no effect - the whole class of thing this
    module refuses."""
    with pytest.raises(we.EventError, match="on Automatic recompute"):
        we.parse(
            {"e_1": event("e_1",
                          effects=[{"type": "recompute", "config": {"variable": "v_b"}}])},
            layout={"btn": node({})}, variables=wv.parse(_recompute_vars()),
        )


def test_recompute_is_no_longer_a_planned_effect() -> None:
    """It was in `PLANNED_EFFECTS` for precisely the right reason and for
    precisely as long as the reason held: with every derived variable
    recomputing on every resolve there was nothing for it to trigger."""
    assert "recompute" not in we.PLANNED_EFFECTS
    assert "recompute" in we.EFFECTS


def test_the_builder_offers_every_effect_the_server_accepts() -> None:
    """**The guard that would have caught §190's gap.**

    `switch_tab` was added to the server's `EFFECTS` and never to the builder's
    catalogue, so it was legal to save and impossible to create - a feature
    reachable only by hand-editing the raw JSON. Nothing noticed, because the
    two lists are in different languages and neither is derived from the other.

    The panel's list must cover exactly what the server accepts, minus the ones
    the server refuses with a reason: offering a refused effect is offering a
    choice that fails on save, and *not* offering an accepted one is the gap
    above.
    """
    import re

    panel = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "web", "src", "components", "canvas", "EventsPanel.tsx",
    )
    source = open(panel).read()
    block = re.search(
        r"const EFFECTS: \{ type: string; label: string; hint: string \}\[\] = \[(.*?)\n\];",
        source, re.S,
    )
    assert block, "EFFECTS not found in EventsPanel.tsx - has it been renamed?"
    # **Types *and* labels, and the labels are the vacuity guard.** Reading only
    # the types lets this test be quietly turned into a comparison of the
    # server's list with itself - which passes for any panel at all. A label is
    # something only the panel has: an `<option>` with no text is not an offer,
    # so requiring one is both the check and the proof that the panel was read.
    catalogue = dict(re.findall(r'type: "([^"]+)",\s*label: "([^"]+)"', block.group(1)))
    offered = set(catalogue)
    assert offered, "the catalogue parsed as empty - the scan broke, not the panel"
    assert all(catalogue.values()), catalogue
    assert catalogue.get("reset_variable") == "Reset a variable", (
        "the scan is not reading EventsPanel.tsx - it should have found this "
        f"entry's label, and found {catalogue.get('reset_variable')!r}"
    )
    accepted = set(we.EFFECTS) - set(we.PLANNED_EFFECTS)
    assert offered == accepted, (
        f"the builder offers {sorted(offered)}; the server accepts "
        f"{sorted(accepted)}. An effect the server takes but the panel does not "
        "offer can only be created by hand-editing the raw JSON"
    )


# ---- tabs sections and p.84's switch_tab (p.54, p.84) ------------------------
def tabs_layout(*, tabs: str = "Overview,Details", children: int = 2,
                direction: str = "tabs", tab_variable=None) -> dict:
    kids = [f"t{i}" for i in range(children)]
    layout = {
        "ROOT": {"type": {"resolvedName": "CanvasContainer"}, "nodes": ["sec", "btn"]},
        "sec": {
            "type": {"resolvedName": "CanvasSection"},
            "props": {"direction": direction, "tabs": tabs,
                      **({"tabVariable": tab_variable} if tab_variable is not None else {})},
            "nodes": kids,
        },
        "btn": node({}),
        **{k: {**node({}), "parent": "sec"} for k in kids},
    }
    return layout


def switch_tab(tab: str = "Details", section: str = "sec") -> dict:
    return {"type": "switch_tab", "config": {"section": section, "tab": tab}}


def test_a_tabs_section_reports_its_tab_names() -> None:
    """p.84 addresses a tab by name - "a Switch to {tab name} event will be
    added for each tab in the section" - so validating one means knowing what
    this section's tabs are called."""
    assert we.tab_sections(tabs_layout()) == {"sec": ["Overview", "Details"]}


def test_only_a_tabs_section_has_tabs() -> None:
    """Same qualifier as p.82's "collapsible section", and the same refusal
    depends on it: a Columns section has no tabs to switch between."""
    assert we.tab_sections(tabs_layout(direction="columns")) == {}


def test_tab_names_are_numbered_where_unnamed_and_made_unique() -> None:
    """**Mirrors `tabLabels` in `tab-selection.ts`**, and this is the assertion
    that keeps the two in step: if they drift, the browser draws a tab the
    server will not let an event name."""
    assert we.tab_sections(tabs_layout(tabs="Overview", children=3)) == {
        "sec": ["Overview", "Tab 2", "Tab 3"],
    }
    assert we.tab_sections(tabs_layout(tabs="Same,Same", children=2)) == {
        "sec": ["Same", "Same 2"],
    }
    assert we.tab_sections(tabs_layout(tabs="A,B,C", children=2)) == {"sec": ["A", "B"]}


def test_switching_to_a_tab_that_exists_is_accepted() -> None:
    events = we.parse({"e_1": event("e_1", effects=[switch_tab()])}, layout=tabs_layout())
    assert [e.type for e in events["e_1"].effects] == ["switch_tab"]


def test_switch_tab_needs_a_section_and_a_tab() -> None:
    with pytest.raises(we.EventError, match="needs a section"):
        we.parse({"e_1": event("e_1", effects=[{"type": "switch_tab", "config": {}}])},
                 layout=tabs_layout())
    with pytest.raises(we.EventError, match="needs a tab"):
        we.parse(
            {"e_1": event("e_1", effects=[{"type": "switch_tab",
                                           "config": {"section": "sec"}}])},
            layout=tabs_layout(),
        )


def test_switching_a_tab_in_a_section_that_is_not_tabbed_is_refused() -> None:
    """p.84 offers the event "for each Tab section", and a Columns section has
    no tabs - so this would save a button that does nothing."""
    with pytest.raises(we.EventError, match="not a Tabs section"):
        we.parse({"e_1": event("e_1", effects=[switch_tab()])},
                 layout=tabs_layout(direction="columns"))


def test_switching_to_a_tab_the_section_does_not_have_is_refused() -> None:
    """The usual cause is a rename: the event was right when it was written
    and the section moved underneath it. So the refusal names the tabs that
    *are* there."""
    with pytest.raises(we.EventError, match="Its tabs are: 'Overview', 'Details'"):
        we.parse({"e_1": event("e_1", effects=[switch_tab("Histroy")])},
                 layout=tabs_layout())


def test_switching_a_tab_in_a_node_that_is_not_there_is_refused() -> None:
    with pytest.raises(we.EventError, match="does not contain"):
        we.parse({"e_1": event("e_1", effects=[switch_tab("Details", "gone")])},
                 layout=tabs_layout())


def tabs_module(**kwargs) -> dict:
    variables = kwargs.pop("variables", {"v_tab": var("v_tab")})
    return {"format": 2, "layout": tabs_layout(**kwargs),
            "variables": variables, "events": {}}


def test_a_tab_variable_must_name_a_declared_string() -> None:
    """The section-level twin of `page_selection`, and the argument is
    identical: p.84 says "the string variable configured for Variable-Based
    Tab Selection"."""
    wv.validate_module(tabs_module(tab_variable="v_tab"))
    with pytest.raises(wv.VariableError, match="not a variable in this module"):
        wv.validate_module(tabs_module(tab_variable="v_gone"))
    with pytest.raises(wv.VariableError, match="is a number variable"):
        wv.validate_module(tabs_module(
            tab_variable="v_tab", variables={"v_tab": var("v_tab", kind="number")},
        ))


def test_no_tab_variable_is_the_ordinary_case() -> None:
    wv.validate_module(tabs_module())
    wv.validate_module(tabs_module(tab_variable=""))


def test_a_tab_variables_value_is_not_checked_against_the_tabs() -> None:
    """**Deliberately not checked.** Tabs get renamed long after a save, and
    refusing a stale value would make a valid module unsaveable because
    somebody edited a label. `activeTab` falls back to the first tab, which is
    the rendering answer to the same question."""
    wv.validate_module(tabs_module(
        tab_variable="v_tab",
        variables={"v_tab": var("v_tab", default="a tab nobody has")},
    ))


def test_a_section_with_more_tabs_than_a_strip_can_hold_is_refused() -> None:
    """Structural, unlike the value above: past `MAX_TABS` a tab strip has
    stopped being one, and no amount of later editing makes forty buttons in a
    row readable."""
    with pytest.raises(wv.VariableError, match="the limit is"):
        wv.validate_module(tabs_module(tabs="", children=we.MAX_TABS + 1))
    wv.validate_module(tabs_module(tabs="", children=we.MAX_TABS))


# ---- collapsible sections (p.55, p.82) ---------------------------------------
def section_node(*, collapsible: bool = True) -> dict:
    return {
        "type": {"resolvedName": "CanvasSection"},
        "props": {"direction": "columns", "collapsible": collapsible},
        "nodes": [],
    }


def collapse_layout(*, collapsible: bool = True) -> dict:
    return {
        "ROOT": {"type": {"resolvedName": "CanvasContainer"}, "nodes": ["sec", "btn"]},
        "sec": section_node(collapsible=collapsible),
        "btn": node({}),
    }


def section_effect(kind: str, section: str = "sec") -> dict:
    return {"type": kind, "config": {"section": section}}


@pytest.mark.parametrize("kind", ["expand_section", "collapse_section", "toggle_section"])
def test_p82s_three_section_effects_are_accepted(kind: str) -> None:
    """p.82: "For each collapsible section in the module, the following three
    events are available: Expand… Collapse… Toggle"."""
    events = we.parse(
        {"e_1": event("e_1", effects=[section_effect(kind)])},
        layout=collapse_layout(),
    )
    assert [e.type for e in events["e_1"].effects] == [kind]


def test_collapsible_sections_are_read_from_the_layout() -> None:
    assert we.collapsible_sections(collapse_layout()) == ["sec"]
    # **Marked, not merely a section.** The qualifier in p.82's sentence is
    # the whole refusal below.
    assert we.collapsible_sections(collapse_layout(collapsible=False)) == []


def test_a_section_effect_needs_a_section() -> None:
    with pytest.raises(we.EventError, match="needs a section"):
        we.parse(
            {"e_1": event("e_1", effects=[{"type": "toggle_section", "config": {}}])},
            layout=collapse_layout(),
        )


def test_a_section_effect_on_a_node_that_is_not_there_is_refused() -> None:
    with pytest.raises(we.EventError, match="does not contain"):
        we.parse(
            {"e_1": event("e_1", effects=[section_effect("expand_section", "gone")])},
            layout=collapse_layout(),
        )


def test_a_section_effect_on_a_section_that_cannot_collapse_is_refused() -> None:
    """**The refusal p.82's own wording asks for.** Its three events are
    offered "for each collapsible section", and a section that cannot collapse
    has no state for them to change - so this would save a button that does
    nothing, which is the one outcome nobody can debug from the outside."""
    with pytest.raises(we.EventError, match="not a collapsible section"):
        we.parse(
            {"e_1": event("e_1", effects=[section_effect("collapse_section")])},
            layout=collapse_layout(collapsible=False),
        )


def test_a_section_effect_aimed_at_a_widget_is_refused_for_the_same_reason() -> None:
    """A button is in the layout and is not collapsible. Checking only
    membership would accept this and produce a click that does nothing."""
    with pytest.raises(we.EventError, match="not a collapsible section"):
        we.parse(
            {"e_1": event("e_1", effects=[section_effect("toggle_section", "btn")])},
            layout=collapse_layout(),
        )


# ---- p.132's array element type -----------------------------------------------
@pytest.mark.parametrize("element", wv.ARRAY_ELEMENTS)
def test_every_element_type_p132_lists_parses(element: str) -> None:
    variables = wv.parse({
        "v_a": {"id": "v_a", "kind": "array", "label": "A", "element": element},
    })
    assert variables["v_a"].element == element


def test_an_array_may_carry_no_element_at_all() -> None:
    """**Optional rather than defaulted.** Every array written before this
    existed has none, and picking one for them would be inventing a fact about
    somebody's document. It stays valid; it simply cannot be looped over."""
    assert wv.parse({"v_a": {"id": "v_a", "kind": "array", "label": "A"}})["v_a"].element is None


def test_a_struct_element_is_refused_with_its_own_reason() -> None:
    """p.132 lists struct arrays, so somebody reading the spec will try it -
    and "expected one of string, number…" would read as the spec being wrong
    rather than as this platform being behind."""
    with pytest.raises(wv.VariableError, match="named fields"):
        wv.parse({"v_a": {"id": "v_a", "kind": "array", "label": "A", "element": "struct"}})


def test_an_unknown_element_is_refused() -> None:
    with pytest.raises(wv.VariableError, match="expected one of"):
        wv.parse({"v_a": {"id": "v_a", "kind": "array", "label": "A", "element": "widget"}})


def test_an_element_on_a_non_array_is_refused() -> None:
    """A setting with no effect is the shape this module refuses everywhere."""
    with pytest.raises(wv.VariableError, match="has no entries"):
        wv.parse({"v_a": {"id": "v_a", "kind": "string", "label": "A", "element": "string"}})


# ---- p.133's loop source -------------------------------------------------------
def _loop(**props: Any) -> dict[str, Any]:
    return {"loop": {"type": {"resolvedName": "CanvasLoopSection"}, "props": props}}


def _module(layout: dict[str, Any], variables: dict[str, Any]) -> dict[str, Any]:
    return {"format": 2, "layout": layout, "variables": variables, "events": {}}


ARR = {"v_arr": {"id": "v_arr", "kind": "array", "label": "Names", "element": "string"}}


def test_a_loop_over_a_typed_array_is_accepted() -> None:
    wv.validate_module(_module(_loop(source="array", arrayVariable="v_arr"), ARR))


def test_an_object_set_loop_is_untouched_by_the_new_check() -> None:
    """The arm that already worked. Worth pinning because the check reads a
    prop that older documents do not carry at all."""
    wv.validate_module(_module(_loop(objectSetVariable="v_set"), {
        "v_set": {"id": "v_set", "kind": "object_set", "label": "Set",
                  "object_set": {"object_type_id": str(uuid.uuid4()), "filters": []}},
    }))


def test_an_array_loop_naming_nothing_is_refused() -> None:
    """p.133 makes the array to loop through the first configuration."""
    with pytest.raises(wv.VariableError, match="names none"):
        wv.validate_module(_module(_loop(source="array"), ARR))


def test_an_array_loop_naming_an_undeclared_variable_is_refused() -> None:
    with pytest.raises(wv.VariableError, match="does not declare"):
        wv.validate_module(_module(_loop(source="array", arrayVariable="v_gone"), ARR))


def test_an_array_loop_over_a_non_array_is_refused() -> None:
    with pytest.raises(wv.VariableError, match="not an array"):
        wv.validate_module(_module(_loop(source="array", arrayVariable="v_s"), {
            "v_s": {"id": "v_s", "kind": "string", "label": "S"},
        }))


def test_an_array_loop_over_an_untyped_array_is_refused() -> None:
    """**The refusal that makes p.134 checkable.**

    An untyped array has no type for the child's variable to match, so the
    alternative to refusing is a loop that passes any entry to any variable and
    renders whatever happens to fit.
    """
    with pytest.raises(wv.VariableError, match="no element type"):
        wv.validate_module(_module(_loop(source="array", arrayVariable="v_arr"), {
            "v_arr": {"id": "v_arr", "kind": "array", "label": "Names"},
        }))


def test_an_unknown_loop_source_is_refused() -> None:
    with pytest.raises(wv.VariableError, match="p.133 offers"):
        wv.validate_module(_module(_loop(source="sideways", arrayVariable="v_arr"), ARR))


# ---- what the child's item variable has to be (p.134) --------------------------
def test_an_array_loop_asks_for_the_elements_kind_not_array() -> None:
    """**p.134's sentence, read the way p.134 settles it.**

    "a variable typed to the array type" could mean the child receives the
    whole array. Two sentences later p.134 says the struct-typed variable
    "renders the fields of each struct entry", so the child receives one
    *entry* - and handing every copy the whole array would not be a loop.
    """
    embeds = wv.embeds(_module(
        _loop(source="array", arrayVariable="v_arr", moduleId="m1", itemVariable="each"),
        ARR,
    ))
    assert [e.item_kind for e in embeds] == ["string"]


def test_an_object_set_loop_still_asks_for_a_single_object() -> None:
    embeds = wv.embeds(_module(
        _loop(objectSetVariable="v_set", moduleId="m1", itemVariable="each"),
        {"v_set": {"id": "v_set", "kind": "object_set", "label": "Set",
                   "object_set": {"object_type_id": str(uuid.uuid4()), "filters": []}}},
    ))
    assert [e.item_kind for e in embeds] == ["single_object"]


def test_an_untyped_array_leaves_the_item_kind_unknown() -> None:
    """So the cross-module check stays quiet and the layout check gets to
    report the real fault - which is on the host, not on the child."""
    embeds = wv.embeds(_module(
        _loop(source="array", arrayVariable="v_arr", moduleId="m1", itemVariable="each"),
        {"v_arr": {"id": "v_arr", "kind": "array", "label": "Names"}},
    ))
    assert [e.item_kind for e in embeds] == [None]
