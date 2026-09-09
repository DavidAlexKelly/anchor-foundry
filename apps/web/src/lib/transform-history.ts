/**
 * How the project's transform history reads (§280).
 *
 * §278 found this among the capabilities living only on the page B.1 deletes:
 * `codeApi.history` is **the project's** transform history, and the repository
 * application's History tab is *commits in one repository*. Those are
 * different lists and neither substitutes for the other — a project's
 * transforms span repositories, and include ones in no repository at all.
 *
 * **What makes it worth keeping is the grouping.** Decision 0001 called the
 * change set "the one genuinely new concept": before it, *"these three
 * transforms changed together, for one reason"* could not be said. Every
 * ungrouped model version is in the same list, because a single-model save is
 * still an edit and belongs in the log; it just has no message.
 */
import type { CodeHistoryEntry } from "./types";

/** Whether this entry groups several transforms under one reason. */
export function isChangeSet(entry: CodeHistoryEntry): boolean {
  return entry.kind === "change_set";
}

/**
 * What the row says about size.
 *
 * **A change set of one is still a change set** and says so, because the
 * distinction it carries is *"somebody meant these together"* rather than
 * *"there were several"*. Collapsing a one-model change set into a plain
 * version would hide the message its author wrote.
 */
export function scopeLabel(entry: CodeHistoryEntry): string {
  if (!isChangeSet(entry)) {
    return entry.version_number ? `v${entry.version_number}` : "one version";
  }
  return `${entry.model_count} transform${entry.model_count === 1 ? "" : "s"}`;
}

/** Who and when, in one line, or what can be said of it.
 *
 * An author is optional in the data — `created_by` is nullable, because a
 * version can be written by the platform rather than by a person (a publish
 * from a schedule, most obviously). "unknown" would be wrong about that;
 * "the platform" is what actually happened. */
export function attribution(entry: CodeHistoryEntry): string {
  return entry.created_by_email ?? "the platform";
}

// **There is no `newestFirst` here, and that is deliberate** (§264, §213).
// The obvious one to write: the endpoint runs two queries — change sets and
// ungrouped versions — and concatenates them, so a merged list looks like it
// needs sorting. It does not. `services/code.py` ends with
// `entries.sort(key=..., reverse=True)` before it truncates to the limit, so a
// browser-side sort could never change the order of anything it was given.
//
// It was written, tested, and removed on reading the endpoint it describes:
// §213's question is whether another layer already makes the promise, and here
// it does. A re-sort would also have been *wrong* to keep for a second reason —
// the server sorts **before** applying `LIMIT`, so re-ordering a truncated page
// client-side cannot recover anything the truncation dropped, and would quietly
// imply it had.

/** What an empty history means, which is not "nothing happened".
 *
 * A project whose transforms have never been saved has no history; so does a
 * project with no transforms. Only the second is a reason to go somewhere
 * else, and the reader is the one who knows which they are looking at. */
export function emptyNote(modelCount: number): string {
  return modelCount === 0
    ? "No transforms in this project yet, so nothing has changed."
    : "No saved changes yet. Editing a transform writes a version here.";
}
