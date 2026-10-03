/** A version's transaction type and the views they make (§747; Foundry
 *  `data-integration` p.22-26; db 0144).
 *
 *  > "A dataset view represents the effective file contents of a dataset for a
 *  > branch at a point in time." (p.26)
 *
 *  Every version here is stored whole, so any of them can be read on its own
 *  (time travel needs nothing from this). What the type adds is how a version
 *  relates to the one before, and so which versions are one view: p.26's
 *  rule, that "a new view only begins at a SNAPSHOT transaction".
 */
import type { TransactionType } from "./types";

/** p.22-23's meanings, as they are true of a version here. */
export const TRANSACTION_MEANING: Record<TransactionType, string> = {
  SNAPSHOT: "A new view: everything the dataset holds was written by this version.",
  APPEND: "Rows added to the view before it; no row of that view changed.",
  UPDATE: "The view before it with rows added, changed or removed.",
};

interface Versioned {
  version_number: number;
  transaction_type: TransactionType;
}

/** The versions that begin a view, oldest first. p.26: "The view at a given
 *  time begins at the latest SNAPSHOT transaction before that point in time.
 *  If there is no SNAPSHOT transaction present, then take the earliest
 *  transaction for the dataset instead." */
export function viewStarts(versions: readonly Versioned[]): number[] {
  const ordered = [...versions].sort((a, b) => a.version_number - b.version_number);
  const starts = ordered
    .filter((v, i) => v.transaction_type === "SNAPSHOT" || i === 0)
    .map((v) => v.version_number);
  return starts;
}

/** Where the view a version belongs to begins. */
export function viewOf(versions: readonly Versioned[], versionNumber: number): number | null {
  const starts = viewStarts(versions).filter((s) => s <= versionNumber);
  return starts.length ? starts[starts.length - 1]! : null;
}

/** One line on the History tab saying what the current view is. */
export function currentViewText(versions: readonly Versioned[]): string {
  const starts = viewStarts(versions);
  const newest = Math.max(...versions.map((v) => v.version_number));
  const from = starts[starts.length - 1];
  if (from === undefined) return "";
  const views = starts.length === 1 ? "one view" : `${starts.length} views`;
  const span = from === newest ? `is v${from} alone` : `runs from v${from} to v${newest}`;
  return `This dataset has ${views}. The current one ${span}.`;
}
