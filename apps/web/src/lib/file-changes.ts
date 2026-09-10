/**
 * What the File Changes panel says (§287; `code-repositories.md` §2.4).
 *
 * p.14: *"The File Changes helper can be used to view any uncommitted changes
 * to the current file, as well as compare previous versions of the file."*
 *
 * The server builds the diff, with the same aligner the review surface uses —
 * a second alignment would be a second answer the first time either was
 * improved. What lives here is how the result reads: the one-line header, what
 * an empty panel means, and how a version in the picker is described.
 */
import type { RepositoryFileChanges, RepositoryFileVersion } from "./types";

/**
 * The panel's header line.
 *
 * **Counted separately, and never as a single total.** "Two lines changed"
 * hides whether a file grew or shrank, and the difference is most of what
 * somebody wants from a glance. A `changed` row counts on both sides, because
 * it is a line removed and a line put in its place.
 */
export function headline(changes: RepositoryFileChanges): string {
  if (changes.state === "unchanged") return "No uncommitted changes to this file.";
  if (changes.state === "added") {
    return `New file — ${changes.added} line${changes.added === 1 ? "" : "s"}.`;
  }
  if (changes.state === "deleted") {
    return `Deleted — ${changes.removed} line${changes.removed === 1 ? "" : "s"} removed.`;
  }
  return `+${changes.added} −${changes.removed}`;
}

/**
 * Whether there is a diff worth rendering.
 *
 * **An unchanged file has rows and they are all `same`.** Rendering them is a
 * whole file in a panel sized for a diff, so the panel says "no uncommitted
 * changes" instead — but the rows are still *there*, which is why this asks
 * about the state rather than about the row count.
 */
export function hasChanges(changes: RepositoryFileChanges): boolean {
  return changes.state !== "unchanged";
}

/**
 * The rows to show: the changed ones, with a little of what surrounds them.
 *
 * **Context, because a diff with none is unreadable.** A `changed` row three
 * hundred lines into a file, shown alone, tells you what the line says and
 * nothing about what it is part of. Three lines either side is the number
 * `difflib` itself defaults to, and matching it means the panel and a unified
 * diff of the same file agree about what is worth showing.
 */
export function withContext(
  rows: RepositoryFileChanges["rows"],
  context = 3,
): RepositoryFileChanges["rows"] {
  const keep = new Set<number>();
  rows.forEach((row, index) => {
    if (row.kind === "same") return;
    // **No bounds check on `i`, and a mutant proved one was doing nothing**
    // (§213): the set is asked about an index only by `filter`, which never
    // offers one outside the array. An index of -1 in here is a number nobody
    // looks up.
    for (let i = index - context; i <= index + context; i += 1) keep.add(i);
  });
  return rows.filter((_, index) => keep.has(index));
}

/**
 * Whether a gap was elided between two rows, so the panel can say so.
 *
 * A diff that silently skips two hundred lines and shows the next change
 * flush against the last one is a diff that reads as one hunk. Saying "…"
 * costs a line and stops that.
 */
export function isGap(
  rows: RepositoryFileChanges["rows"],
  shown: RepositoryFileChanges["rows"],
  index: number,
): boolean {
  const here = shown[index];
  const before = shown[index - 1];
  // An index off either end is not a gap. Reading past the array is how a
  // marker appears above the first row, which would claim lines were skipped
  // before the file began.
  if (here === undefined || before === undefined) return false;
  return rows.indexOf(here) - rows.indexOf(before) > 1;
}

/** How a version reads in the picker. */
export function versionLabel(version: RepositoryFileVersion): string {
  const when = new Date(version.created_at).toLocaleString();
  const what = version.message.trim() || "no message";
  return `${what} — ${when}`;
}

/**
 * What an empty version list means.
 *
 * A file that has never been committed has no previous versions, which is a
 * different answer from a file whose history this branch does not have — and
 * the second is what a new sandbox looks like before anybody commits to it.
 */
export function versionsEmptyNote(state: string): string {
  return state === "added"
    ? "This file is not committed yet, so it has no previous versions."
    : "No commits on this branch have changed this file.";
}
