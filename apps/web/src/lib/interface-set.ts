/**
 * Reading an interface's objects, browser side (Foundry `ontology` p.61).
 *
 * §254 built the read: `POST /interfaces/{id}/evaluate` returns every object of
 * every implementing type, filtered in the interface's vocabulary and keyed by
 * it. This is what a screen has to say about the answer in words the response
 * does not carry.
 *
 * **Which types a filter skipped is not here, and that is deliberate.** It was,
 * briefly — as a subtraction of the types that were read from the types that
 * implement the interface — and the browser does not have the second list: a
 * listing row carries an implementation *count* and no names. A function whose
 * input its only caller cannot supply is a function that cannot work, so the
 * server sends `skipped` and this does not compute it (§213).
 *
 * The division is the usual one — the server owns what is **legal**, this owns
 * what is **offered and said** — and it matters most for paging. An interface
 * set is bounded at one store page, because the merge needs `offset + limit`
 * rows from every implementing type and both stores clamp a read to that. The
 * server refuses past it in a sentence; a Next button that produced that
 * sentence would be §214's control that cannot work, so {@link canPage} knows
 * the same ceiling and stops offering.
 */

/** `interface_sets.MAX_DEPTH`, restated.
 *
 * A ceiling rather than a policy, and the reason is in the server module: both
 * instance stores clamp a read to their page size, so a merge that asked one
 * type for more would silently drop real members off the end of the order.
 * Restated here rather than fetched because a Next button cannot wait for a
 * round trip to decide whether to be disabled. */
export const MAX_DEPTH = 50;

/** What this page of objects *is*, in one sentence.
 *
 * p.61's argument made readable: the point of `Inspectable` is that Vehicle,
 * Equipment and Facility answer one question together, so the count alone is
 * the less interesting half of the answer. Naming the types is the half that
 * says an interface did something.
 */
export function readSummary(total: number, objectTypes: string[]): string {
  const objects = `${total} object${total === 1 ? "" : "s"}`;
  if (objectTypes.length === 0) return objects;
  if (objectTypes.length === 1) return `${objects} in ${objectTypes[0]}`;
  const last = objectTypes[objectTypes.length - 1];
  return `${objects} across ${objectTypes.slice(0, -1).join(", ")} and ${last}`;
}

/** Whether a previous and a next page exist *and* can be served.
 *
 * `next` is false at the ceiling even when more objects match, because the
 * server refuses past it — and it is better for the button to be absent than
 * for it to produce a refusal. {@link depthNote} is what says so, since a
 * button that quietly stops being there is its own kind of confusing.
 */
export function canPage(
  offset: number, limit: number, total: number,
): { previous: boolean; next: boolean } {
  return {
    previous: offset > 0,
    next: offset + limit < total && offset + limit + limit <= MAX_DEPTH,
  };
}

/** Why there is no next page despite more matches, or null when there is one
 * (or when nothing is being hidden). */
export function depthNote(
  offset: number, limit: number, total: number,
): string | null {
  if (offset + limit >= total) return null;
  if (canPage(offset, limit, total).next) return null;
  return (
    `Showing the first ${MAX_DEPTH} of ${total} — an interface set reads ` +
    "across every implementing type at once, so it pages this far. Narrow it " +
    "with a filter."
  );
}
