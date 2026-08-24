/** p.133's loop over an array: turning a variable's value into copies.
 *
 * > "Loop layouts iterate through each entry in the array, and each entry is
 * > displayed as an instance of the embedded module configured in the Module
 * > selection step. **Modules are ordered by the entry's position in the
 * > array.** Inserting, re-ordering, and deleting entries from the array will
 * > be reflected in the looped layout." (p.133)
 *
 * The object-set arm of the same widget goes through `useSetPage`, because the
 * rows live on the server and arrive a page at a time. An array does not: its
 * value is already resolved and in memory, so paging is a slice and the whole
 * of it is arithmetic — which is why it is here rather than in the component.
 *
 * **Position is the identity.** p.133 says the copies are ordered by position
 * and that re-ordering is reflected, so the index is the key. Keying by the
 * *value* would look more stable and is wrong: an array may hold the same
 * entry twice ("Alice", "Bob", "Alice"), and two copies sharing a key is a
 * React tree that renders one of them. The cost is that re-ordering hands copy
 * 0 a new value rather than moving it, which is what "ordered by position"
 * describes.
 */

/** The entries a resolved variable value contributes.
 *
 * Anything that is not an array becomes none. That covers a variable the
 * server has not resolved yet (`undefined`), one whose value is genuinely null,
 * and a document whose `array` variable is holding something else — all three
 * mean "no copies", and none of them should throw in a render.
 */
export function arrayEntries(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export interface LoopPaging {
  paging: "limit" | "paged";
  /** p.134's "Max items to display", used by `limit`. */
  maxItems: number;
  /** p.134's "Max items per page", used by `paged`. */
  pageSize: number;
  /** Which page `paged` is showing, from zero. Ignored by `limit`. */
  page?: number;
}

export interface LoopPage {
  /** The entries to render, paired with their **position in the whole array**
   * rather than in this page — the key has to be stable across paging, and an
   * index into a slice is not. */
  rows: { index: number; value: unknown }[];
  /** How many pages there are, at least 1 so a control never reads "page 1 of
   * 0" on an empty array. */
  pageCount: number;
}

/** p.134's two paging styles, over entries already in memory.
 *
 * > "**Limit**: This paging style will display only a single page which
 * > displays up to the first X objects or array entries… **Paged**: This paging
 * > style will display pages of objects or array entries of size X." (p.134)
 *
 * `limit` is not `paged` with one page: it is one page *of at most X*, with the
 * rest of the array simply not shown. Conflating them would give a Limit loop
 * pagination controls for entries it is documented not to display.
 */
export function pageOf(entries: readonly unknown[], options: LoopPaging): LoopPage {
  const withIndex = entries.map((value, index) => ({ index, value }));
  if (options.paging === "limit") {
    const cap = Math.max(1, Math.floor(options.maxItems));
    return { rows: withIndex.slice(0, cap), pageCount: 1 };
  }
  const size = Math.max(1, Math.floor(options.pageSize));
  const pageCount = Math.max(1, Math.ceil(withIndex.length / size));
  // Clamped rather than trusted: an author can shrink the array under a reader
  // who is on the last page, and an out-of-range slice would show nothing with
  // no way back.
  const current = Math.min(Math.max(0, Math.floor(options.page ?? 0)), pageCount - 1);
  return {
    rows: withIndex.slice(current * size, current * size + size),
    pageCount,
  };
}
