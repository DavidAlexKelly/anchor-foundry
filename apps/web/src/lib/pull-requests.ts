/**
 * Which proposals belong on a repository's Pull requests tab (§276).
 *
 * `code-repositories.md` §1 wants five tabs and calls proposals "Pull
 * requests"; ours live on the project's Code pillar page, which is the page
 * B.1 deletes. This is the rule for what the tab shows, and it exists as a
 * module because the answer is not obvious.
 *
 * **A proposal is a project-level thing and a repository is one of several.**
 * db 0039 gave a proposal an optional `source_repo_id`, set when it asks to
 * publish a commit and null when it carries typed changes to named transforms.
 * So "this project's proposals" and "this repository's proposals" are
 * different lists, and a tab that showed the first would put another
 * repository's review in front of somebody looking at this one.
 *
 * The typed-changes proposals belong to **no** repository, so they cannot be
 * shown here honestly — they stay on the Code page until adoption (§274) has
 * made them unnecessary, and `unrepositoried` is what lets a screen say so
 * rather than leaving them out silently.
 */
import type { CodeProposal } from "./types";

/** A proposal that asks to publish a commit from *this* repository. */
export function forRepository(
  proposals: readonly CodeProposal[],
  repositoryId: string,
): CodeProposal[] {
  return proposals.filter((p) => p.source_repo_id === repositoryId);
}

/**
 * Proposals in this project that name no repository at all.
 *
 * Not shown in the tab, and **counted rather than hidden**: they are the
 * typed-changes shape, they are still reviewable on the Code page, and a
 * reviewer who cannot find one they were told about is worse served by a tidy
 * list than by a sentence saying where it is.
 */
export function unrepositoried(proposals: readonly CodeProposal[]): CodeProposal[] {
  return proposals.filter((p) => !p.source_repo_id);
}

/** How a row describes what a proposal would do.
 *
 * A commit proposal's file count is derived from the commit, so the useful
 * thing to show is *which commit* — the same eight characters the History tab
 * and the publish plan use, so the three can be read against each other.
 */
export function describe(proposal: CodeProposal): string {
  if (proposal.source_commit_id) {
    return `publishes ${proposal.source_commit_id.slice(0, 8)}`;
  }
  return `${proposal.file_count} file${proposal.file_count === 1 ? "" : "s"}`;
}

/** What the tab says when it has nothing to show, which is two different
 * situations and only one of them is "nothing is happening".
 *
 * A project can have open proposals that this repository has none of — and a
 * reviewer who was sent a link, and finds an empty tab, needs to know the
 * difference between "already dealt with" and "not here". */
export function emptyReason(
  proposals: readonly CodeProposal[],
  repositoryId: string,
): string | null {
  if (forRepository(proposals, repositoryId).length > 0) return null;
  const elsewhere = proposals.length - forRepository(proposals, repositoryId).length;
  if (elsewhere === 0) {
    return "No open proposals for this repository.";
  }
  const other = unrepositoried(proposals).length;
  if (other === elsewhere) {
    return (
      `No open proposals for this repository. ${elsewhere} in this project ` +
      `${elsewhere === 1 ? "changes a transform" : "change transforms"} directly ` +
      `rather than publishing a commit, and ${elsewhere === 1 ? "is" : "are"} ` +
      `reviewed on the Code screen.`
    );
  }
  return (
    `No open proposals for this repository. ${elsewhere} in this project ` +
    `${elsewhere === 1 ? "belongs" : "belong"} to something else.`
  );
}
