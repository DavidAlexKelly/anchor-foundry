/**
 * Marking the part of a search result that matched (Foundry `ontology-manager`
 * p.28: "the search results highlight the specific field that matched your
 * query").
 *
 * **Its own module because it is pure**, which is the boundary
 * `apps/web/src/components/canvas/pure.ts` draws and the reason applies here:
 * a rule about *where the mark lands* is worth a test that can make it fail,
 * and vitest in this repo runs pure `.ts` only.
 *
 * The value being marked is the one the **server** said matched. This never
 * decides whether a row matched — only where inside the string the query sits.
 */

/** The matched value split into plain runs and one marked run. */
export function highlight(value: string, query: string): (string | { mark: string })[] {
  const needle = query.trim();
  if (!needle) return [value];
  // Case-insensitive, but the slice comes out of `value` — the mark has to
  // land on what is there, not on what was typed. Rewriting "Status" as
  // "status" would be editing the answer.
  const at = value.toLowerCase().indexOf(needle.toLowerCase());
  if (at < 0) {
    // Reachable, and correct: the server matched some *other* field of the
    // same row and this is drawing that one. Marking nothing beats marking
    // the whole string.
    return [value];
  }
  return [
    value.slice(0, at),
    { mark: value.slice(at, at + needle.length) },
    value.slice(at + needle.length),
  ].filter((part) => part !== "");
}
