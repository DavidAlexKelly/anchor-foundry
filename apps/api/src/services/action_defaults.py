"""A parameter's default taken from an object (§588; db 0122; `action-types`
p.27, p.29, p.69-70).

    "Parameters can be set to default values to display either a fixed value
     or a property of the selected object." (p.27)

    "...configuring the value of each parameter to be prefilled from the
     currently selected object... Only object reference parameters that are
     placed above the parameter in the input list are available to be used as
     a default value." (p.29)

    "Default values are defined individually for struct parameter fields. Each
     struct parameter field is mapped to fields of a specified object type's
     struct property. A default value must be defined for all fields in the
     struct parameter and must be mapped to fields of the same object type
     struct property... The object type whose struct property fields will act
     as default values is specified in the ObjectReference parameter."
     (p.69-70)

**One document for both**: `{parameter, property}` names an object reference
parameter above this one and a property of the object it holds; for a struct
parameter, `fields` maps each of its fields to a field of that (struct)
property, by name where it is not given. p.70's "must be mapped to fields of
the same object type struct property" is then true by construction, since
there is one property to map from.

**Resolved into `default_value`**, where p.27's fixed default already lives,
so everything that reads a default - `bind_parameters`, p.45's overrides, the
form's prefill - reads this one too without learning a second kind. It is
resolved from the object as it is when the form asks or the action is
submitted; a default is a starting value, so an object that changed since
simply starts the form somewhere else.
"""
from __future__ import annotations

from typing import Any


def source_of(parameter: dict[str, Any]) -> dict[str, Any] | None:
    raw = parameter.get("default_from")
    return raw if isinstance(raw, dict) and raw else None


def check(
    parameters: list[dict[str, Any]],
    *,
    order: list[str],
    object_types: dict[str, str],
    properties_by_type: dict[str, dict[str, str]],
    struct_fields_by_type: dict[str, dict[str, Any]],
    parameter_fields: dict[str, list[dict[str, Any]]],
    element_types: dict[str, dict[str, str | None]] | None = None,
) -> None:
    """Refuse a default that could not be read, by name, and normalise the
    rest in place.

    `object_types` is `{object parameter: its type}`; `properties_by_type`
    each type's properties and their types; `struct_fields_by_type` each
    type's struct properties' fields; `parameter_fields` each struct
    parameter's own fields (§450's derivation); `element_types` each type's
    array properties' element types.
    """
    from .action_overrides import readable_before

    kinds = {str(p["api_name"]): str(p.get("data_type")) for p in parameters}
    for parameter in parameters:
        source = source_of(parameter)
        name = str(parameter.get("api_name", ""))
        if source is None:
            parameter["default_from"] = None
            continue
        if parameter.get("default_value") is not None:
            raise ValueError(
                f"{name!r} has a fixed default and one from an object; p.27 offers "
                "one or the other"
            )
        unknown = sorted(k for k in source if k not in ("parameter", "property", "fields"))
        if unknown:
            raise ValueError(f"{name!r}: unknown default option {', '.join(unknown)}")
        read = str(source.get("parameter") or "")
        if read not in kinds:
            raise ValueError(f"{name!r} takes its default from {read!r}, which is not a parameter")
        if kinds[read] != "object":
            raise ValueError(
                f"{name!r} takes its default from {read!r}, which is not a single object "
                "reference"
            )
        if read not in readable_before(order, name):
            raise ValueError(
                f"{name!r} takes its default from {read!r}, which is not above it in the "
                "form; p.29 offers only object references placed above"
            )
        type_id = str(object_types.get(read) or "")
        declared = properties_by_type.get(type_id)
        if declared is None:
            raise ValueError(f"{read!r} does not say which object type it holds")
        prop = str(source.get("property") or "")
        if prop not in declared:
            raise ValueError(f"the object in {read!r} has no {prop!r} property")
        wanted = kinds[name]
        if wanted != declared[prop]:
            raise ValueError(
                f"{name!r} is a {wanted} and {prop!r} on the object in {read!r} is a "
                f"{declared[prop]}, so it cannot be its default"
            )
        if wanted == "array":
            held = (element_types or {}).get(type_id, {}).get(prop)
            if held != parameter.get("array_of"):
                raise ValueError(
                    f"{name!r} holds {parameter.get('array_of')} and {prop!r} on the "
                    f"object in {read!r} holds {held}, so it cannot be its default"
                )
        out: dict[str, Any] = {"parameter": read, "property": prop}
        if wanted == "struct":
            out["fields"] = _check_fields(
                name, source.get("fields"),
                own=parameter_fields.get(name) or [],
                theirs=(struct_fields_by_type.get(type_id) or {}).get(prop) or [],
            )
        elif source.get("fields"):
            raise ValueError(f"{name!r} is not a struct, so it has no fields to map")
        parameter["default_from"] = out


def _check_fields(
    name: str, raw: Any, *, own: list[dict[str, Any]], theirs: list[dict[str, Any]],
) -> dict[str, str]:
    """p.70: "A default value must be defined for all fields in the struct
    parameter" - each of this parameter's fields mapped to a field of the
    source property of the same type, by name unless `raw` says otherwise."""
    if not own:
        raise ValueError(
            f"{name!r} has no fields yet: a struct parameter's fields are the struct "
            "property its rule writes (p.73)"
        )
    if raw is not None and not isinstance(raw, dict):
        raise ValueError(f"{name!r}: fields map each field to a field of the property")
    given = raw or {}
    types = {str(f["api_name"]): str(f["data_type"]) for f in theirs}
    out: dict[str, str] = {}
    for field in own:
        mine = str(field["api_name"])
        from_field = str(given.get(mine) or mine)
        if from_field not in types:
            raise ValueError(
                f"{name!r} field {mine!r} has no field to take its default from; p.70: "
                "a default must be defined for all fields"
            )
        if types[from_field] != str(field["data_type"]):
            raise ValueError(
                f"{name!r} field {mine!r} is a {field['data_type']} and "
                f"{from_field!r} is a {types[from_field]}"
            )
        out[mine] = from_field
    unknown = sorted(set(given) - {str(f["api_name"]) for f in own})
    if unknown:
        raise ValueError(f"{name!r} has no field {unknown[0]!r}")
    return out


def resolve(
    parameters: list[dict[str, Any]], objects: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """The parameters with each object default read into `default_value`
    from `objects` (`{object parameter: its properties}`). A default whose
    object is not chosen, or that holds nothing, stays unset: there is no
    starting value to show."""
    out: list[dict[str, Any]] = []
    for parameter in parameters:
        source = source_of(parameter)
        if source is None or str(source.get("parameter")) not in objects:
            out.append(parameter)
            continue
        value = objects[str(source["parameter"])].get(str(source.get("property")))
        fields = source.get("fields")
        if fields and isinstance(value, dict):
            value = {mine: value.get(theirs) for mine, theirs in fields.items()}
        out.append({**parameter, "default_value": value} if value is not None else parameter)
    return out
