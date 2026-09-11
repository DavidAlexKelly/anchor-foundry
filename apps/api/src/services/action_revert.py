"""Whether an action can be undone, and why not (§319; db 0076;
`action-types` p.154-156).

    "Action reverts in Ontology Manager allow an action to be reverted (that
     is, undone) immediately after the action has been applied. You can revert
     an action by selecting Undo in the success message after any successful
     action application." (p.154)

**The decision is pure and the writing is not**, which is the whole shape of
this module. p.154-156 are mostly a list of conditions under which an undo is
*not* offered, and each is a sentence about state somebody already has in hand:
the run, the action type, and what the object looks like now. Nothing here
reads a database, so every refusal is a test that runs in microseconds and none
of them needs an object to exist.

**Every refusal says what happened, not that something did.** p.155 calls the
toast "your only opportunity to revert the action" — somebody who missed it
needs to know which of six reasons applies, because two of them (another edit
landed; the toggle was turned off) are things a person can do something about
and the rest are not.
"""
from __future__ import annotations

from typing import Any

#: What a run must be for an undo to be worth offering. A failed run changed
#: nothing to undo, and a running one has not finished changing it.
REVERTIBLE_STATUS = "succeeded"


class RevertRefused(Exception):
    """The undo was asked for and cannot be given. Carries p.154-156's reason."""


def refusal(
    run: dict[str, Any],
    *,
    action_type: dict[str, Any],
    actor_id: str,
    current_properties: dict[str, Any] | None,
) -> str | None:
    """Why this run cannot be undone, or `None` if it can.

    **Ordered by what the reader most needs to hear.** Several of these can be
    true at once — an action somebody else applied, to an object since edited,
    whose type had its toggle turned off — and a refusal that reported the
    third of those would send them to change a setting that would not help.
    So the fixed, unhelpable facts come first: it is not yours, it is already
    undone, it never could be.

    `current_properties` is `None` when the object is gone. That is its own
    answer rather than a missing one: there is nothing left to write the old
    values onto.
    """
    if str(run.get("status")) != REVERTIBLE_STATUS:
        return (
            "Only a successful action can be undone, and this one "
            f"{run.get('status')}."
        )
    if run.get("reverted_at") is not None:
        # p.155: the toast is "your only opportunity". An undo that could be
        # pressed twice would write the old values over whatever the second
        # press found — which is the very thing every other rule here prevents.
        return "This action has already been undone."
    if run.get("reverts_run_id") is not None:
        # **An undo of an undo is the action again.** Offering it under the
        # word "undo" would be a button whose name is wrong about what it does,
        # and the honest form of it is already on screen: apply the action.
        return (
            "This was itself an undo. To put the change back, apply the action "
            "again."
        )
    if str(run.get("requested_by")) != str(actor_id):
        # p.154: "Currently, actions can only be reverted by the user who
        # applied the action."
        return "Only the person who applied an action can undo it."
    if run.get("revert_unsupported"):
        return str(run["revert_unsupported"])
    if run.get("revert_blocked") or not action_type.get("allow_revert", True):
        # p.155: "An action cannot be reverted if action reverts has been
        # toggled off after action submission, even if action reverts have been
        # toggled on again." The stamp on the run is what makes the second half
        # of that sentence true.
        return (
            "Undo is switched off for this action type, so this application "
            "can no longer be undone."
        )
    if run.get("previous_properties") is None:
        # A run from before db 0076, or one that recorded nothing. Said plainly
        # rather than reported as a rule the reader has broken.
        return "There is no record of what this object looked like beforehand."
    if current_properties is None:
        return "This object no longer exists, so there is nothing to undo onto."
    if current_properties != run.get("applied_properties"):
        # p.156: "An action on an object cannot be reverted once any subsequent
        # edit has been made to the object, **even if the edit is on a
        # different property**." Compared whole for exactly that reason — a
        # diff of the keys this run wrote cannot see a change to another one.
        return (
            "This object has been edited since, so undoing this action would "
            "overwrite the newer change."
        )
    return None


def can_revert(
    run: dict[str, Any],
    *,
    action_type: dict[str, Any],
    actor_id: str,
    current_properties: dict[str, Any] | None,
) -> bool:
    """The same question as a boolean, for a screen deciding whether to draw a
    button. The reason is what a screen shows when it does not."""
    return refusal(
        run,
        action_type=action_type,
        actor_id=actor_id,
        current_properties=current_properties,
    ) is None


def unsupported_reason(
    *, creations: int, removals: int, other_modifications: int
) -> str | None:
    """Why this run will never be undoable, decided while it is being applied.

    **Written at apply time because nothing later knows.** A run's rows are
    gone from this platform's point of view once the dataset version is
    committed: the appended rows are indistinguishable from any other, so a
    revert reading only `action_runs` could not tell that three objects were
    created alongside the edit it was asked to undo.

    Restoring the subject's properties while leaving those creations in place
    is an undo that half-works, which §214 argues is worse than one that says
    it cannot — so the run records the sentence, and the Undo button is absent
    with that sentence in its place.
    """
    if creations:
        return (
            f"This action also created {_things(creations)}, and undoing it "
            "would leave them behind."
        )
    if removals:
        return (
            f"This action also deleted {_things(removals)}, and undoing it "
            "would not bring them back."
        )
    if other_modifications:
        return (
            f"This action also changed {_things(other_modifications)}, and "
            "undoing it would only put this one back."
        )
    return None


def _things(count: int) -> str:
    return "another object" if count == 1 else f"{count} other objects"
