"""p.73's Object set aggregation, answered from the store (§617).

> "Object set aggregation: For variables derived from an aggregation of an
> object set" (`workshop` p.73) - and p.75's Numeric variable, "Initialized
> from either a static value or the output of a function, aggregation, or
> object property."

`workshop_variables.evaluate` is a pure function and keeps no connection, so
it cannot read the store. It does not pretend to either: an aggregation it has
no answer for resolves to `None` and is written into `wanted`. This module is
the other half. It reads each wanted aggregation through `object_set_eval.aggregate`,
which `/object-sets/aggregate` reads through too (the same checks and the
same store call, so a variable and a Metric Card over one set cannot
disagree), then evaluates again with the
answers.

**Again, and possibly again.** An aggregation's set can itself depend on an
aggregation - a set narrowed to the sites at the largest capacity - so one
pass may reveal a question the last one could not ask. Each pass answers at
least one new question or ends, so the passes are bounded by the number of
aggregation variables plus the one that finds nothing new.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from . import object_set_eval
from . import workshop_variables as wv


#: The objects a set variable may hand a function's `object_set` parameter
#: (§772). Read a page at a time, so this is a viewer's wait, not a build's.
MAX_SET_INPUT = 1_000

#: What each output becomes, for each kind of variable (§772; `functions`
#: p.80's "Below is the mapping between Workshop variable types").
_OUTPUT_FOR = {"object_set": "object_set", "array": "array"}


async def call_function(conn: Any, workspace_id: UUID, request: dict[str, Any]) -> Any:
    """p.73's function-backed variable (§772; decision 0018): the function
    called as the viewer, with its inputs as the module holds them.

    A picked object is passed by its id; a set variable by the keys it holds,
    for an `object_set` parameter. The answer is the variable's kind: a value,
    a list, or an object set of the output's type narrowed to the keys the
    function gave. Every refusal is the variable's (`VariableError`)."""
    from uuid import UUID as _UUID

    from . import functions as functions_service

    try:
        current = await functions_service.get_function(
            conn, workspace_id, _UUID(str(request["function"])))
    except Exception as exc:  # NotFoundError, a malformed id
        raise wv.VariableError(f"the function this variable calls is not here: {exc}") from None
    version = request.get("version")
    chosen = next((v for v in current["versions"] if v["version"] == version), None) \
        if version else max(current["versions"],
                            key=lambda v: functions_service.version_key(v["version"]))
    if chosen is None:
        raise wv.VariableError(f"{current['api_name']} has no version {version}")
    kinds = {p["api_name"]: p["data_type"] for p in chosen["parameters"]}
    values: dict[str, Any] = {}
    for name, value in (request.get("values") or {}).items():
        # An empty one goes on as it is: `execute` refuses a required
        # parameter with nothing in it by name, and leaves an optional unset.
        if kinds.get(name) == "object" and isinstance(value, dict):
            value = value.get("id")
        elif kinds.get(name) == "object_set" and isinstance(value, dict):
            try:
                value = await object_set_eval.keys_of(conn, workspace_id, value,
                                                      limit=MAX_SET_INPUT)
            except ValueError as exc:
                raise wv.VariableError(f"{current['api_name']}'s {name}: {exc}") from None
        values[name] = value
    expected = _OUTPUT_FOR.get(str(request.get("kind")), "value")
    if chosen["output"]["kind"] != expected:
        raise wv.VariableError(
            f"{current['api_name']} returns {chosen['output']['kind'].replace('_', ' ')}, "
            f"and a {request.get('kind')} variable takes {expected.replace('_', ' ')}")
    try:
        result = await functions_service.execute(
            conn, workspace_id=workspace_id, function_id=_UUID(str(current["id"])),
            version=chosen["version"], values=values)
    except ValueError as exc:
        raise wv.VariableError(f"{current['api_name']}: {exc}") from None
    if expected == "value":
        return result["value"]
    if expected == "array":
        return result["values"]
    return {"object_type_id": chosen["output"]["object_type_id"],
            "filters": [{"property": "$primary_key", "op": "in", "value": result["values"]}]}


async def answer(conn: Any, workspace_id: UUID, request: dict[str, Any]) -> Any:
    """One aggregation over one set, read the way `/object-sets/aggregate`
    reads it - through `object_set_eval.aggregate`, so the two cannot differ.
    A function variable's question (§772) is `call_function`'s.

    A refusal - a property the type does not declare, or cannot aggregate -
    is a `VariableError`, because what reaches a viewer is the variable's
    problem rather than a request's."""
    if "function" in request:
        return await call_function(conn, workspace_id, request)
    try:
        value, _ = await object_set_eval.aggregate(
            conn, workspace_id, request["definition"], str(request["aggregation"]),
            request.get("property"),
        )
    except ValueError as exc:
        raise wv.VariableError(f"an object set aggregation cannot be answered: {exc}") from None
    return value


async def evaluate(
    conn: Any, workspace_id: UUID, variables: dict[str, wv.Variable],
    values: dict[str, Any], **options: Any,
) -> dict[str, Any]:
    """`workshop_variables.evaluate`, with its aggregations read from the store."""
    aggregates: dict[str, Any] = {}
    passes = 1 + sum(
        1 for v in variables.values()
        if v.derivation is not None
        and v.derivation.transform in ("object_set_aggregation", "function")
    )
    for _ in range(passes):
        wanted: dict[str, dict[str, Any]] = {}
        resolved = wv.evaluate(variables, values, aggregates=aggregates, wanted=wanted,
                               **options)
        if not wanted:
            return resolved
        refused: wv.VariableError | None = None
        answered = False
        for key, request in wanted.items():
            try:
                aggregates[key] = await answer(conn, workspace_id, request)
                answered = True
            except wv.VariableError as exc:
                # **Deferred while another question is answered** (§772): a
                # call may read a variable another call in this pass answers,
                # and is asked again with it. A pass that answers nothing says
                # the refusal.
                refused = exc
        if refused is not None and not answered:
            raise refused
    # Only reachable if every pass found something new, which the bound above
    # says cannot happen; answered with what is known rather than looping on.
    return wv.evaluate(variables, values, aggregates=aggregates, **options)
