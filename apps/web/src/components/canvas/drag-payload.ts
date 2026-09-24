/**
 * What a Workshop drag carries, and what a drop zone makes of it (`workshop`
 * p.55, p.564–570; §457).
 *
 * > "Sections can be configured as drop zones to receive drag payloads from
 * > other Workshop components… users can drag objects onto a section to
 * > populate variables or trigger events." (p.55)
 *
 * > "This drop zone accepts the Foundry object RID and the Foundry object set
 * > media type." (p.568)
 *
 * **Two media types, as Foundry has**, carried on the browser's own
 * `DataTransfer` under this platform's names. A drag zone says which it is by
 * which type it sets, and a drop zone reads whichever it finds — so the
 * contract between the two is these strings and these shapes, and nothing
 * else in either widget has to know the other exists.
 *
 * **Both carry keys, never a set definition.** p.274 says what an Object Set
 * Title drags: "the objects within the object set", and only while there are
 * "fewer than 500" of them. That limit only makes sense if the objects are
 * enumerated, and enumerating them is also what makes a drop expressible
 * here: a drop zone writes a clause list (the currency of every output in this
 * builder, p.224's and p.513's included), and a definition with a traversal in
 * it is not something a clause list can say.
 *
 * Pure, and deliberately: `DataTransfer` is a browser object a test cannot
 * build, so what is read from it is reduced here to a `getData`-shaped
 * function and everything that decides anything happens against plain values.
 */

import { PRIMARY_KEY, type Clause } from "./object-table-selection";

/** p.568's "Foundry object RID" media type: one object. */
export const OBJECT_MEDIA_TYPE = "application/x-anchor-object";
/** p.568's "Foundry object set" media type: several. */
export const OBJECT_SET_MEDIA_TYPE = "application/x-anchor-object-set";

/** p.274: "Must … have fewer than 500 objects within the object set." */
export const MAX_DRAGGED_OBJECTS = 499;

/** The clause naming the type a drop is about.
 *
 * **The same string as `OBJECT_TYPE_CLAUSE` in `workshop_variables.py`**, and a
 * test there reads it out of this file. The server's `narrow_set` checks it
 * against its base set and removes it; a key is only a key within its type, so
 * without it an object dropped from one type would narrow a set of another to
 * whichever member happened to share its key.
 */
export const OBJECT_TYPE_CLAUSE = "$object_type";

/** What one object drag carries — p.570's table cell and Object View icon. */
export function objectPayload(objectTypeId: string, primaryKey: string): string {
  return JSON.stringify({ object_type_id: objectTypeId, primary_keys: [primaryKey] });
}

/** What an object set drag carries — p.569's Object Set Title — or `null`
 * when p.274 says it cannot be dragged: an empty set, or 500 or more. */
export function objectSetPayload(
  objectTypeId: string, primaryKeys: readonly string[],
): string | null {
  if (primaryKeys.length === 0 || primaryKeys.length > MAX_DRAGGED_OBJECTS) return null;
  return JSON.stringify({ object_type_id: objectTypeId, primary_keys: primaryKeys });
}

/** Every key of a set small enough for p.274 to let it be dragged, or `null`
 * when it is not: empty, or 500 objects or more.
 *
 * **Paged, because a store read is.** Both stores clamp a read to one page
 * (`interface_sets.MAX_DEPTH` says why that is a ceiling rather than a
 * policy), so 499 keys is ten requests rather than one. A short page ends the
 * walk early: the set shrank between the count and the read, and asking for
 * pages past its end would only return empty ones.
 */
export async function collectKeys(
  fetchPage: (offset: number, limit: number) => Promise<readonly { primary_key: string }[]>,
  total: number,
  pageSize = 50,
): Promise<string[] | null> {
  // No `total <= 0` case: an empty set runs the loop no times and lands on
  // the `null` below, and a guard that could not change the answer was one
  // the §457 sweep could not make fail.
  if (total > MAX_DRAGGED_OBJECTS) return null;
  const keys: string[] = [];
  for (let offset = 0; offset < total; offset += pageSize) {
    const rows = await fetchPage(offset, pageSize);
    keys.push(...rows.map((row) => row.primary_key));
    if (rows.length < pageSize) break;
  }
  return keys.length > 0 ? keys : null;
}

/** What a drop writes to its output variable (p.568's "Output object set"),
 * or `null` when there is nothing usable on the drag.
 *
 * **The type clause first, then the keys**, with the same `in` clause the
 * Object Table's selection writes, so a set derived from the variable narrows
 * by a rule the builder already has rather than one only drops produce.
 *
 * **Checked for shape rather than trusted**: a drag can come from anywhere on
 * the page (another module, another tab, a hostile page), and what it carries
 * is written into a variable every widget downstream reads.
 *
 * The set type is preferred when a drag carries both, because it says more.
 */
export function droppedClauses(getData: (type: string) => string): Clause[] | null {
  // Chosen by which type is *present*, not by which one parses: a drag that
  // said it was a set and is not one is a broken drag, and reading its other
  // type instead would drop something the person did not drag.
  const asSet = getData(OBJECT_SET_MEDIA_TYPE);
  const raw = parse(asSet || getData(OBJECT_MEDIA_TYPE));
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const { object_type_id: typeId, primary_keys: keys } = raw as Record<string, unknown>;
  if (typeof typeId !== "string" || !typeId) return null;
  if (!Array.isArray(keys) || keys.length === 0 || keys.length > MAX_DRAGGED_OBJECTS) {
    return null;
  }
  if (!keys.every((k) => typeof k === "string" || typeof k === "number")) return null;
  return [
    { property: OBJECT_TYPE_CLAUSE, op: "eq", value: typeId },
    { property: PRIMARY_KEY, op: "in", value: keys.map(String) },
  ];
}

/** Whether a drag *might* be droppable here, from its types alone.
 *
 * Asked during `dragover`, when a browser withholds the data itself and says
 * only which types are on the drag — which is the whole reason a drop zone
 * can light up before anything is dropped, and why this cannot read a value.
 */
export function carriesPayload(types: readonly string[]): boolean {
  return types.includes(OBJECT_MEDIA_TYPE) || types.includes(OBJECT_SET_MEDIA_TYPE);
}

function parse(raw: string): unknown {
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}
