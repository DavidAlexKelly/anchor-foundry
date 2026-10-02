"""Which actions `workshop` p.511's Action table can draw (§702).

> "There may be some Actions that are not yet usable in the Table because some
> feature of the Action is only supported in the Form layout." (p.511)

Decided without a database, like `test_action_overrides.py`: the rule is a
function of the action type's definition and nothing else.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.actions import TABLE_ROW_LIMIT, table_refusals  # noqa: E402


def parameter(name: str, data_type: str = "string", **over) -> dict:
    return {"api_name": name, "data_type": data_type, "hidden": False, **over}


def action(*parameters: dict, **over) -> dict:
    return {"object_type_id": "t", "interface_id": None,
            "parameters": list(parameters), "rules": [], **over}


def test_an_action_of_single_values_is_a_table() -> None:
    assert table_refusals(action(parameter("status"), parameter("count", "integer"),
                                 parameter("due", "date"))) == []


def test_creating_is_not_a_reason(  # unlike an inline edit
) -> None:
    """Each row is its own submission of the whole action, so a create, a delete
    or a link is as drawable as an edit."""
    made = action(parameter("key"), rules=[{"kind": "create_object", "config": {}}])
    assert table_refusals(made) == []


def test_a_value_no_cell_can_hold_is_refused_by_name() -> None:
    reasons = table_refusals(action(parameter("status"), parameter("site", "geopoint")))
    assert len(reasons) == 1, reasons
    assert "'site'" in reasons[0] and "geopoint" in reasons[0]


def test_a_hidden_parameter_is_never_drawn_so_never_refused() -> None:
    """Seeded from the row's object and sent as it is (p.25)."""
    assert table_refusals(action(parameter("site", "geopoint", hidden=True))) == []


def test_a_parameter_that_changes_with_others_is_form_only() -> None:
    reasons = table_refusals(action(parameter("status", overrides=[{"id": "b"}])))
    assert len(reasons) == 1 and "'status'" in reasons[0] and "p.45" in reasons[0]


def test_choices_narrowed_by_other_values_are_form_only() -> None:
    for key in ("dropdown_filters", "options_from", "dropdown_search_around"):
        reasons = table_refusals(action(parameter("team", **{key: [{"x": 1}]})))
        assert len(reasons) == 1 and "p.33" in reasons[0], (key, reasons)


def test_an_interface_action_is_form_only() -> None:
    reasons = table_refusals(action(object_type_id=None, interface_id="i"))
    assert len(reasons) == 1 and "interface" in reasons[0]


def test_a_table_holds_as_many_rows_as_a_batch_has_calls() -> None:
    """`action-types` p.131: "An action can be called a maximum of 10,000 times
    in a batch"."""
    assert TABLE_ROW_LIMIT == 10_000
