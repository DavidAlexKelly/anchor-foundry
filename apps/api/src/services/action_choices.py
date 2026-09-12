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

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all
from . import instance_store
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
    rows, total = await instance_store.store_for(conn).list_for_type(
        search_prefix=prefix, object_type_id=object_type_id,
        limit=limit, offset=0,
    )
    return [dict(r) for r in rows], total > len(rows)


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
    wanted: dict[str, str] = {}
    for parameter in object_parameters(parameters):
        name = str(parameter.get("api_name", ""))
        value = bound.get(name)
        if value is None or value == "":
            continue
        type_id = type_of(parameter)
        if type_id is None:
            continue
        wanted[name] = type_id

    if not wanted:
        return

    prefix = await instances_service.workspace_search_prefix(conn, workspace_id)
    store = instance_store.store_for(conn)
    for name, type_id in wanted.items():
        value = str(bound[name])
        row = await store.get_instance(
            search_prefix=prefix, object_type_id=type_id, instance_id=value,
        )
        if row is None:
            raise ValueError(
                f"{value!r} is not an object of the type {name!r} asks for"
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
