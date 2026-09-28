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


async def answer(conn: Any, workspace_id: UUID, request: dict[str, Any]) -> Any:
    """One aggregation over one set, read the way `/object-sets/aggregate`
    reads it - through `object_set_eval.aggregate`, so the two cannot differ.

    A refusal - a property the type does not declare, or cannot aggregate -
    is a `VariableError`, because what reaches a viewer is the variable's
    problem rather than a request's."""
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
        if v.derivation is not None and v.derivation.transform == "object_set_aggregation"
    )
    for _ in range(passes):
        wanted: dict[str, dict[str, Any]] = {}
        resolved = wv.evaluate(variables, values, aggregates=aggregates, wanted=wanted,
                               **options)
        if not wanted:
            return resolved
        for key, request in wanted.items():
            aggregates[key] = await answer(conn, workspace_id, request)
    # Only reachable if every pass found something new, which the bound above
    # says cannot happen; answered with what is known rather than looping on.
    return wv.evaluate(variables, values, aggregates=aggregates, **options)
