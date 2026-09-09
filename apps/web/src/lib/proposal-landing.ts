/**
 * What applying a proposal does to the branch it came from (§283).
 *
 * The API decides whether a commit can land; this decides what to say about it
 * *before* the Apply button is pressed. The same division `repo-settings.ts`
 * and `model-authoring.ts` take: the server owns what is legal, the browser
 * owns what to offer.
 *
 * **Applying used to publish and stop there**, which was invisible while
 * everything was committed to the default branch first - the branch was
 * already at the commit, so "the branch does not move" and "the branch is
 * right" were the same picture. They come apart the moment work happens on a
 * sandbox, which is the whole point of a pull request.
 */
import type { CodeProposalDetail } from "./types";

/** The three answers the API gives, and the one it gives for a proposal that
 *  names no repository. */
export type Landing = "landed" | "fast_forward" | "diverged" | null;

/**
 * One sentence about the branch, or nothing at all.
 *
 * **Silent for a typed-changes proposal**, which names no repository and so
 * lands on no branch (db 0039). A line reading "lands on main" there would be
 * describing something that cannot happen.
 */
export function landingNote(p: CodeProposalDetail): string | null {
  if (!p.lands_on || !p.landing) return null;
  if (p.landing === "fast_forward") {
    return `Applying this also moves ${p.lands_on} to this commit.`;
  }
  if (p.landing === "landed") {
    // Worth saying rather than staying silent: "nothing will happen to the
    // branch" and "the branch will be updated" look identical on a screen that
    // mentions neither, and the second is the one people assume.
    return `${p.lands_on} already has this commit, so applying it publishes without moving the branch.`;
  }
  return `${p.lands_on} has moved on since this was proposed.`;
}

/**
 * Whether the note is a warning rather than information.
 *
 * Only the divergence is: the other two are the system working, and styling
 * them as problems would train people past the one that is.
 */
export function landingIsAProblem(p: CodeProposalDetail): boolean {
  return p.landing === "diverged";
}

/**
 * What to do about a divergence, in the words somebody can act on.
 *
 * A fast-forward is the only landing this repository model has - there is no
 * merge commit, so a divergence cannot be resolved by moving a pointer
 * (`repositories.py`, `merge_branch`). Which means the remedy is a real
 * instruction and not "try again".
 */
export function divergenceRemedy(p: CodeProposalDetail): string | null {
  if (!landingIsAProblem(p) || !p.lands_on) return null;
  return `Merge ${p.lands_on} into the branch this was made on and propose the new commit. Landing here is fast-forward only, so this cannot be resolved by retrying.`;
}
