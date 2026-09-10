/**
 * Which branch may be committed to, and what to offer instead (§284).
 *
 * `code-repositories.md` §2.1 quotes p.12: *"To edit code in your repository,
 * you must work in a sandbox branch — protected branches cannot be directly
 * edited."* The spec calls it "the one to take seriously… it is what makes the
 * Pull requests tab load-bearing rather than optional".
 *
 * **Protection is the review gate, not a second switch.** The default branch is
 * protected exactly when the project requires review. The server owns that rule
 * (`repositories.py`, `assert_branch_is_writable`); what lives here is what to
 * *offer*, which is the division `repo-settings.ts` and `model-authoring.ts`
 * already take — and the reason a browser copy of a server rule is a display
 * decision rather than a security one: the commit endpoint refuses whatever
 * this returns.
 *
 * What it buys is not putting somebody in front of an editor that takes their
 * typing and then refuses to keep it (§214).
 */

/** Everything the rule depends on, in the order it is asked. */
export type BranchContext = {
  branch: string;
  defaultBranch: string;
  reviewRequired: boolean;
  /** Whether this branch has anything committed to it yet. */
  hasCommits: boolean;
};

/**
 * Whether committing here is refused.
 *
 * **A branch with no commits is not protected**, because there is nothing to
 * edit yet: putting a repository's first commit on its default branch is how a
 * repository starts, and it is what Foundry does from a template. The server
 * makes the same exception, and a browser that did not would hide a door that
 * is actually open.
 */
export function isProtected(ctx: BranchContext): boolean {
  if (ctx.branch !== ctx.defaultBranch) return false;
  if (!ctx.reviewRequired) return false;
  return ctx.hasCommits;
}

/**
 * Why, and the way through — or null when there is nothing to say.
 *
 * **Names the route rather than the rule.** A refusal that only says no
 * teaches people the product is broken; this one says which branch, why it is
 * protected, and what to do, including the part §283 built: applying the pull
 * request is what moves the branch, so working on a sandbox is not a detour
 * that leaves the work stranded somewhere else.
 */
export function protectedReason(ctx: BranchContext): string | null {
  if (!isProtected(ctx)) return null;
  return (
    `${ctx.branch} is protected because this project requires code review. ` +
    `Create a sandbox branch from it, commit there, and open a pull request — ` +
    `applying that moves ${ctx.branch} to your commit.`
  );
}

/**
 * A name to offer for the sandbox this person is about to need.
 *
 * Suggested rather than imposed, and the shape is the one Foundry's own
 * screenshots use: a short prefix and something unique, because the branch a
 * sandbox is *from* is already knowable and the branch it is *for* is not.
 */
export function suggestedSandboxName(existing: string[]): string {
  for (let n = 1; ; n += 1) {
    const name = `sandbox-${n}`;
    if (!existing.includes(name)) return name;
  }
}
