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

/** What the server says of a dataset's whole history (§879). */
interface HistorySummary {
  views: number;
  view_start: number | null;
  newest: number | null;
}

/** One line on the History tab saying what the current view is. p.26: "The
 *  view at a given time begins at the latest SNAPSHOT transaction before that
 *  point in time. If there is no SNAPSHOT transaction present, then take the
 *  earliest transaction for the dataset instead."
 *
 *  **From the server's summary, not the rows on screen (§879).** The history
 *  is a page now, and the latest SNAPSHOT may be many pages back. */
export function currentViewText(summary: HistorySummary): string {
  const { views: count, view_start: from, newest } = summary;
  if (from === null || newest === null || count < 1) return "";
  const views = count === 1 ? "one view" : `${count} views`;
  const span = from === newest ? `is v${from} alone` : `runs from v${from} to v${newest}`;
  return `This dataset has ${views}. The current one ${span}.`;
}

/** Where the next, older page of the history starts, or undefined when this
 *  one reached the first version (§879). The server's `before` is exclusive,
 *  so the oldest number shown is the next page's bound. */
export function olderPage(page: { items: readonly { version_number: number }[] }): number | undefined {
  const oldest = page.items[page.items.length - 1];
  return oldest !== undefined && oldest.version_number > 1 ? oldest.version_number : undefined;
}
