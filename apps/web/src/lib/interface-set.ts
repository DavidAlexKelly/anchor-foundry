/**
 * Reading an interface's objects, browser side (Foundry `ontology` p.61).
 *
 * §254 built the read: `POST /interfaces/{id}/evaluate` returns every object of
 * every implementing type, filtered in the interface's vocabulary and keyed by
 * it. This is what a screen has to say about the answer, and it is three
 * things the raw response does not say in words.
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

/** The implementing types this read did not consult, in the listing's order.
 *
 * **A different fact from "matched nothing", and worth its own sentence.** A
 * filter on an optional property a type answers nothing to means no object of
 * that type can match, so §254 skips it — and an empty result then has two
 * possible readings that a person acting on it needs told apart. Reporting
 * only the count would leave "Facility has no inspections due" and "Facility
 * does not record inspection status" looking identical.
 */
export function notConsulted(all: string[], read: string[]): string[] {
  const seen = new Set(read);
  return all.filter((name) => !seen.has(name));
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
