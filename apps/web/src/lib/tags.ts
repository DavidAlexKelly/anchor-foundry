/**
 * What the tags section of the Branches tab says (§299; p.17).
 *
 *     "The branches tab also lets you access a list of tags, which are like
 *      immutable branches. A tag can be used to mark a significant version of
 *      the code for future reference by giving it a version number or name."
 *
 * The server owns every refusal — the name convention from `repoSettings.json`,
 * the uniqueness, and the immutability, which is a database trigger. What lives
 * here is what to *offer*, the division `protected-branches.ts` and
 * `bulk-adoption.ts` already take.
 */
import type { RepositoryTag } from "./types";

/**
 * What a row says a tag points at.
 *
 * The same eight characters the History tab, the publish plan and the Pull
 * requests tab use, so the four can be read against each other. A tag's whole
 * purpose is to be resolved back to a commit, and a row that named neither the
 * commit nor its message would be a label on nothing.
 */
export function pointsAt(tag: RepositoryTag): string {
  return tag.commit_id.slice(0, 8);
}

/**
 * The line under the name.
 *
 * The tagged commit's message when there is one, because "1.4.0 · 3f2a1b9c"
 * makes you open it to find out what it was. The tag's *own* message wins when
 * it has one: somebody who wrote down why this version mattered has said
 * something the commit message does not.
 */
export function subtitle(tag: RepositoryTag): string {
  const said = tag.message?.trim() || tag.commit_message?.trim();
  return said ? `${pointsAt(tag)} · ${said}` : pointsAt(tag);
}

/**
 * Whether this name can be sent at all.
 *
 * **Not the repository's convention** — that is `repoSettings.json`'s, it is
 * read from the commit being tagged, and the browser does not have it. A second
 * copy of a regex the server reads from a file would be a rule that disagrees
 * with the file the first time somebody edits it. This is only the floor db
 * 0072 puts on the column, so that an obviously impossible name is refused
 * before a round trip rather than after one.
 */
const SHAPE = /^[A-Za-z0-9][A-Za-z0-9._+-]*$/;

export function nameProblem(name: string): string | null {
  const trimmed = name.trim();
  if (trimmed === "") return null;
  if (trimmed.length > 100) return "A tag name is at most 100 characters.";
  if (!SHAPE.test(trimmed)) {
    return (
      "A tag name starts with a letter or digit and then uses letters, digits, " +
      "dots, dashes, underscores or plus signs."
    );
  }
  return null;
}

/**
 * Whether the form can be submitted.
 *
 * Empty is not an error and not submittable: a form that turns red because you
 * have not typed anything yet is a form that shouts before you have done
 * anything wrong.
 */
export function canCreate(name: string): boolean {
  return name.trim() !== "" && nameProblem(name) === null;
}

/**
 * What the empty list says.
 *
 * **Two absences with two remedies**, and only one of them is something the
 * reader can do here: a repository with no commits has no version to mark, and
 * the refusal for that comes from the server anyway — saying it before they try
 * is the difference between a form that explains and a form that argues.
 */
export function emptyReason(tagCount: number, hasCommits: boolean): string | null {
  if (tagCount > 0) return null;
  if (!hasCommits) {
    return "Nothing has been committed here yet, so there is no version to tag.";
  }
  return (
    "No tags yet. A tag marks a version of the code for future reference — it " +
    "points at one commit and never moves, so it stays true after the branch " +
    "has gone on."
  );
}

/**
 * What the delete button asks first.
 *
 * **It asks, and it says what is not at risk.** Deleting a branch can lose
 * somebody's work, which is why p.17 warns about it; deleting a tag cannot —
 * the commit is held by `ON DELETE RESTRICT` and is exactly as safe afterwards.
 * A confirmation that did not say so would borrow the branch warning's weight
 * for a much smaller act.
 */
export function deleteQuestion(tag: RepositoryTag): string {
  return (
    `Delete the tag ${tag.name}? The commit it points at (${pointsAt(tag)}) stays ` +
    "exactly where it is — only the name goes."
  );
}

/**
 * Which commit a new tag would be pinned to, said before it is made.
 *
 * A tag is immutable, so **this is the one moment it can be got right**, and a
 * dialog that did not say which commit it was about would be asking somebody to
 * make a permanent decision blind.
 */
export function willPin(branch: string, commitId: string | undefined): string {
  if (commitId) return `Pins ${commitId.slice(0, 8)}.`;
  return `Pins the current version of ${branch}.`;
}
