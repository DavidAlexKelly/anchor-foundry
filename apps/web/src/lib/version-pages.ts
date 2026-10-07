/** Paging a version history newest first (models and canvas apps).
 *
 * The API returns `VERSION_PAGE` versions per request and takes `before`, the
 * oldest version number the caller already holds. A page shorter than that is
 * the last one. A full page may also be the last; asking once more then
 * returns an empty page, which also ends the list. */

/** The API's default page (`VERSION_PAGE` in the model and canvas services). */
export const VERSION_PAGE = 50;

/** The query string for a page: none for the first page. */
export function pageQuery(before?: number): string {
  return before === undefined ? "" : `?before=${before}`;
}

/** What to ask for after `page`, or `undefined` when it was the last. */
export function nextBefore(page: { version_number: number }[]): number | undefined {
  if (page.length < VERSION_PAGE) return undefined;
  return page[page.length - 1]?.version_number;
}
