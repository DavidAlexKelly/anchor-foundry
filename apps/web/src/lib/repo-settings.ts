/**
 * What the repository application's Settings tab may offer, and to whom (§279).
 *
 * `code-repositories.md` §6 quotes p.20: "Code authors can configure their
 * personal editor preferences and repository administrators can control the
 * repository's behavior and policies. Most options are admin-only, defaulting
 * to repository owners."
 *
 * **This tab exists to give the review gate a home**, which §278 found is a
 * control that lives on exactly one page in the whole product — the page B.1
 * deletes. Nothing would have errored when it went; a project would simply
 * have lost the ability to require review of its transforms, which is a
 * governance setting rather than a convenience.
 */
import type { ProjectRole } from "./types";

/**
 * Whether this person may change the review gate.
 *
 * Owner, matching `PUT /code/review-policy` — and the browser's copy of a
 * server rule is a *display* decision, not a security one: the endpoint
 * refuses an editor whatever this returns. What it buys is not offering a
 * switch that answers 403, which is §214's shape.
 */
export function canChangeReviewPolicy(role: ProjectRole): boolean {
  return role === "owner";
}

/**
 * Why the switch is not offered, for somebody who came to change it.
 *
 * Names the role rather than saying "you cannot": a reader who knows an owner
 * can do it knows who to ask, and a reader who is told only that they may not
 * goes looking for a permissions screen that does not exist.
 */
export function reviewPolicyLockedReason(role: ProjectRole): string | null {
  if (canChangeReviewPolicy(role)) return null;
  return "Only a project owner can change whether transforms need review.";
}

/**
 * **The divergence this tab has to state out loud.**
 *
 * Foundry's required-review setting is per *repository* — `repoSettings.json`,
 * `code-repositories` p.20 and TOC §28. Ours is per *project*:
 * `projects.require_code_review`, which §28 chose deliberately because the
 * review gate has to cover transforms that are not in any repository, and at
 * the time none of them were.
 *
 * So the same switch, shown in two repositories of one project, is one switch.
 * A tab that let somebody discover that by flipping it would be a worse tab
 * than one that says so, which is why this string exists rather than a label
 * reading "Require review".
 */
export function reviewPolicyScopeNote(repositoryCount: number): string {
  if (repositoryCount > 1) {
    return (
      `This applies to the whole project — all ${repositoryCount} repositories ` +
      `in it, and to transforms that are not in a repository at all. Foundry ` +
      `sets this per repository; here it is one setting, because the gate has ` +
      `to cover transforms no repository holds.`
    );
  }
  return (
    "This applies to the whole project, including transforms that are not in " +
    "a repository. Foundry sets this per repository; here it is one setting, " +
    "because the gate has to cover transforms no repository holds."
  );
}

/** What the gate does, said once, where somebody deciding can read it.
 *
 * **It gained a second consequence in §284 and this sentence had to gain one
 * too.** The gate is now also what protects a repository's default branch —
 * one switch rather than two that must agree, which is the choice this whole
 * file exists to state out loud. A description that still said only "a
 * transform cannot be changed directly" would leave somebody discovering the
 * branch rule by being refused by it. */
export function reviewPolicyEffect(required: boolean): string {
  return required
    ? "A transform cannot be changed directly. Changes arrive as a proposal and need an approving review from somebody other than their author. Each repository's default branch is protected too: commits go to a sandbox branch and land when the pull request is applied."
    : "A transform can be changed directly by anyone who may edit this project, and every repository's default branch takes commits directly. Proposals still work, and are optional.";
}
