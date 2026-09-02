/** p.455-458's Object Dropdown: "used to select a single object from a list of
 * objects".
 *
 * > "**Label**: Set an optional label… **Input object set**: This input variable
 * > determines the data that will be displayed in the widget… **Selected
 * > object**: This is an output variable for the widget that outputs a single
 * > object set of the currently selected object… **Allow no selection**: If
 * > enabled, the widget will be allowed to have no object selected." (p.457)
 *
 * > "**Hide null properties**: If enabled, null properties will be hidden on a
 * > per object basis within the list. **Sort items by**… **Search items by**:
 * > Specify which object properties search is performed on. **On-screen
 * > properties**: If enabled, search will be performed on all string properties
 * > that are displayed in the dropdown widget. **Specific properties**: … on the
 * > specified string properties. **All searchable properties**: … on all
 * > searchable properties in the object set." (p.458)
 *
 * ---
 *
 * **Most of this widget is other widgets.** The output is the Object Table's
 * selection clauses (`object-table-selection.ts`), and "allow no selection"
 * off is its auto-selection with the sign flipped — p.457's setting and p.224's
 * are the same question about the same variable shape. Which properties appear
 * under each title, and which of them a null hides, is the Property List's
 * `visibleProperties`, applied once per row instead of once. What is left here
 * is the part p.458 introduces and nothing else has: **which properties a
 * search runs on**, and what matching one means.
 *
 * ---
 *
 * **The Object Selector shares this file** (p.444: "Allow the user to select
 * multiple objects from a list of objects" — one line, and no page of its own).
 * Every setting it has is one of these, so a second module would be a second
 * place for p.458's search rules to drift; the only thing the two do not share
 * is how a selection of several reads back, which is `selectionSummary` at the
 * bottom.
 */

import { orderableProperties, requestSort } from "./property-sort";
import type { Property } from "./property-sort";

/** How many objects the dropdown loads.
 *
 * **Search happens within these**, which is the one place this widget is
 * narrower than p.458: "all searchable properties in the object set" means the
 * whole set, and matching several properties at once is an *or* the object-set
 * language has no way to say — every clause it takes is an `and`. A picker over
 * a bounded page is the honest version, so the widget says when it has
 * truncated rather than quietly searching a prefix of the answer.
 */
export const PAGE_LIMIT = 200;

/** One declared property. Defined in `property-sort.ts` and re-exported here
 * rather than restated: this file had its own copy, and a second declaration of
 * the same three fields is how `data_type` ends up optional in one place and
 * required in another. */
export type { Property } from "./property-sort";

/** p.458's "Sort items by": "Specify the order in which objects are sorted in
 * the dropdown widget."
 *
 * **A property picker as of §231, and the note saying it could not be one had
 * outlived its reason by ten units.** It read "not a property picker, and that
 * is decision 0006 rather than a shortcut" — true when §214 wrote it, and
 * untrue from §221, which built property sorts on both stores for every
 * declared type the two order identically. `STATUS.md` §230 found six copies of
 * that sentence across this codebase; this was one, and `property-sort.ts` now
 * holds the single answer all of them were guessing at.
 *
 * p.458's second clause — "if multiple object types exist in the object set,
 * only shared properties can be sorted on" — is satisfied by construction here:
 * an object set in this platform is over one object type, so every declared
 * property is a shared one.
 *
 * **The default is the key, not `recent`.** A picker's list has to be in an
 * order a person can predict; "whichever rows were touched last" is not one,
 * and on a freshly synced type every row shares an instant, so the order would
 * be arbitrary and would change under a viewer for no visible reason.
 */
export const SORTS: Record<string, string> = {
  key: "Primary key (A–Z)",
  "-key": "Primary key (Z–A)",
  recent: "Recently updated first",
  oldest: "Oldest first",
};

export const DEFAULT_SORT = "key";

/** What to send, given what the object type declares.
 *
 * **The fallback matters more in a picker than in a table**, which is why this
 * goes through `requestSort` and the Object Table does not. A dropdown is a
 * small control: a load error where its list should be is easy to miss and
 * impossible to act on from the viewer's side, so a sort naming a property the
 * ontology no longer orders reads back to the key rather than being sent on.
 * §214's rule, at the widget §214 wrote it for.
 *
 * `undefined` while the ontology is still resolving — see `requestSort`.
 */
export function sortOf(raw: unknown, declared?: readonly Property[]): string | undefined {
  if (typeof raw === "string" && Object.hasOwn(SORTS, raw)) return raw;
  return requestSort(raw, declared, DEFAULT_SORT);
}

/** The properties p.458's picker offers, which is narrower than the list the
 * search modes use: a search runs on text and an ordering cannot. */
export function sortableProperties(all: readonly Property[]): Property[] {
  return orderableProperties(all);
}

/** p.458's three Search items by modes. */
export const SEARCH_MODES: Record<string, string> = {
  on_screen: "On-screen properties",
  specific: "Specific properties",
  all: "All searchable properties",
};

export const DEFAULT_SEARCH_MODE = "on_screen";

export function searchModeOf(raw: unknown): string {
  return typeof raw === "string" && Object.hasOwn(SEARCH_MODES, raw)
    ? raw
    : DEFAULT_SEARCH_MODE;
}

/** p.457's Allow no selection.
 *
 * **Default off**, which is what makes the widget a dropdown rather than a
 * filter: p.457 offers the setting as a permission to be *without* a
 * selection, so the unconfigured widget picks the first object and every
 * downstream widget has something to read on load.
 */
export function allowNoSelectionOf(raw: unknown): boolean {
  return raw === true;
}

/** A comma-separated prop read as a list of names. */
export function propertyListOf(raw: unknown): string[] {
  return String(raw ?? "")
    .split(",")
    .map((name) => name.trim())
    .filter(Boolean);
}

/** p.457's optional Label, or nothing at all.
 *
 * A blank string is nothing, not an empty label: the difference is a row of
 * whitespace above the widget that no author asked for and none can see to
 * remove.
 */
export function labelOf(raw: unknown): string | null {
  const text = typeof raw === "string" ? raw.trim() : "";
  return text || null;
}

/** What p.458 means by a property search can run on.
 *
 * **String properties**, which p.458 says twice and is worth keeping: a search
 * box that silently matched nothing against a number column would look broken
 * rather than restricted.
 */
export function isSearchable(property: Property): boolean {
  return (property.data_type ?? "string") === "string";
}

export interface SearchScope {
  mode: unknown;
  /** Every property the object type declares. */
  all: readonly Property[];
  /** The api_names actually drawn in the list — the title and p.457's
   *  "Add property" lines, in that order. */
  shown: readonly string[];
  /** p.458's "the specified string properties", as the document holds them. */
  specific: unknown;
}

/** Which property names a search runs on.
 *
 * All three modes end at the same place — a list of names that exist on the
 * type and hold strings — and each gets there from somewhere different. The
 * filtering is not defensive tidying: a name that no longer exists, or one that
 * was configured before the property became a number, would otherwise make the
 * search box quietly match nothing and look like a broken widget rather than a
 * stale configuration.
 */
export function searchProperties({ mode, all, shown, specific }: SearchScope): string[] {
  const searchable = new Map(
    all.filter(isSearchable).map((p) => [p.api_name, p] as const),
  );
  const chosen = searchModeOf(mode) === "specific"
    ? propertyListOf(specific)
    : searchModeOf(mode) === "on_screen"
      ? [...shown]
      : all.map((p) => p.api_name);
  const out: string[] = [];
  for (const name of chosen) {
    if (searchable.has(name) && !out.includes(name)) out.push(name);
  }
  return out;
}

/** Whether one object answers what was typed.
 *
 * **Substring, case-insensitively, and not `starts_with`.** The Exploration
 * Search Bar writes a `starts_with` clause because it narrows a set on the
 * server and that is the operator the object-set language has; this is a
 * picker, and an object called "North West Depot" has to be findable by typing
 * "depot" or the search box is a worse way to find it than scrolling.
 *
 * A blank query matches everything — the box is empty far more often than it
 * is used, and a widget that showed nothing until somebody typed would be a
 * dropdown with no list.
 */
export function matchesQuery(
  values: Record<string, unknown> | undefined,
  query: unknown,
  properties: readonly string[],
): boolean {
  const needle = String(query ?? "").trim().toLowerCase();
  if (!needle) return true;
  if (!values) return false;
  return properties.some((name) => {
    const value = values[name];
    if (value === null || value === undefined) return false;
    return String(value).toLowerCase().includes(needle);
  });
}

/** What one option is called.
 *
 * The title property's value, and the primary key when there is not one — a
 * blank title is a real possibility on real data, and an option with no text
 * is one a viewer cannot pick on purpose.
 */
export function titleOf(
  values: Record<string, unknown> | undefined,
  titleProperty: string | null,
  primaryKey: string,
): string {
  if (!titleProperty || !values) return primaryKey;
  const value = values[titleProperty];
  if (value === null || value === undefined) return primaryKey;
  const text = String(value).trim();
  return text || primaryKey;
}

/** What the widget says when the set is larger than the page it loaded.
 *
 * Said rather than hidden, because the alternative is a search box that
 * answers about part of the set and looks like it answered about all of it.
 */
export function truncationNote(total: number | undefined, loaded: number): string | null {
  if (total === undefined || total <= loaded) return null;
  return `Showing the first ${loaded} of ${total.toLocaleString()} — narrow the object set to search the rest`;
}

/** What the Object Selector's closed control says (p.444's one line).
 *
 * **Three answers, and the middle one is the reason this is a function.** None
 * is a prompt; several is a count; *one* is the object's own title, because a
 * selector showing "1 selected" beside a list where the reader can see which
 * one would be withholding the answer to make the code simpler.
 *
 * The count is what a set of several reads as: naming them would run off the
 * control at four, and truncating a list of titles produces a label that
 * changes width every time somebody ticks a box.
 */
export function selectionSummary(count: number, onlyTitle: string | null): string {
  if (count <= 0) return "Select objects...";
  if (count === 1 && onlyTitle) return onlyTitle;
  return `${count} selected`;
}
