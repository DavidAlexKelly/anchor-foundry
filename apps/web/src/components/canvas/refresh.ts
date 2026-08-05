/** What a write inside a canvas app invalidates.
 *
 * **By prefix, not by a list of keys.** The list used to be four names spelled
 * out at each call site, and it had already drifted: the object table's key
 * (`canvas-object-table`) was not among them, so running an action left the
 * table showing the value it had just replaced — the action form had the same
 * gap, and item 1.3's `run_action` inherited it verbatim.
 *
 * A hand-kept list of "every widget that reads object data" is a second copy
 * of a fact, and the widget added next is the one that gets left out of it.
 * Every canvas read is keyed `canvas-*` by convention, so this asks for that
 * convention instead. Over-invalidating a few option lists after a write is
 * not a cost worth a stale table.
 */
import type { QueryClient } from "@tanstack/react-query";

export const CANVAS_KEY_PREFIX = "canvas-";

export function invalidateCanvasReads(queryClient: QueryClient): Promise<void> {
  return queryClient.invalidateQueries({
    predicate: (query) => String(query.queryKey[0] ?? "").startsWith(CANVAS_KEY_PREFIX),
  });
}
