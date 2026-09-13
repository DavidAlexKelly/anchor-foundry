"""What an object parameter offers, and what it accepts (§330; db 0083;
`action-types` p.25, p.33-37).

    "Within the parameter configuration view, action editors can specify
     filters and Search Arounds to limit the objects that show up in the
     dropdown across all action interfaces. After configuring the filters, the
     action form will render a dropdown with only objects that match the
     filter. **The value selected is also validated before the action is
     executed.**" (p.34)

    "The resulting multiple choice options will be derived from the set of
     objects that the user has permission to view. In other words, when
     deriving multiple choice options from an object set, **users will not see
     properties of objects to which they do not have access**." (p.33)

**p.33-37 narrows a dropdown this platform did not draw.** An `object`
parameter has been a text box since db 0044 — the person submitting is expected
to know a uuid and type it in — so the list comes first and the filters (p.36)
come next. A filter over a list nobody can see is a setting with no observable
effect, which is the shape §214 refuses.

**The two halves of p.34 are one function apart on purpose.** `choices` says
what the form may offer; `check_object_values` says what a submission may
contain, and it runs on the submit path whether or not anybody drew a form.
They read the same rows through the same connection, so "only objects that
match" and "validated before the action is executed" cannot come apart — and
p.33's permission sentence is free, because RLS is what answers both.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all
from . import action_filters
from . import action_search_arounds as search_arounds
from . import instance_store
from . import object_set_eval
from . import object_sets
from . import instances as instances_service

#: How many objects a dropdown offers. p.33-37 says nothing about a limit, and
#: a dropdown is not a listing (§256): a control somebody scrolls is a control
#: over the rows it happened to receive, so this is a cap on the *control*
#: rather than a page of a result set. Past it the form says so rather than
#: silently offering a slice — see the `truncated` half of `choices`.
#:
#: **The store's own page size, not a number chosen here.** `list_for_type`
#: clamps to `INSTANCE_PAGE_SIZE`, so a larger value would be a constant that
#: reads like a promise and is quietly overruled one call down — and the
#: truncation notice would then be right for a reason this file did not know.
MAX_CHOICES = instance_store.INSTANCE_PAGE_SIZE


def object_parameters(parameters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The parameters whose value is an object, in declaration order."""
    return [p for p in parameters or [] if str(p.get("data_type")) == "object"]


def type_of(parameter: dict[str, Any]) -> str | None:
    """Which object type this parameter holds — **only when somebody said so.**

    db 0083's column, and nothing else. `actions.object_parameter_types` can
    also produce an answer by reading the action's rules, and the first draft of
    this module used it as a fallback so that parameters written before §330
    would get a dropdown too. That was wrong, and the existing tests said so
    within a minute: the inference is a *guess*, documented as one, and it is
    plainly wrong for a link rule — which names the far object through the link
    type rather than through `config.object_type`, so the guess falls back to
    the action's own subject type and is simply a different type.

    A wrong guess is survivable where it was born. `object_parameter_types`
    exists so a notification template can be checked against *some* property
    list (§257), and there a bad guess renders a gap. Refusing a submission on
    one, or offering somebody a dropdown of the wrong objects, is not
    survivable — so this asks only the column, and a parameter nobody has typed
    keeps exactly the behaviour it had before this unit: a text box, and no
    p.34 validation to be wrong about.

    That is also the argument for the column existing at all. Declaring the type
    is what turns the box into a list *and* turns on p.34's check, and the two
    arrive together because they are the same claim read twice.
    """
    declared = parameter.get("object_type_id")
    return str(declared) if declared else None


async def choices(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    object_type_id: UUID,
    filters: tuple[Any, ...] = (),
    definition: Any = None,
    limit: int = MAX_CHOICES,
) -> tuple[list[dict[str, Any]], bool]:
    """The objects this parameter may be set to, and whether there were more.

    **Read through the caller's own connection**, which is the whole of p.33's
    permission rule: "users will not see properties of objects to which they do
    not have access". There is no second visibility check here because there is
    no second answer — RLS narrowed the rows before this function saw them.

    Returns `(rows, truncated)` rather than a page. p.33-37 describes a control
    somebody picks from, not a listing somebody pages through, so the honest
    report is "here is what fits, and there are more" — a dropdown that
    silently offered the first two hundred of a thousand would be the trap §256
    names, one control down.
    """
    prefix = await instances_service.workspace_search_prefix(conn, workspace_id)
    store = instance_store.store_for(conn)
    # p.36's filters, as the object set p.41 says Foundry compiles them into
    # (§331), and p.36-37's start and hops as the `via` chain that set already
    # supports (§333). Unfiltered and unwalked go through the same call rather
    # than a different one, so there is one path for "what does this parameter
    # offer" and no second place for the answer to be decided.
    if definition is not None and definition.via is not None:
        filters, empty = await object_set_eval.resolve_traversal(
            conn, store, prefix, workspace_id, definition
        )
        if empty:
            # The set below linked to nothing, so this one has no members. An
            # unfiltered read here would be the silent widening decision 0002
            # exists to remove — and it would offer every object of the type,
            # which is the opposite of what a walk narrowing to none means.
            return [], False
    rows, total = await store.evaluate_object_set(
        search_prefix=prefix, object_type_id=object_type_id,
        filters=filters, limit=limit, offset=0,
    )
    return [dict(r) for r in rows], total > len(rows)


async def start_key_of(
    conn: AsyncConnection,
    parameter: dict[str, Any],
    *,
    workspace_id: UUID,
    bound: dict[str, Any],
) -> str | None:
    """The primary key of the object p.37's walk starts from, or `None`.

    **A form holds instance ids and a set names primary keys**, and this is the
    one round trip between them. `search_arounds.build` stays pure and testable
    without a database because the lookup lives here instead.

    An id nothing resolves comes back unchanged rather than as `None`, and the
    difference matters: `None` means "nobody has chosen an employee yet", which
    the form answers with "choose that box first", while an id that names
    nothing this caller can read means the walk starts from an empty set — an
    empty dropdown, correctly. The submission is refused either way, because the
    starting parameter is itself an object parameter and `check_object_values`
    refuses an id it cannot read by its own rule, in a sentence about the box
    that actually holds the bad value.
    """
    name = search_arounds.start_parameter(parameter)
    if name is None:
        return None
    held = bound.get(name)
    if held is None or held == "":
        return None
    start = (search_arounds.source_of(parameter) or {}).get("start") or {}
    type_id = str(start.get("object_type_id") or "")
    if not type_id:
        return str(held)
    prefix = await instances_service.workspace_search_prefix(conn, workspace_id)
    row = await instance_store.store_for(conn).get_instance(
        search_prefix=prefix, object_type_id=type_id, instance_id=str(held),
    )
    return str(row["primary_key"]) if row else str(held)


async def object_values_of(
    conn: AsyncConnection,
    parameter: dict[str, Any],
    *,
    workspace_id: UUID,
    bound: dict[str, Any],
    parameters: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """`{parameter: its object's properties}` for p.36's third value kind.

    **The round trip `action_filters.resolve` deliberately does not make**
    (§334). A form holds instance ids and a filter reading "the region of the
    Office you chose" needs what is *inside* that object, so somebody has to
    read it; keeping that here is what lets the whole of p.36's compilation be
    decided without a database.

    One read per *parameter named*, not per filter: two filters reading two
    properties of the same Office are one object. A parameter whose id names
    nothing readable is simply absent from the result, which `resolve` turns
    into the same "there is nothing to match on" it gives an empty property —
    the honest answer, because RLS makes "deleted" and "not yours" the same
    state from here.
    """
    wanted = action_filters.object_parameters_read(parameter)
    if not wanted:
        return {}
    declared = {
        str(p.get("api_name")): type_of(p)
        for p in object_parameters(parameters)
    }
    prefix = await instances_service.workspace_search_prefix(conn, workspace_id)
    store = instance_store.store_for(conn)
    out: dict[str, dict[str, Any]] = {}
    for name in wanted:
        type_id = declared.get(name)
        held = bound.get(name)
        if not type_id or held is None or held == "":
            continue
        row = await store.get_instance(
            search_prefix=prefix, object_type_id=type_id, instance_id=str(held),
        )
        if row is not None:
            out[name] = _properties(row)
    return out


def _properties(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("properties")
    return json.loads(raw) if isinstance(raw, str) else (raw or {})


async def check_object_values(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    bound: dict[str, Any],
    parameters: list[dict[str, Any]],
) -> None:
    """p.34's "the value selected is also validated before the action is
    executed".

    **The half of p.34 that is not about a form.** A dropdown that offers only
    matching objects is a convenience; this is the rule. A submission naming an
    object of the wrong type, or one the submitter cannot see, is refused here —
    before the first rule runs, like every other refusal on this path.

    An object the caller cannot read is reported as not being an object of this
    type, which is the same sentence a non-existent id gets. That is not
    vagueness, it is the only honest answer: RLS makes those two states
    genuinely indistinguishable from here, and a message that told them apart
    would be telling somebody an object exists that they may not see.

    A parameter nobody has declared a type for is not checked, because there is
    nothing to check it against that is not a guess — see `type_of`.
    """
    wanted: list[tuple[str, str, dict[str, Any]]] = []
    for parameter in object_parameters(parameters):
        name = str(parameter.get("api_name", ""))
        value = bound.get(name)
        if value is None or value == "":
            continue
        type_id = type_of(parameter)
        if type_id is None:
            continue
        wanted.append((name, type_id, parameter))

    if not wanted:
        return

    prefix = await instances_service.workspace_search_prefix(conn, workspace_id)
    store = instance_store.store_for(conn)
    for name, type_id, parameter in wanted:
        value = str(bound[name])
        row = await store.get_instance(
            search_prefix=prefix, object_type_id=type_id, instance_id=value,
        )
        if row is None:
            raise ValueError(
                f"{value!r} is not an object of the type {name!r} asks for"
            )
        # p.34's second sentence, with p.36's filters in it (§331) and p.37's
        # walk (§333). The type is not the whole of "the value selected is also
        # validated": a dropdown narrowed to three objects and a check that
        # accepts any object of the type is a control that looks like it works.
        declared = action_filters.filters_of(parameter)
        walked = search_arounds.source_of(parameter)
        if not declared and walked is None:
            continue
        types = await property_types_of(conn, type_id)
        try:
            narrowing = action_filters.resolve(
                parameter, bound=bound, property_types=types,
                objects=await object_values_of(
                    conn, parameter, workspace_id=workspace_id,
                    bound=bound, parameters=parameters,
                ),
            )
            # **Asking about this one object rather than reading the offer and
            # looking for it.** §331 evaluated the narrowed set at
            # `MAX_CHOICES` and searched the result, so an object that matched
            # the filter but sat past the fiftieth was refused — the answer to
            # "is this value allowed" depended on how many the *control* can
            # hold, which is §256's trap arriving through the back door. A key
            # equality makes it a set of one and the page size stops mattering.
            confirming = (*narrowing, object_sets.Filter(
                property=object_sets.PRIMARY_KEY_FILTER,
                op="eq", value=row["primary_key"],
            ))
            definition = search_arounds.build(
                parameter, object_type_id=UUID(type_id),
                filters=confirming,
                start_key=await start_key_of(
                    conn, parameter, workspace_id=workspace_id, bound=bound,
                ),
            )
        except action_filters.Unresolved as missing:
            # **Fails closed**, for the filters and for the walk alike. The rule
            # reads a parameter nothing supplied, so whether this object is in
            # the set is a question nobody can answer — and accepting on an
            # unanswered question is how a value the rule exists to exclude
            # gets written.
            raise ValueError(
                f"{name!r} is narrowed by {missing.parameter!r}, which this "
                "submission does not supply"
            ) from missing
        # **The same call the dropdown makes**, rather than a second reading of
        # the rules: p.34 says the offered list and the accepted value are one
        # rule, and the cheapest way for them to agree is for there to be one
        # place that decides. A walk that reached nothing must refuse rather
        # than fall through, which is why this no longer skips when the
        # narrowing is empty — with a search around, empty filters and no set
        # are different answers.
        matched, _ = await choices(
            conn, workspace_id=workspace_id, object_type_id=UUID(type_id),
            filters=confirming, definition=definition, limit=1,
        )
        if not matched:
            raise ValueError(
                f"{value!r} is not among the objects {name!r} offers"
            )


async def types_by_id(
    conn: AsyncConnection, type_ids: list[str]
) -> dict[str, dict[str, Any]]:
    """The object types a form's parameters name, for labelling the controls.

    One statement for all of them: a form with four object parameters would
    otherwise be four round trips to say four names.
    """
    if not type_ids:
        return {}
    rows = await fetch_all(
        conn,
        # The title property comes back as its **api_name**, joined here rather
        # than resolved by the caller: `object_types` stores it as a foreign key
        # (`title_property_id`) and an instance's `properties` map is keyed by
        # api_name, so a caller holding the id still could not read a label out
        # of a row.
        """
        SELECT ot.id, ot.api_name, ot.display_name, p.api_name AS title_property
          FROM object_types ot
          LEFT JOIN object_type_properties p ON p.id = ot.title_property_id
         WHERE ot.id = ANY(CAST(:ids AS uuid[]))
        """,
        {"ids": list({str(t) for t in type_ids})},
    )
    return {str(r["id"]): dict(r) for r in rows}


async def property_types_of(conn: AsyncConnection, object_type_id: str) -> dict[str, str]:
    """`{api_name: data_type}` for one object type's properties.

    What a filter's declared type comes from (§221's argument, carried on the
    `Filter` rather than looked up again by each store). Its own small read
    because the type a *parameter offers* is not the action's own, so the
    property vocabulary a filter is written against is not one the action
    already had in hand.
    """
    rows = await fetch_all(
        conn,
        "SELECT api_name, data_type FROM object_type_properties "
        " WHERE object_type_id = CAST(:tid AS uuid)",
        {"tid": str(object_type_id)},
    )
    return {str(r["api_name"]): str(r["data_type"]) for r in rows}
