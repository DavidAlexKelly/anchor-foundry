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

import json
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
    if subject_removed(run):
        # p.156's "reverting a delete action" (§551): the object is meant to
        # be gone, and the undo writes it back - unless something has put an
        # object under its key since, which the undo would overwrite.
        if current_properties is not None:
            return (
                "The object this action deleted has been created again since, so "
                "undoing it would overwrite that one."
            )
        return None
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


def effects_of(run: dict[str, Any]) -> list[dict[str, Any]]:
    """What this run did besides writing its subject (db 0114; §551): the
    objects it created, deleted and changed, each with what the undo needs to
    put it back. Empty for a run that did nothing else, or one recorded before
    db 0114 - which carries `revert_unsupported` instead and is refused by it.
    """
    raw = run.get("revert_effects")
    if isinstance(raw, str):
        raw = json.loads(raw)
    return [dict(e) for e in raw] if isinstance(raw, list) else []


def subject_removed(run: dict[str, Any]) -> bool:
    """Whether the run deleted the very object it was applied to."""
    return any(e.get("kind") == "remove" and e.get("subject") for e in effects_of(run))


def links_refusal(links: list[dict[str, Any]], present: list[bool]) -> str | None:
    """Why the links this run made or removed in a join table cannot be put
    back (§553), or `None`. `present` is whether each is in its join table now.

    p.156's rule again, for a link: one the run made must still be there, and
    one it removed still gone, or the undo would reverse somebody else's
    later decision about it."""
    for link, now in zip(links, present):
        if link.get("made") and not now:
            return (
                "A link this action made has been removed since, so there is no "
                "longer anything of it to undo."
            )
        if not link.get("made") and now:
            return (
                "A link this action removed has been made again since, so undoing "
                "it would undo that one."
            )
    return None


def effects_refusal(
    effects: list[dict[str, Any]], current: list[dict[str, Any] | None],
) -> str | None:
    """Why the objects this run touched besides its subject cannot be put back,
    or `None` if they can. `current` is each one's properties now, in the same
    order, or `None` where it no longer exists.

    **p.156's rule, for every object and not only the subject**: "an action on
    an object cannot be reverted once any subsequent edit has been made to the
    object, even if the edit is on a different property". An object the run
    created must still be exactly as created, one it deleted still gone, and
    one it changed still as it left it - or the undo would overwrite, delete or
    resurrect something a later edit decided.
    """
    for effect, now in zip(effects, current):
        kind = effect.get("kind")
        if kind == "create" and now != effect.get("properties"):
            return (
                "An object this action created has been edited or deleted since, "
                "so undoing it would lose that change."
            )
        if kind == "remove" and not effect.get("subject") and now is not None:
            return (
                "An object this action deleted has been created again since, so "
                "undoing it would overwrite that one."
            )
        if kind == "modify" and now != effect.get("after"):
            return (
                "Another object this action changed has been edited since, so "
                "undoing it would overwrite the newer change."
            )
    return None
