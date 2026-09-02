/** One page ordering, and the one place the browser says which properties can
 * carry one.
 *
 * Four widgets want the same control and each had its own answer before this
 * existed: the Object Table's p.223 default sorts (§225, a free-text property
 * box), the Object Dropdown's and Object Selector's p.458 "Sort items by" and
 * the Loop layout's p.132 property sorts (all three a disabled hint saying the
 * platform could not do it). §225 wrote the argument for this file and left the
 * file unwritten:
 *
 * > "**The property is typed, not picked.** §222's Timeline made the same call
 * > for its date property: a picker over the ontology's orderable properties is
 * > one decision for every widget that wants one — the Timeline, the Object
 * > Dropdown's p.458 sort, this — and building it three times privately is how
 * > three widgets end up disagreeing about which properties are offered."
 *
 * ---
 *
 * **The division of labour, unchanged from §221 and §225.** The *server* owns
 * what is legal and refuses in a sentence naming the property. This module owns
 * what an author can *write* — it parses and edits a sort without consulting an
 * ontology, because a settings panel edits a document and a document can name a
 * property that has since been deleted. The *panel* owns what is offered, and
 * that is where `orderableProperties` is used: a picker listing a `string`
 * property would be offering a setting that can only ever produce a refusal.
 *
 * The three answers are different on purpose. Filtering the picker is not a
 * second validation — it is the panel declining to suggest something it knows
 * will fail, which is §214's rule, and it does not make the server's refusal
 * redundant because a document can arrive from anywhere.
 */

/** The declared property types both stores order identically.
 *
 * **Mirrors `object_sets.ORDERABLE_TYPES`, and the mirror is the point of this
 * file.** Before it, the constraint was typed out in four panels and named in
 * six comments, so §226 could build numeric aggregations and §221 could build
 * property sorts without a single one of them noticing — which is what
 * `STATUS.md` §230 found and this module exists to stop happening again.
 *
 * `string` is absent **permanently, not pending** (decision 0006 §2):
 * lexicographic order is the database collation on Postgres and byte order on
 * OpenSearch, so `'Z' < 'a'` is true in one and false in the other. A text sort
 * is the invisible kind of wrong — the same list, in a different order, on two
 * deployments of the same module.
 */
export const ORDERABLE_TYPES: readonly string[] = ["integer", "float", "date", "timestamp"];

/** What a panel says beneath a property sort picker.
 *
 * One sentence in one place, for the reason the type list is: the four panels
 * that show it would otherwise drift, and the sentence is a *claim about the
 * platform* rather than about the widget — which is exactly the kind that goes
 * stale without anything failing.
 */
export const ORDERABLE_HINT =
  "Integer, float, date and timestamp properties — the ones both stores order "
  + "identically. Text is refused permanently, not pending.";

/** The four orderings that need no declared property type behind them.
 *
 * Mirrors `object_sets.SORTS`. They are the primary key, which is text on both
 * stores, and `updated_at`, which is a real timestamp on one and an indexed
 * date on the other — so both stores order them identically without knowing any
 * property's type.
 */
export const FIXED_SORTS: Record<string, string> = {
  recent: "Last changed, newest first",
  oldest: "Last changed, oldest first",
  key: "Key, A–Z",
  "-key": "Key, Z–A",
};

/** A declared property, as every ontology read in the browser returns one. */
export interface Property {
  api_name: string;
  display_name?: string | null;
  data_type?: string | null;
}

/** Whether a page may be ordered by this property.
 *
 * **A missing `data_type` is not orderable**, which is the opposite of what
 * `isSearchable` does with one, and the asymmetry is deliberate: a search that
 * runs over a property it should not have costs a few irrelevant matches, and
 * an ordering that does costs a page in an order the two stores disagree about.
 * Absence is a refusal here for the same reason it is on the server (§221):
 * a caller that does not know a property's type has not checked it.
 */
export function isOrderable(property: Property): boolean {
  return ORDERABLE_TYPES.includes(property.data_type ?? "");
}

/** The properties a panel may offer as a sort, in the order the type declares
 * them. */
export function orderableProperties(all: readonly Property[]): Property[] {
  return all.filter(isOrderable);
}

export interface Entry {
  /** The sort as the server reads it: a fixed key, or `prop` / `-prop`. */
  key: string;
  /** The property name, or `""` for one of the four fixed sorts. */
  property: string;
  descending: boolean;
  /** True for the four fixed sorts, which have no property and no direction
   * control of their own — `-key` *is* the descending one. */
  fixed: boolean;
}

/** One written sort, read. `null` for anything that names no ordering. */
export function entryOf(raw: unknown): Entry | null {
  const value = typeof raw === "string" ? raw.trim() : "";
  if (!value) return null;
  if (Object.hasOwn(FIXED_SORTS, value)) {
    return { key: value, property: "", descending: value.startsWith("-"), fixed: true };
  }
  const descending = value.startsWith("-");
  const property = descending ? value.slice(1).trim() : value;
  // A bare `-` is a direction with nothing to apply it to. Dropped rather than
  // sent, because the server would refuse it as an unknown sort and the author
  // would read a sentence about property types for what is a blank field.
  if (!property) return null;
  return { key: `${descending ? "-" : ""}${property}`, property, descending, fixed: false };
}

/** A sort's direction changed, keeping everything else about it. */
export function withDirection(entry: Entry, descending: boolean): Entry {
  if (entry.fixed) return entry;
  return {
    ...entry,
    descending,
    key: `${descending ? "-" : ""}${entry.property}`,
  };
}

/** A sort's property changed. Blank leaves the entry in place with no key, so
 * a half-typed row does not vanish from under the author mid-keystroke —
 * §203's rule about a field that clears itself between `1` and `1.5`. */
export function withProperty(entry: Entry, property: string): Entry {
  const name = property.trim();
  return {
    key: name ? `${entry.descending ? "-" : ""}${name}` : "",
    property: name,
    descending: entry.descending,
    fixed: false,
  };
}

/** An entry switched between one of the four fixed sorts and a property. */
export function withFixed(entry: Entry, key: string): Entry {
  if (!Object.hasOwn(FIXED_SORTS, key)) {
    return { key: "", property: "", descending: entry.descending, fixed: false };
  }
  return { key, property: "", descending: key.startsWith("-"), fixed: true };
}

/** A blank row to add, defaulting to a property sort — the fixed four are one
 * click away and are not what an author reaches for a *second* sort. */
export function blankEntry(): Entry {
  return { key: "", property: "", descending: false, fixed: false };
}

/** What to call a sort, for a row's summary. */
export function labelOf(entry: Entry): string {
  if (entry.fixed) return FIXED_SORTS[entry.key] ?? entry.key;
  if (!entry.property) return "No property yet";
  return `${entry.property} ${entry.descending ? "(Z–A / high to low)" : "(A–Z / low to high)"}`;
}

/** One sort as a widget should *send* it, given what the ontology declares.
 *
 * **This is the one place a stale document is read back to something safe**, and
 * it is a different question from what the panel offers. A module saved when
 * `capacity` was an integer, opened after somebody retyped it to text, holds a
 * sort the server now refuses — and a widget whose whole job is a small control
 * (a dropdown, a looped list) would show a load error where a list should be.
 *
 * §214's rule: read a value the document holds but the platform refuses back to
 * the default, rather than sending it on. The **Object Table is deliberately not
 * a caller** — it renders a big region, its refusal is legible, and p.223's
 * setting is a list whose silent collapse to one default would be a worse lie
 * than an error.
 *
 * **A fixed sort needs no ontology, and that is what keeps the common case to
 * one fetch.** The four fixed keys are checked before `declared` is looked at,
 * so a widget with the default setting — which is every widget nobody has
 * configured — asks for its page once. Only a *property* sort has to wait, and
 * `undefined` is what it waits with: no sort at all, rather than the default,
 * because committing to the default would order the first page one way and the
 * second another and call it paging.
 *
 * The wait is usually not a wait. The type query is keyed `["object-type", id]`
 * and every panel and widget on the page shares it, so a second widget over the
 * same set reads it from cache and renders sorted on the first pass. A cold
 * cache costs one extra evaluation of the set.
 */
export function requestSort(
  raw: unknown,
  declared: readonly Property[] | undefined,
  fallback: string,
): string | undefined {
  const entry = entryOf(raw);
  if (!entry) return fallback;
  if (entry.fixed) return entry.key;
  if (declared === undefined) return undefined;
  return orderableProperties(declared).some((p) => p.api_name === entry.property)
    ? entry.key
    : fallback;
}
