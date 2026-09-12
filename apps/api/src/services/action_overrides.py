"""Changing a parameter under specific circumstances (§329; db 0082;
`action-types` p.43-46).

    "Overrides are used to change a parameter's behavior and configuration
     under specific circumstances… removing the need to configure separate
     action types with only minor variations." (p.43)

    "While assignees can change the status, managers will have to provide a
     justification. Using overrides, the Justification reason parameter can be
     made **required and visible for managers, while it is hidden and optional
     for the assignee**." (p.43)

    "Every parameter can contain multiple override blocks, however, **if more
     than one is true, only the first one will be executed**." (p.45)

    "The only difference between override conditions and submission criteria
     conditions is that **only parameters which appear above the current
     parameter in the form hierarchy** can be referenced in override
     conditions." (p.45)

**An override changes what the action asks for, not how the form looks.** That
is the whole difference from §328's sections, which say the opposite in the
same words: p.43's justification is *required* for a manager and optional for
an assignee, so a submission with no justification is refused for one person
and accepted for another. `resolve` therefore runs inside `bind_parameters`,
before anything decides whether a submission is complete — a form that applied
these for drawing only would let the manager submit without the thing p.43 says
they owe, and the screen would be the only place the rule existed.

**p.45's one difference is what makes a single pass possible.** Conditions may
only read parameters above this one, so resolving the form in order gives every
block exactly the values it is allowed to see, and no block can depend on a
parameter whose own resolution depends on it. That is not a convenience: the
alternative is a fixed point, and a form whose parameters are required in a
cycle has no answer at all. The refusal lives in `check_references`, at save
time, where somebody can still do something about it.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from .actions import _passes  # the condition grammar decision 0007 already has

#: p.45's "then": what a block may change. Constraints are p.45's fourth and
#: are absent here because the thing they would override is — an
#: `action_parameters` row has a type, a default, a `required` and a `hidden`,
#: and no value constraints for a block to narrow. Named rather than silently
#: missing: see the roadmap row's ○.
SETTABLE = ("hidden", "required", "default")


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def form_order(
    parameters: list[dict[str, Any]], sections: list[dict[str, Any]]
) -> list[str]:
    """p.45's "form hierarchy", flattened to the order somebody reads.

    The same arrangement §328's form draws: the parameters no section claimed,
    then each section's in turn. **A parameter inside a hidden section still
    has a position** — p.45's rule is about what a condition may *read*, and a
    hidden section's parameters are still bound and still submitted (db 0081),
    so leaving them out would make a legal reference unsayable.

    Sections that name a parameter the action does not declare are ignored
    rather than refused: `replace_sections` cannot create one, but an ontology
    import (§326) or a hand-edited row can, and a save that failed here would
    be refusing the wrong document.
    """
    declared = [str(p["api_name"]) for p in parameters]
    known = set(declared)
    claimed: dict[str, list[str]] = {}
    for section in sections:
        inside = [str(n) for n in (section.get("parameters") or []) if str(n) in known]
        claimed[str(section.get("id"))] = inside
    taken = {name for names in claimed.values() for name in names}
    order = [name for name in declared if name not in taken]
    for section in sections:
        order.extend(claimed.get(str(section.get("id")), []))
    return order


def readable_before(order: list[str], api_name: str) -> set[str]:
    """The parameters p.45 lets this one's conditions reference.

    Strictly above: a block on `justification` may read `status`, and a block
    on `status` may not read `justification`. **Nor may it read itself** — a
    condition on the parameter whose default it sets is the fixed point the
    module docstring refuses, and it reads as sensible right up until somebody
    writes one.

    A parameter no section and no declaration mentions has nothing above it,
    which is the right answer for a reference to a parameter that is gone.
    """
    if api_name not in order:
        return set()
    return set(order[: order.index(api_name)])


def check_references(
    parameters: list[dict[str, Any]], sections: list[dict[str, Any]]
) -> None:
    """p.45's one difference from a submission criterion, refused by name.

    Raised at save time rather than resolved at submit time, because the two
    ways of being wrong look identical once the form is open: a condition that
    reads a parameter below it is unevaluable, an unevaluable condition does
    not hold, and a block that never holds is indistinguishable from one
    nobody meant to write. p.43's whole premise is a builder arranging a form,
    so the message names the parameter, the block and the reference.
    """
    order = form_order(parameters, sections)
    for parameter in parameters:
        name = str(parameter["api_name"])
        above = readable_before(order, name)
        for index, block in enumerate(parameter.get("overrides") or [], start=1):
            for condition in _json(block.get("conditions")) or []:
                for side in ("left", "right"):
                    spec = _json((_json(condition) or {}).get(side)) or {}
                    if str(spec.get("kind", "")) != "parameter":
                        continue
                    read = str(spec.get("parameter", ""))
                    if read in above:
                        continue
                    if read == name:
                        raise ValueError(
                            f"override {index} on {name!r} reads {name!r} itself; "
                            "a block can only read parameters above it (p.45)"
                        )
                    where = (
                        "is below it in the form"
                        if read in order
                        else "is not a parameter of this action"
                    )
                    raise ValueError(
                        f"override {index} on {name!r} reads {read!r}, which "
                        f"{where}; p.45 allows only parameters above it"
                    )


def applies(block: dict[str, Any], *, bound: dict[str, Any], user: dict[str, Any]) -> bool:
    """Whether every condition in one block holds.

    **All of them, and an empty block holds.** p.45 says "Each block can
    contain one or multiple conditions" and nothing about combining them any
    other way, which is how `check_criteria` reads its list too — one grammar,
    one reading. `write_overrides` refuses a block with no conditions, so the
    vacuous case cannot be stored; it is `True` here because that is what "all
    of none" means and inventing a different answer for an input that cannot
    arrive would be a branch nothing can reach.

    A condition that cannot be decided does not hold. Unlike §328's sections,
    where failing closed hides a box, failing closed here leaves the parameter
    exactly as its own configuration says — the action behaves as though nobody
    had written the override, which is the only safe reading of a rule the
    server cannot evaluate.
    """
    for condition in _json(block.get("conditions")) or []:
        try:
            if not _passes(_json(condition) or {}, bound=bound, user=user):
                return False
        except Exception:  # noqa: BLE001 - `_Unevaluable` and anything a bad
            # document can throw. An override is resolved on the submit path,
            # so a 500 here would take the action down for a rule that is only
            # meant to adjust one field.
            return False
    return True


def effective(
    parameter: dict[str, Any], *, bound: dict[str, Any], user: dict[str, Any]
) -> dict[str, Any]:
    """The parameter as it stands for this submission.

    p.45-46, said twice: "if more than one is true, only the first one will be
    executed". Not a merge of every block that holds — the first one wins
    outright, and the rest are not consulted.

    Returns a parameter row, so every caller that already knows how to read one
    (`bind_parameters`, the form, the import) keeps working against the
    resolved thing without learning what an override is.
    """
    for block in parameter.get("overrides") or []:
        if not applies(block, bound=bound, user=user):
            continue
        resolved = dict(parameter)
        # **NULL means "leave alone", not False.** p.43's example makes one
        # parameter *required and visible* in a single block; a block that only
        # set `hidden` would otherwise un-require it as a side effect.
        if block.get("set_hidden") is not None:
            resolved["hidden"] = bool(block["set_hidden"])
        if block.get("set_required") is not None:
            resolved["required"] = bool(block["set_required"])
        if block.get("set_default") is not None:
            # **Used as it comes, not re-parsed**, which is the trap
            # `bind_parameters` documents one file over: the repo's defensive
            # `json.loads(x) if isinstance(x, str)` is a no-op for a jsonb
            # object and *wrong* for a jsonb scalar, because the driver already
            # decoded `"see the ticket"` to a Python string and parsing that
            # again fails at column 1. A default is the only jsonb here that is
            # routinely a scalar — and an override's default is a second one.
            resolved["default_value"] = block["set_default"]
        resolved["overridden_by"] = str(block.get("id") or "")
        return resolved
    return dict(parameter)


def resolve(
    parameters: list[dict[str, Any]],
    *,
    values: dict[str, Any],
    user: dict[str, Any],
    order: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Every parameter as it stands, resolved in p.45's order.

    **One pass, and p.45 is why one pass is enough.** A block may only read
    parameters above this one, so by the time a parameter is resolved every
    value its conditions are allowed to see is already known — either supplied
    by the caller or taken from a default that was itself resolved a moment
    earlier.

    The values it resolves against are the *submitted* ones plus the defaults
    settled so far, which is what p.43's example needs: the justification's
    block asks who is submitting, and a block further down may ask about a
    status the caller never typed because a default filled it in.

    Returned in the order it was given, not in form order — a caller reading
    this list is reading an action's parameters, and quietly reordering them
    would change what `bind_parameters` reports first and what the definition
    endpoint returns.
    """
    by_name = {str(p["api_name"]): p for p in parameters}
    sequence = [n for n in (order or []) if n in by_name]
    sequence += [str(p["api_name"]) for p in parameters if str(p["api_name"]) not in sequence]

    bound = dict(values)
    resolved: dict[str, dict[str, Any]] = {}
    for name in sequence:
        parameter = effective(by_name[name], bound=bound, user=user)
        resolved[name] = parameter
        if name in bound:
            continue
        default = parameter.get("default_value")
        if default is not None:
            # Seeded here so a later block can read it, and *only* here —
            # `bind_parameters` applies the same default a moment later from
            # the resolved row, so this is not a second place that decides what
            # a submission contains.
            bound[name] = default
    return [resolved[str(p["api_name"])] for p in parameters]


# ---- storage ------------------------------------------------------------------
async def overrides_for(
    conn: AsyncConnection, parameter_ids: list[str]
) -> dict[str, list[dict[str, Any]]]:
    """Every parameter's blocks in one query, for the reason `_parameters_for`
    gives: the list endpoint returns a workspace's actions, and a fetch per
    parameter would make it N+1 twice over."""
    if not parameter_ids:
        return {}
    rows = await fetch_all(
        conn,
        """
        SELECT id, parameter_id, sort_order, conditions,
               set_hidden, set_required, set_default
          FROM action_parameter_overrides
         WHERE parameter_id = ANY(CAST(:ids AS uuid[]))
         ORDER BY sort_order, id
        """,
        {"ids": parameter_ids},
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        block = dict(row)
        block["conditions"] = _json(block["conditions"]) or []
        # `set_default` is deliberately not passed through `_json`: see
        # `effective`. It arrives decoded and a scalar would not survive a
        # second parse.
        grouped.setdefault(str(row["parameter_id"]), []).append(block)
    return grouped


async def write_overrides(
    conn: AsyncConnection, parameter_id: UUID, blocks: list[dict[str, Any]]
) -> None:
    """Write one parameter's blocks, in p.45's order.

    **Called only as part of `set_definition`, and named for what it does.**
    The first draft was `replace_overrides` and began by deleting this
    parameter's blocks — a statement that can never find a row, because
    `set_definition` has already deleted every `action_parameters` row for the
    action and `ON DELETE CASCADE` took the blocks with them. A sweep removed
    the delete and nothing changed, which is §213's rule arriving from the
    database rather than from another layer of Python.

    The order is the rule, not a presentation detail (p.45-46: "only the first
    one will be executed"), which is why `sort_order` is the position in the
    list rather than anything the caller has to keep consistent.

    A refused write leaves the old blocks alone because `user_connection` is one
    transaction per request — not because the checks come first. The checks
    come first because that is how the function reads.
    """
    for index, block in enumerate(blocks, start=1):
        conditions = block.get("conditions") or []
        if not conditions:
            # p.45 offers a block as an "if"/"then" pair. A block with no "if"
            # is not an override, it is the parameter's own configuration
            # written twice — and it would silently win over every block below
            # it, because the first one that holds is the only one applied.
            raise ValueError(f"override {index} has no conditions")
        if all(block.get(f"set_{name}") is None for name in SETTABLE):
            raise ValueError(f"override {index} changes nothing")

    for index, block in enumerate(blocks):
        await fetch_one(
            conn,
            """
            INSERT INTO action_parameter_overrides
                   (parameter_id, sort_order, conditions,
                    set_hidden, set_required, set_default)
            VALUES (:pid, :ord, CAST(:conditions AS jsonb),
                    :hidden, :required, CAST(:default AS jsonb))
            RETURNING id
            """,
            {
                "pid": str(parameter_id),
                "ord": index,
                "conditions": json.dumps(block.get("conditions") or []),
                "hidden": block.get("set_hidden"),
                "required": block.get("set_required"),
                "default": json.dumps(block["set_default"])
                if block.get("set_default") is not None else None,
            },
        )
