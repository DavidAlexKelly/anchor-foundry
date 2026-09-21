"""One object, named in a URL (Foundry `workshop` p.199).

> "The following variables types are unable to be used in the URL: Object set
> filter variables / **Object set variables are limited to single objects,
> specified by their RID**" (p.199)

So p.199 is not the blanket refusal it reads as at a glance: one object *is*
routable, and only by an identifier rather than by a definition. This is that
identifier, and the half of it that turns back into an object.

**Two UUIDs joined by a colon**, the object type and the instance. Opaque, like
the RID p.199 names, and for the same reason: what travels in a link is a
*reference*, and a reference that carried the object's properties would be a
snapshot somebody could edit by hand before sending it on.

Neither half can contain the separator, so parsing needs no subtlety and a
malformed ref is refused outright rather than half-read. §414 spent a mutant
on exactly that distinction in a different format; here the shape rules it out.

**Rehydration happens in the route, not in the evaluator.** `evaluate` is pure
and synchronous — it computes a graph and touches no database — and a lookup
belongs on the async side of that line. The route expands a ref into the object
before the graph is resolved, using the same RLS-checked read the click that
first selected it would have made: a link cannot show its recipient an object
they could not have opened themselves.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

#: Between the type and the instance. A colon because a RID uses them and
#: because neither half can contain one.
SEPARATOR = ":"


def ref_for(value: Any) -> str | None:
    """The URL form of a `single_object` value, or None when there is none.

    Nothing picked is None rather than an empty string: an empty parameter in a
    link is a parameter somebody has to decide the meaning of, and the meaning
    is "this key should not be here at all".
    """
    if not isinstance(value, dict):
        return None
    type_id = value.get("object_type_id")
    instance_id = value.get("id")
    if not isinstance(type_id, str) or not isinstance(instance_id, str):
        return None
    if not type_id or not instance_id:
        return None
    return f"{type_id}{SEPARATOR}{instance_id}"


def parse_ref(raw: Any) -> tuple[UUID, UUID] | None:
    """The type and instance a ref names, or None if it names neither.

    **Both halves are checked as UUIDs**, which is not ceremony: this value
    arrives from a URL somebody may have typed, and the two ids go straight
    into a read. A string that is not a pair of UUIDs is not a reference to
    something missing — it is not a reference at all, and the difference
    matters to the caller, which treats the first as "nothing picked" and has
    no business issuing a query for the second.
    """
    if not isinstance(raw, str) or SEPARATOR not in raw:
        return None
    type_part, _, instance_part = raw.partition(SEPARATOR)
    try:
        return UUID(type_part), UUID(instance_part)
    except ValueError:
        return None
