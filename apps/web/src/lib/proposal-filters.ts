/**
 * Filtering the Pull requests tab (§429; `code-repositories` p.18).
 *
 * > "You can switch between a list of open and closed Pull requests by
 * > clicking the 'Open' / 'Closed' button at the top of the pull requests
 * > list, and use the search bar to further filter the list based on title or
 * > author."
 *
 * **One sentence, two controls, and "further" is the word that joins them.**
 * The search narrows whichever bucket is showing; it does not search across
 * both. That is worth stating because the other reading is tempting and
 * wrong: a search box that quietly returned closed proposals while the Open
 * button was lit would make the button mean nothing.
 *
 * ---
 *
 * **The bucket is asked of the server and the search is not**, which is not an
 * inconsistency but the difference between the two questions. A bucket is
 * coarse and changes when somebody applies or withdraws something, so asking
 * for it keeps the list bounded — a project accumulates closed proposals
 * forever, and a tab that fetched all of them to show three open ones would
 * get slower every month. A search is a narrowing of what is already on
 * screen, and a round trip per keystroke is how a search box becomes a thing
 * people wait for.
 */
import type { CodeProposal } from "./types";

/** p.18's two buttons. Ours is a URL value as well as a control, so the list
 *  somebody is looking at is a link they can send. */
export const BUCKETS = ["open", "closed"] as const;
export type Bucket = (typeof BUCKETS)[number];
export const DEFAULT_BUCKET: Bucket = "open";

export const BUCKET_LABELS: Record<Bucket, string> = {
  open: "Open",
  closed: "Closed",
};

// A bucket is passed to the API as `?state=` unchanged, so there is no
// translation function here. One was written — `stateParam(bucket)`, returning
// its argument — and a mutation sweep can say nothing about a function that
// cannot be wrong (§223). The two vocabularies agreeing is a fact about the
// server, and `test_code_review.py` is where it is checked.

/**
 * Which bucket a proposal's state falls in.
 *
 * **Two buckets over three states** (db 0031: open, applied, withdrawn),
 * because how a proposal ended is a fact the review record keeps and Foundry's
 * two buttons have nowhere to put it. The bucket decides the list; the row
 * still says which ending it had.
 */
export function bucketOf(state: CodeProposal["state"]): Bucket {
  return state === "open" ? "open" : "closed";
}

/**
 * Whether one proposal answers a search.
 *
 * **Title or author, which is what p.18 names**, and nothing else. A search
 * that also matched the description would find proposals whose visible row
 * says nothing about the word that was typed — a result a reader cannot
 * account for is worse than one they did not get.
 *
 * The author is matched by the address the row shows. Matching a user id
 * would be matching something nobody can see or type.
 */
export function matches(proposal: CodeProposal, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (q === "") return true;
  if (proposal.summary.toLowerCase().includes(q)) return true;
  return (proposal.created_by_email ?? "").toLowerCase().includes(q);
}

/** The rows a search leaves, in the order they arrived (newest first). */
export function filtered(
  proposals: readonly CodeProposal[], query: string,
): CodeProposal[] {
  return proposals.filter((p) => matches(p, query));
}

/**
 * What the tab says when a search finds nothing here.
 *
 * **It names the query, and it says whether the other bucket has an answer.**
 * "No results" leaves a reader unable to tell a typo from a proposal that was
 * merged last week, and those want opposite next actions. `elsewhere` is how
 * many rows in the *other* bucket match the same words; when it is zero the
 * sentence stops rather than mentioning a place with nothing in it.
 *
 * `null` when there is nothing to say: either the search found something, or
 * the query is blank and the bucket's own empty state (which says where a
 * repository's proposals are, §276) is the better sentence.
 */
export function searchEmptyNote(
  query: string, found: number, elsewhere: number, bucket: Bucket,
): string | null {
  if (query.trim() === "" || found > 0) return null;
  const other = bucket === "open" ? "closed" : "open";
  const here = `Nothing ${bucket === "open" ? "open" : "closed"} matches “${query.trim()}”.`;
  if (elsewhere === 0) return here;
  return (
    `${here} ${elsewhere} ${other} proposal${elsewhere === 1 ? "" : "s"} ` +
    `match${elsewhere === 1 ? "es" : ""}.`
  );
}

/** The label on the button that switches to the other bucket's matches, or
 *  `null` when there is nothing there to switch to. */
export function switchLabel(elsewhere: number, bucket: Bucket): string | null {
  if (elsewhere === 0) return null;
  return `Search ${bucket === "open" ? "closed" : "open"} proposals`;
}
