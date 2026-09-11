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


# --- what the apply path records (§319) ---------------------------------------


def test_an_ordinary_edit_records_no_reason() -> None:
    assert action_revert.unsupported_reason(
        creations=0, removals=0, other_modifications=0
    ) is None


def test_a_creating_action_says_what_would_be_left_behind() -> None:
    said = action_revert.unsupported_reason(
        creations=2, removals=0, other_modifications=0
    )
    assert said is not None and "created 2 other objects" in said
    assert "leave them behind" in said


def test_a_deleting_action_says_what_would_not_come_back() -> None:
    said = action_revert.unsupported_reason(
        creations=0, removals=1, other_modifications=0
    )
    assert said is not None and "deleted another object" in said
    assert "bring them back" in said


def test_an_action_that_touches_its_neighbours_says_so() -> None:
    said = action_revert.unsupported_reason(
        creations=0, removals=0, other_modifications=3
    )
    assert said is not None and "changed 3 other objects" in said


def test_one_is_named_rather_than_counted() -> None:
    """"1 other objects" is the kind of sentence that makes a reader distrust
    the rest of the screen."""
    said = action_revert.unsupported_reason(
        creations=1, removals=0, other_modifications=0
    )
    assert said is not None and "another object" in said and "1 other" not in said


@pytest.mark.parametrize(
    "kinds",
    [
        {"creations": 1, "removals": 1, "other_modifications": 0},
        {"creations": 1, "removals": 0, "other_modifications": 1},
        {"creations": 0, "removals": 1, "other_modifications": 1},
    ],
)
def test_a_run_that_did_several_of_them_still_gets_one_sentence(kinds: dict) -> None:
    """Only one reason is shown, and it is the first that applies. A refusal
    that listed three would be a paragraph where a sentence was wanted, and the
    reader cannot act on any of them anyway."""
    said = action_revert.unsupported_reason(**kinds)  # type: ignore[arg-type]
    assert said is not None
    assert said.count(".") == 1
