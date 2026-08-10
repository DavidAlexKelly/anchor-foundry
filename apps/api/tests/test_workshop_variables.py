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
