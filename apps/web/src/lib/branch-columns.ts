/**
 * p.16's Checks and Pull request columns on the Branches tab (§300).
 *
 *     "The 'Checks' column indicates whether or not the automatic code checks
 *      have passed for a branch. The 'Pull request' column tells you about any
 *      existing Pull requests in a branch and lets you create new Pull
 *      requests. To create a new Pull request that contains the changes on a
 *      branch, click the 'Propose changes' button… If you don't see the button
 *      to create a new Pull request, it means that a Pull request already
 *      exists for a branch. Click on the 'Open' / 'Closed' / 'Merged' button to
 *      open the full Pull request." (p.16–17)
 *
 * That last sentence is a *rule*, not a description: the button and the state
 * are the same slot, and which one is there says which situation you are in.
 * Two controls side by side would lose that.
 *
 * The server owns what is true (`repositories.branch_summary`); this owns what
 * to say about it.
 */
import type { RepositoryBranchSummary } from "./types";

/**
 * What the Checks column says.
 *
 * **`none` is its own answer and never a tick.** "Nothing failed" and
 * "everything passed" are the same number, and a branch nothing has run against
 * is the case somebody is most likely to merge on the strength of a green
 * column. §295 refuses the same lie about a test suite that ran nothing.
 */
export function checksLabel(branch: RepositoryBranchSummary): string {
  if (branch.head_commit_id === null) return "—";
  if (branch.checks === "passed") return "passed";
  if (branch.checks === "failed") return "failed";
  return "not run";
}

/** Whether the Checks column should read as bad news. */
export function checksAreAProblem(branch: RepositoryBranchSummary): boolean {
  return branch.checks === "failed";
}

/**
 * What the Pull request column offers, which is **one of two things and never
 * both** (p.16–17).
 *
 * A branch with a proposal over its head shows that proposal's state and opens
 * it; a branch without one shows "Propose changes". Foundry says the absence of
 * the button *is* how you know a pull request exists, so a screen that showed
 * both would be answering a question the reader did not have to ask.
 */
export type PullRequestSlot =
  | { kind: "none"; reason: string }
  | { kind: "propose" }
  | { kind: "open"; id: string; state: string; summary: string };

export function pullRequestSlot(branch: RepositoryBranchSummary): PullRequestSlot {
  if (branch.head_commit_id === null) {
    // A branch with no commits has nothing to propose, and offering the button
    // would be offering a refusal (§214).
    return { kind: "none", reason: "nothing committed" };
  }
  if (branch.proposal_id) {
    return {
      kind: "open",
      id: branch.proposal_id,
      state: branch.proposal_state ?? "open",
      summary: branch.proposal_summary ?? "",
    };
  }
  return { kind: "propose" };
}

/**
 * The word on the button that opens an existing pull request.
 *
 * p.17 names three — "Open" / "Closed" / "Merged" — and ours has three of its
 * own (db 0039: open, applied, withdrawn), which are not the same three.
 * **Translated rather than renamed**: `applied` is Foundry's "Merged" in every
 * way that matters to a reader, and calling ours `applied` on a screen whose
 * shape is borrowed from p.17 would make the two harder to compare, not easier.
 */
export function proposalStateLabel(state: string): string {
  if (state === "applied") return "Merged";
  if (state === "withdrawn") return "Closed";
  return "Open";
}

/**
 * Why a branch cannot be proposed from, or null when it can.
 *
 * **The default branch is the one case worth naming.** Applying a proposal
 * lands its commit on the default branch (§283), so proposing the default
 * branch into itself is a review of nothing — and the refusal is more useful
 * before the click than after it.
 */
export function proposeProblem(
  branch: RepositoryBranchSummary,
  defaultBranch: string,
): string | null {
  if (branch.head_commit_id === null) return "Nothing has been committed here yet.";
  if (branch.name === defaultBranch) {
    return (
      `${defaultBranch} is where applied changes land, so there is nothing to ` +
      "propose it into. Commit on a sandbox branch and propose that."
    );
  }
  return null;
}
