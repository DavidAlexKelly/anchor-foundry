"""Whether an action can be undone (§319; db 0076; `action-types` p.154-156).

    "You can revert an action by selecting Undo in the success message after
     any successful action application." (p.154)

**No database here at all.** p.154-156 are a list of conditions under which the
undo is not offered, and every one of them is a sentence about state the caller
already holds — the run, its action type, and what the object looks like now.
The writing half is in `test_action_execution.py`, where an action is really
applied and really undone.

The refusals are tested **one at a time and in combination**, because the order
is a decision: several can be true at once, and a refusal that reported the
wrong one would send somebody to change a setting that would not help them.
"""
from __future__ import annotations

import os
import sys

import json

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import action_revert  # noqa: E402

MINE = "11111111-1111-1111-1111-111111111111"
SOMEONE_ELSE = "22222222-2222-2222-2222-222222222222"

AFTER = {"status": "open", "owner": "ada"}
BEFORE = {"status": "closed", "owner": "ada"}


def a_run(**over: object) -> dict:
    return {
        "status": "succeeded",
        "requested_by": MINE,
        "previous_properties": dict(BEFORE),
        "applied_properties": dict(AFTER),
        "revert_blocked": False,
        "reverted_at": None,
        "reverts_run_id": None,
        "revert_unsupported": None,
        **over,
    }


def a_type(**over: object) -> dict:
    return {"allow_revert": True, **over}


#: "not given", so that `current=None` can mean **the object is gone** — which
#: is a case this file has to be able to express and `None` as a default would
#: have swallowed. It did: the deleted-object test passed `None`, got `AFTER`,
#: and failed for the right reason on the first run.
UNSET = object()


def refusal(run: dict, *, actor: str = MINE, current: object = UNSET) -> str | None:
    return action_revert.refusal(
        run,
        action_type=a_type(),
        actor_id=actor,
        current_properties=AFTER if current is UNSET else current,  # type: ignore[arg-type]
    )


def test_a_fresh_successful_run_by_its_applier_can_be_undone() -> None:
    """**The case every refusal below has to be measured against.**

    Without this, "undo is refused when X" is satisfied by an undo that is
    always refused — which is the shape §302 found in five specifications and
    §315 found in a browser test three units ago.
    """
    assert refusal(a_run()) is None
    assert action_revert.can_revert(
        a_run(), action_type=a_type(), actor_id=MINE, current_properties=AFTER
    )


def test_only_the_person_who_applied_it_may_undo_it() -> None:
    """p.154: "Currently, actions can only be reverted by the user who applied
    the action.\""""
    said = refusal(a_run(), actor=SOMEONE_ELSE)
    assert said is not None and "person who applied" in said


def test_a_later_edit_to_the_object_takes_the_undo_away() -> None:
    """p.156: "An action on an object cannot be reverted once any subsequent
    edit has been made to the object.\""""
    said = refusal(a_run(), current={"status": "archived", "owner": "ada"})
    assert said is not None and "edited since" in said


def test_a_later_edit_to_a_different_property_takes_it_away_too() -> None:
    """**p.156's own emphasis**: "even if the edit is on a different property".

    This is the sentence that decides the whole storage shape — a record of
    which keys this run wrote could not see a change to `owner`, so the run
    stores the object's whole property map and the comparison is whole. The
    mutant that would pass without this test is a diff over the written keys,
    and it is a mutant somebody would write believing it was a tidy-up.
    """
    said = refusal(a_run(), current={"status": "open", "owner": "grace"})
    assert said is not None and "edited since" in said


def test_an_unrelated_key_appearing_takes_it_away() -> None:
    """The same rule from the other side: a property the object did not have
    when the action finished is also a subsequent edit."""
    said = refusal(a_run(), current={**AFTER, "note": "added later"})
    assert said is not None and "edited since" in said


def test_a_run_that_has_already_been_undone_cannot_be_undone_again() -> None:
    """p.155 calls the toast "your only opportunity". A second press would
    write the old values over whatever the first press left."""
    said = refusal(a_run(reverted_at="2026-06-01T00:00:00Z"))
    assert said is not None and "already been undone" in said


def test_an_undo_cannot_itself_be_undone() -> None:
    """Not p.154's rule but this platform's: an undo of an undo is the action
    applied again, and offering it under the word "undo" would be a button
    whose name is wrong about what it does."""
    said = refusal(a_run(reverts_run_id="33333333-3333-3333-3333-333333333333"))
    assert said is not None and "apply the action again" in said


def test_the_toggle_being_off_now_takes_it_away() -> None:
    """p.155: "An action cannot be reverted if action reverts has been toggled
    off after action submission.\""""
    said = action_revert.refusal(
        a_run(), action_type=a_type(allow_revert=False), actor_id=MINE,
        current_properties=AFTER,
    )
    assert said is not None and "switched off" in said


def test_turning_the_toggle_back_on_does_not_bring_it_back() -> None:
    """**p.155's second half**, and the reason the stamp is on the *run*:
    "even if action reverts have been toggled on again".

    A check on the action type alone would resurrect every undo the moment
    somebody flipped the switch back, which is precisely what p.155 says must
    not happen.
    """
    said = action_revert.refusal(
        a_run(revert_blocked=True), action_type=a_type(allow_revert=True),
        actor_id=MINE, current_properties=AFTER,
    )
    assert said is not None and "switched off" in said


def test_a_failed_run_has_nothing_to_undo() -> None:
    for status in ("failed", "running"):
        said = refusal(a_run(status=status))
        assert said is not None and status in said


def test_a_deleted_object_has_nothing_to_undo_onto() -> None:
    said = refusal(a_run(), current=None)
    assert said is not None and "no longer exists" in said


def test_a_run_with_no_record_of_the_old_values_says_so_plainly() -> None:
    """Every run applied before db 0076. Said as a fact rather than as a rule
    the reader has broken."""
    said = refusal(a_run(previous_properties=None))
    assert said is not None and "no record" in said


def test_the_run_s_own_reason_beats_the_generic_ones() -> None:
    """A run that created objects is refused with *that* sentence, not with
    "there is no record" — even though such a run records no snapshots."""
    said = refusal(
        a_run(revert_unsupported="This action also created another object, and "
                                 "undoing it would leave them behind.",
              previous_properties=None)
    )
    assert said is not None and "created another object" in said


def test_the_unfixable_reasons_are_reported_before_the_fixable_ones() -> None:
    """**The order is the decision.**

    Somebody else's action, on an object since edited, of a type whose toggle
    is off: all three are true, and only one of them is worth telling them.
    "Only the person who applied an action can undo it" ends the conversation;
    "undo is switched off for this action type" sends them to a setting that
    would not give them this undo even after they changed it.
    """
    said = action_revert.refusal(
        a_run(revert_blocked=True),
        action_type=a_type(allow_revert=False),
        actor_id=SOMEONE_ELSE,
        current_properties={"status": "archived"},
    )
    assert said is not None and "person who applied" in said


def test_already_undone_is_reported_before_whose_it_was() -> None:
    """A run somebody else applied and has already undone reads better as
    "already undone": it is the whole story, and the ownership rule would
    imply that the undo is still out there to be had."""
    said = action_revert.refusal(
        a_run(reverted_at="2026-06-01T00:00:00Z"), action_type=a_type(),
        actor_id=SOMEONE_ELSE, current_properties=AFTER,
    )
    assert said is not None and "already been undone" in said


# --- the rest of what a run wrote (§551; db 0114) ------------------------------
#
# 0076 recorded a sentence for a run that created, deleted or changed other
# objects, and refused it. db 0114 records those objects instead, so they can
# be put back - under p.156's rule for each of them, not only the subject.

CREATED = {"kind": "create", "object_type_id": "t", "source_id": "s", "primary_key": "k1",
           "properties": {"name": "New"}}
REMOVED = {"kind": "remove", "object_type_id": "t", "source_id": "s", "primary_key": "k2",
           "properties": {"name": "Old"}, "subject": False}
CHANGED = {"kind": "modify", "object_type_id": "t", "source_id": "s", "primary_key": "k3",
           "instance_id": "i3", "before": {"n": 1}, "after": {"n": 2}}


def test_a_run_s_effects_are_read_from_what_the_database_hands_back() -> None:
    assert action_revert.effects_of(a_run(revert_effects=[CREATED])) == [CREATED]
    assert action_revert.effects_of(a_run(revert_effects=json.dumps([CHANGED]))) == [CHANGED]
    assert action_revert.effects_of(a_run(revert_effects=None)) == []
    assert action_revert.effects_of(a_run()) == []


def test_everything_as_the_run_left_it_can_be_put_back() -> None:
    assert action_revert.effects_refusal(
        [CREATED, REMOVED, CHANGED], [{"name": "New"}, None, {"n": 2}]
    ) is None
    assert action_revert.effects_refusal([], []) is None


def test_a_created_object_edited_or_deleted_since_is_refused() -> None:
    for now in ({"name": "Renamed"}, None):
        said = action_revert.effects_refusal([CREATED], [now])
        assert said is not None and "created has been edited or deleted since" in said


def test_a_deleted_object_that_is_back_is_refused() -> None:
    said = action_revert.effects_refusal([REMOVED], [{"name": "Someone else"}])
    assert said is not None and "deleted has been created again" in said


def test_another_changed_object_edited_since_is_refused() -> None:
    """p.156's "even if the edit is on a different property", for the objects
    around the subject as for the subject."""
    said = action_revert.effects_refusal([CHANGED], [{"n": 2, "other": "x"}])
    assert said is not None and "edited since" in said


def test_the_subject_s_own_deletion_is_judged_as_the_subject() -> None:
    """The subject is `refusal`'s to judge: gone is what a run that deleted it
    leaves, and back again is what an undo would overwrite."""
    gone = dict(REMOVED, subject=True)
    assert action_revert.effects_refusal([gone], [{"name": "Back"}]) is None
    run = a_run(revert_effects=[gone])
    assert action_revert.subject_removed(run) is True
    assert action_revert.subject_removed(a_run(revert_effects=[REMOVED])) is False
    assert refusal(run, current=None) is None
    said = refusal(run, current={"name": "Back"})
    assert said is not None and "created again since" in said


def test_a_run_recorded_before_its_effects_keeps_its_sentence() -> None:
    """0076's runs said why they could not be undone, and it is still true."""
    said = refusal(a_run(revert_unsupported="This action also created another object."))
    assert said == "This action also created another object."
