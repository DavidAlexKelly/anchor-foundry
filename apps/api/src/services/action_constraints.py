"""What values a parameter accepts (§584; db 0119; `action-types` p.8, p.45,
p.71).

    "Select the Priority parameter to limit the values it can take on. Change
     the constraints from User input to Multiple choice. This will allow you to
     pick what values can be chosen for this parameter. Add P0, P1 and P2 as
     options." (p.8)

    "Constraints can be configured individually for struct parameter fields,
     **as with regular parameters**. For example, a string length constraint
     can be defined… to only allow string value that are between 10 and 500
     characters long." (p.71)

    "An override can change the configuration of the parameter's
     **constraints**, visibility, requiredness, and default values." (p.45)

**A parameter's constraint is a value type's constraint** (p.233), parsed and
applied by `value_constraints`. p.8's multiple choice is the `enum`, p.71's
string length is the `range` on a string, and the pattern and UUID checks come
with them. One module deciding what "between 10 and 500" means is the point:
a value type on the property and a constraint on the parameter that writes it
cannot then disagree about the same value.

**Checked where the submission is bound**, inside `bind_parameters`, after
p.45's overrides are resolved — so an override's constraint is the one that
applies, and every path that executes or checks an action asks the same
question. The form draws p.8's multiple choice as a dropdown, but that is a
convenience over this rule rather than the rule.

**An array parameter's constraint is its elements'** (db 0118). p.71's own
reading of a struct is "only valid if all fields meet the defined constraint",
and an array is the same sentence about its items: a list of priorities is
valid when each one is P0, P1 or P2.
"""
from __future__ import annotations

from typing import Any

from . import value_constraints
from .property_values import PropertyValueError, coerce_property_value

#: The parameter types a constraint can be put on: the ones p.233 constrains.
CONSTRAINABLE = ("string", "integer", "float", "boolean", "date", "timestamp")


def base_type_of(parameter: dict[str, Any]) -> str | None:
    """The type a parameter's constraint is read against, or None when it
    cannot carry one: its own type, or an array's element type."""
    data_type = str(parameter.get("data_type") or "")
    if data_type == "array":
        data_type = str(parameter.get("array_of") or "")
    return data_type if data_type in CONSTRAINABLE else None


def parse(raw: Any, parameter: dict[str, Any], *, where: str = "") -> dict[str, Any] | None:
    """One constraint, normalised against the parameter it guards, or a
    refusal naming the parameter."""
    if raw is None:
        return None
    name = str(parameter.get("api_name", ""))
    base_type = base_type_of(parameter)
    if base_type is None:
        raise ValueError(
            f"{name!r}{where} is a {parameter.get('data_type')}, which takes no "
            f"constraint; constraints are for {', '.join(CONSTRAINABLE)} "
            "parameters and arrays of them"
        )
    try:
        return value_constraints.parse(raw, base_type=base_type)
    except value_constraints.ConstraintError as why:
        raise ValueError(f"{name!r}{where}: {why}") from why


def _items(parameter: dict[str, Any], value: Any) -> list[Any]:
    if str(parameter.get("data_type")) == "array" and isinstance(value, list):
        return value
    return [value]


def violation(parameter: dict[str, Any], value: Any) -> str | None:
    """Why `value` fails the parameter's constraint, or None."""
    constraint = parameter.get("value_constraint")
    base_type = base_type_of(parameter)
    if not constraint or base_type is None:
        return None
    for item in _items(parameter, value):
        # **Read as its type first**, so "5" typed for an integer is the 5 the
        # rule will write, not a string that is "not a number" here and a
        # number one step later. A value its type refuses is refused by name.
        try:
            item = coerce_property_value(base_type, item)
        except PropertyValueError as why:
            return str(why)
        why = value_constraints.violation(constraint, base_type, item)
        if why:
            return why
    return None


def check_parameters(parameters: list[dict[str, Any]]) -> None:
    """Refuse a constraint that could not hold, and normalise the rest in
    place — the parameter's own and each override block's (p.45).

    Refused at save rather than found at submit, because a constraint nothing
    can satisfy and a default the constraint refuses look, once the form is
    open, like an action that refuses everybody for no reason.
    """
    from .action_options import options_of

    for parameter in parameters:
        name = str(parameter.get("api_name", ""))
        constraint = parse(parameter.get("value_constraint"), parameter)
        parameter["value_constraint"] = constraint
        if constraint and constraint["kind"] == "enum" and options_of(parameter) is not None:
            # p.8's options and p.33's options from an object set are both
            # "the values it may take", and a parameter carrying both would
            # have two answers with nothing to say which wins.
            raise ValueError(
                f"{name!r} has both a list of options and options from an object "
                "set: two answers to which values it may take"
            )
        default = parameter.get("default_value")
        if constraint and default is not None:
            why = violation(parameter, default)
            if why:
                raise ValueError(f"{name!r}: its default {why}")
        for index, block in enumerate(parameter.get("overrides") or [], start=1):
            block["set_constraint"] = parse(
                block.get("set_constraint"), parameter, where=f" (override {index})"
            )
