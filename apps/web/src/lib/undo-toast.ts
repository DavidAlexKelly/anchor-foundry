/**
 * p.154's success message, and the Undo in it (§319; `action-types` p.154-156).
 *
 *     "You can revert an action by selecting Undo in the success message after
 *      any successful action application." (p.154)
 *
 *     "The toast below is your only opportunity to revert the action. This is
 *      especially important to note when performing delete actions." (p.155)
 *
 * **The server decides whether the undo exists; this decides what to say about
 * it.** Every one of p.154-156's conditions is about state a browser does not
 * have — who applied the run, what the object looked like when it finished,
 * whether the toggle has been off at any point since — so the answer arrives
 * with the result and is not re-derived here. This module is the wording, the
 * same division `object-type-issues.ts` draws between the count and the
 * sentence.
 */
import type { ActionExecuteResult } from "./types";

/** What the toast offers, if anything. */
export type UndoOffer =
  | { kind: "offer"; runId: string }
  | { kind: "refused"; why: string }
  | { kind: "none" };

/**
 * Whether to draw Undo, and what to say instead.
 *
 * **"Refused" is a state with words in it, not a missing button.** p.155 calls
 * this "your only opportunity", so a toast that silently omits Undo tells
 * somebody nothing at the one moment they could have acted — and the two
 * reasons they can do something about (the object was edited since; the toggle
 * is off) are indistinguishable from the four they cannot unless the sentence
 * is on screen.
 *
 * `none` is for a result that did not succeed. There the error is the message,
 * and an undo line beside it would be answering a question nobody asked.
 */
export function undoOffer(result: ActionExecuteResult): UndoOffer {
  if (!result.ok) return { kind: "none" };
  if (result.can_undo && result.run_id) {
    return { kind: "offer", runId: result.run_id };
  }
  return { kind: "refused", why: result.undo_refusal ?? "This cannot be undone." };
}

/**
 * The success line itself.
 *
 * **Names the action, not the properties.** p.155's screenshot heads the toast
 * "Edits applied:" and lists them, and a list is right where the form is gone
 * — but the thing somebody is deciding to undo is *the action they just ran*,
 * and its display name is what they clicked. The properties are on the object
 * behind the toast either way.
 */
export function appliedMessage(actionName: string): string {
  return `${actionName} applied.`;
}

/** The same sentence for an undo that has landed (p.155's "Edits reverted:"). */
export function undoneMessage(actionName: string): string {
  return `${actionName} undone.`;
}

/**
 * How long the toast stays.
 *
 * **It does not go on its own, and that is a deliberate divergence.** Foundry's
 * fades, which is what makes p.156 need a section called "Undoing a delete
 * action without the revert action toast" — and the two remediations it offers
 * there are *migrate to a new object type* and *drop all edits on the object
 * type*, neither of which exists here. Taking the undo away on a timer would
 * therefore leave somebody with no route at all, so it stays until it is
 * dismissed or the next action replaces it.
 *
 * Exported as a named constant rather than left implicit, so the divergence is
 * a thing somebody can find and change rather than an absence of code.
 */
export const TOAST_DISMISSES_ITSELF = false;
