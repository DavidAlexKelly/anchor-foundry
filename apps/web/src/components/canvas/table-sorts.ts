/** p.223's **Default sort(s)** for the Object Table.
 *
 * > "Default sort(s): This setting allows one or more default sorts to be
 * > applied to the table. Module builders can sort on both visible property
 * > types shown within the table or hidden property types not displayed. If no
 * > sort is applied, the data is not sorted." (p.223)
 *
 * ---
 *
 * **The setting is a list, and the order of the list is the setting.** "By
 * status, then by date" and "by date, then by status" are different tables, so
 * everything here preserves position — nothing sorts, dedupes by value, or
 * normalises the order of what an author wrote.
 *
 * **A stored `sort` is a string**, because that is what every module saved
 * before this existed holds, and decision 0002 says a document does not change
 * when you open it. So a string is read as a one-entry list and written back as
 * a one-entry list; the migration is that there isn't one.
 *
 * **What the server will accept is not this module's business.** It refuses a
 * property whose declared type has no order both stores agree on, and the
 * refusal is a sentence naming the property — so this module offers what an
 * author can *write* and lets the server say what is *legal*, which is the same
 * division §214's sort refusal and §221's `property_types` argument draw.
 */

/** The four orderings that need no declared property type behind them.
 *
 * Mirrors `object_sets.SORTS`. They are the primary key, which is text on both
 * stores, and `updated_at`, which is a real timestamp on one and an indexed
 * date on the other — so both stores order them identically without knowing
 * any property's type.
 */
export const FIXED_SORTS: Record<string, string> = {
  recent: "Last changed, newest first",
  oldest: "Last changed, oldest first",
  key: "Key, A–Z",
  "-key": "Key, Z–A",
};

/** What the Object Table has always sorted by when nothing says otherwise. */
export const DEFAULT_SORT = "recent";

/** p.223's cap is ours, not Foundry's — it mirrors `object_sets.MAX_SORTS`, and
 * a panel that let an author add a seventh row would be offering something the
 * server refuses. */
export const MAX_SORTS = 6;

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

/** One written sort, read. */
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

/** The whole setting — **the rows the panel shows** — from what a document holds.
 *
 * Takes the string a pre-p.223 module stored, the list a new one stores, and
 * nothing.
 *
 * **A string and an array mean subtly different things, and the difference is
 * the blank.** A string is one stored ordering, so a blank one is *no* sort. An
 * array is the panel's row list, so a blank member is a row the author has
 * added and not yet filled in — dropping it would delete the row on the
 * keystroke that emptied it, which is §203's field that clears itself between
 * `1` and `1.5`. `toRequest` is what refuses to send a half-written row; this
 * function is what keeps it on screen.
 *
 * **Repeats are dropped here rather than refused**, which is the opposite of
 * what the server does and is deliberate: the server is validating a request an
 * author cannot see, so it owes them a sentence; a settings panel has the rows
 * on screen, and the honest thing there is to stop the second one being sent.
 * Over the cap, the extra entries are dropped for the same reason — the panel
 * does not offer a seventh row, so a document holding one came from elsewhere.
 */
export function sortsOf(raw: unknown): Entry[] {
  if (typeof raw === "string") {
    const one = entryOf(raw);
    return one ? [one] : [];
  }
  if (!Array.isArray(raw)) return [];
  const out: Entry[] = [];
  const seen = new Set<string>();
  for (const item of raw) {
    if (out.length >= MAX_SORTS) break;
    const entry = entryOf(item) ?? blankEntry();
    // A blank row is kept but never counted as a repeat: several unfinished
    // rows are a normal moment in editing, not a duplicate setting.
    if (entry.key && seen.has(entry.key)) continue;
    if (entry.key) seen.add(entry.key);
    out.push(entry);
  }
  return out;
}

/** What to send, from what the panel holds.
 *
 * `undefined` when there is nothing to say, so the request carries no `sort`
 * key at all and the server applies its default — rather than `[]`, which would
 * be an author asking for an ordering they did not ask for.
 */
export function toRequest(entries: Entry[]): string | string[] | undefined {
  const keys = entries.map((e) => e.key).filter(Boolean);
  if (keys.length === 0) return undefined;
  // One sort goes as a string: it is what the API took before p.223 and what
  // every other caller in the browser sends, so a table with one ordering
  // produces the request it always produced.
  return keys.length === 1 ? keys[0] : keys;
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
