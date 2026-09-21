"""One object, named in a URL (§416; `workshop` p.199).

> "Object set variables are limited to single objects, specified by their RID"
> (p.199)

The format half. `test_canvas.py` covers what the route does with a ref; this
covers what a ref *is*, and — because the browser writes what this reads — that
the two ends agree without either importing the other.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import object_refs  # noqa: E402

TYPE = "22222222-2222-2222-2222-222222222222"
INSTANCE = "11111111-1111-1111-1111-111111111111"
WEB_REF = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "web", "src", "components", "canvas", "object-ref.ts",
)


def picked(**over):
    return {
        "id": INSTANCE, "object_type_id": TYPE,
        "primary_key": "R1", "properties": {"name": "North"},
        **over,
    }


def test_a_ref_names_the_type_and_the_instance() -> None:
    assert object_refs.ref_for(picked()) == f"{TYPE}:{INSTANCE}"


def test_a_ref_carries_no_properties() -> None:
    """p.199 says RID, and this is why: a reference carrying the object's
    properties would be a snapshot somebody could edit by hand before sending
    the link on, and the recipient would have no way to tell."""
    ref = object_refs.ref_for(picked())
    assert "North" not in ref
    assert "R1" not in ref


def test_a_ref_round_trips() -> None:
    parsed = object_refs.parse_ref(object_refs.ref_for(picked()))
    assert parsed is not None
    assert [str(part) for part in parsed] == [TYPE, INSTANCE]


def test_nothing_picked_has_no_ref() -> None:
    """Not an empty string: an empty parameter in a link is one whose meaning
    somebody has to decide, and the meaning is that the key does not belong in
    the address at all."""
    for value in (None, "", 7, [], {}, {"id": INSTANCE}, {"object_type_id": TYPE}):
        assert object_refs.ref_for(value) is None


def test_half_a_reference_is_not_a_shorter_one() -> None:
    for value in (picked(id=""), picked(object_type_id=""),
                  picked(id=7), picked(object_type_id=None)):
        assert object_refs.ref_for(value) is None


def test_a_string_that_is_not_a_pair_of_uuids_is_not_a_reference() -> None:
    """**The distinction the caller acts on.** A ref naming something missing
    still gets a lookup; a string that was never a ref does not, and issuing a
    query for `banana:split` would be asking the database about a typo."""
    for raw in ("banana", "a:b", f"{TYPE}:", f":{INSTANCE}", f"{TYPE}:not-a-uuid",
                None, 7, f"{TYPE}", f"{TYPE}:{INSTANCE}:extra"):
        assert object_refs.parse_ref(raw) is None, raw


def test_the_separator_is_one_the_halves_cannot_contain() -> None:
    """Which is what lets `parse_ref` refuse rather than tie-break. A UUID has
    no colon, so there is no "first separator wins" rule to get wrong — §414
    spent a mutant on exactly that in a format where the halves *could*
    collide."""
    assert object_refs.SEPARATOR not in TYPE
    assert object_refs.SEPARATOR not in INSTANCE


def test_the_browser_writes_what_this_reads() -> None:
    """**The two ends agree, pinned rather than trusted** (the shape §410 used).

    `object-ref.ts` builds the ref and this module parses it, in two languages
    that cannot import each other. A separator changed on one side would make
    every routed selection silently unresolvable — a link that restores the
    page and loses the thing it was shared for, which is the exact failure
    `ROUTABLE_KINDS` exists to prevent.
    """
    source = open(WEB_REF).read()
    match = re.search(r'export const REF_SEPARATOR = "(.*?)";', source)
    assert match, "object-ref.ts no longer declares REF_SEPARATOR"
    assert match.group(1) == object_refs.SEPARATOR

    # And the same two fields, in the same order, so the string matches.
    assert re.search(r"\$\{typeId\}\$\{REF_SEPARATOR\}\$\{instanceId\}", source), (
        "object-ref.ts no longer writes <type><separator><instance>"
    )
