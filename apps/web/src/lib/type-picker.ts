/**
 * Choosing one object type from a workspace that may hold hundreds.
 *
 * **This exists because §256 bounded the listing.** `GET /object-types` had no
 * `LIMIT` and eight call sites, seven of them dropdowns; §209 measured a
 * development workspace of ~1,400 types taking seven seconds to open a dialog.
 * Adding a `LIMIT` on its own would have replaced a slow picker with a *lying*
 * one — fifty of six hundred types, indistinguishable from a workspace with
 * fifty. So the endpoint pages and searches, and this is the half that decides
 * what a picker shows and what it says about what it is not showing.
 *
 * The rules, and each is a way of not lying:
 *
 * * a picker searches the **server**, not its own page, once there is more
 *   than a page (`needsSearch`) — filtering fifty rows in the browser answers
 *   the wrong question;
 * * it says how many it is not showing (`truncationNote`), because a list that
 *   stops has to say so;
 * * and the type a caller **already chose** is always on the list
 *   (`withSelected`), whatever the search says — a control whose current value
 *   is missing from its own options silently changes that value on the next
 *   save, which is the failure §175 found in a status dropdown.
 */

/** What this module needs of an object type, which is a name and an identity.
 *
 * **Narrower than {@link ObjectTypeSummary} on purpose**: the picker's chosen
 * type is fetched by `getType`, which returns a *detail*, and the two models
 * agree on exactly the two fields an option is drawn from. Typing this by what
 * is used rather than by where it came from is what lets both through without
 * a cast that would also let anything through. */
export interface PickableType {
  id: string;
  display_name: string;
}

/** `ontology.DEFAULT_TYPE_PAGE`, restated.
 *
 * A picker cannot wait for a round trip to decide whether to draw a search
 * box, and it needs the same number the server pages by to say how many it is
 * hiding. An API test reads this back out of the file (§190). */
export const TYPE_PAGE = 50;

/** Whether this picker needs a search box.
 *
 * **Decided by the total, not by the page.** A workspace with exactly fifty
 * types fits, and one with fifty-one does not — and the page looks identical
 * in both cases, which is precisely why the browser is told the count.
 *
 * **`query` is why this takes two arguments**, and it is a bug found by a
 * browser test rather than reasoned out. The total a picker holds is the total
 * *matching the current search* — so a search that narrows 791 types to one
 * makes `total > TYPE_PAGE` false and takes the search box off the screen,
 * mid-word, with the query still applied. The control removes itself and
 * leaves the list it narrowed. §246 found the same shape in a dialog whose
 * *Add field* button moved under the pointer when the table above it
 * collapsed: a control that disappears as a consequence of being used is worse
 * than one that was never there.
 */
export function needsSearch(total: number, query = ""): boolean {
  return total > TYPE_PAGE || query.trim().length > 0;
}

/** What a picker says about the types it is not showing, or null.
 *
 * A sentence rather than a count on its own: "50 of 613" is a fact, and
 * "search to narrow it" is what somebody can do about it. */
export function truncationNote(shown: number, total: number): string | null {
  if (shown >= total) return null;
  return `Showing ${shown} of ${total} — type to search the rest.`;
}

/** The options to draw: the page, with the already-chosen type put back if the
 * search dropped it.
 *
 * **The invariant this protects is that a select's value is always among its
 * options.** A picker whose current type is missing renders as blank, and the
 * next save writes the blank — the type is silently changed by a search
 * somebody typed and then cleared. §175 found exactly this in a status
 * dropdown and fixed it the same way.
 *
 * `selected` is the full summary rather than an id because the option needs a
 * label, and the page it came from may no longer contain it.
 */
export function withSelected<T extends PickableType>(
  page: T[],
  selected: T | null | undefined,
): T[] {
  if (!selected) return page;
  if (page.some((t) => t.id === selected.id)) return page;
  return [selected, ...page];
}

/** Whether a search has narrowed to nothing, as a sentence.
 *
 * Distinguished from an empty workspace, because they are different problems
 * with different next steps: one is "try a different word", the other is
 * "declare an object type first". */
export function emptyNote(total: number, query: string): string {
  return query.trim()
    ? `Nothing matches “${query.trim()}”.`
    : "No object types yet — declare one first.";
}
