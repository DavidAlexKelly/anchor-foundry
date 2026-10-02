/** p.450's union of object sets of different types, as a widget reads it (§686).
 *
 * > "You can use a variable to store a union of multiple object sets of
 * > different object types and pass it to the Filter List widget." (p.450)
 *
 * > "Combine multiple object types: This setting only affects tables
 * > displaying multiple object types. When disabled, each object type will be
 * > displayed within its own tab." (p.225)
 *
 * A `union_set` variable resolves to `{union: [definition, ...]}`: each part an
 * ordinary set over one type, which is what every read here is over. So the
 * Object Table reads a union a tab at a time, and each tab is a set it
 * already knows how to draw.
 *
 * **A selection names its type.** A key is a key only within its own type, so
 * "S1" picked in the Staff tab would otherwise narrow the Sites part to
 * whichever site is also "S1". The server's `narrow_set` reads the type clause
 * (§457's, from a drop) against every part, and a tab reads back only the
 * selection its own type wrote.
 */

import { OBJECT_TYPE_CLAUSE } from "./drag-payload";
import { keysOf, selectionClauses, type Clause } from "./object-table-selection";

/** The server's `object_sets.UNION`; a test there reads it out of this file. */
export const UNION = "union";

export interface SetPart {
  object_type_id: string;
  filters?: { property: string; op?: string; value: unknown }[];
}

/** A union's parts, or `null` for anything that is not one - a set over one
 * type included, since a definition naming a type is that type's. */
export function unionParts(definition: unknown): SetPart[] | null {
  if (!definition || typeof definition !== "object") return null;
  const raw = definition as Record<string, unknown>;
  if (raw.object_type_id || !Array.isArray(raw[UNION])) return null;
  const parts = (raw[UNION] as unknown[]).filter(
    (p): p is SetPart =>
      !!p && typeof p === "object" && typeof (p as SetPart).object_type_id === "string",
  );
  return parts;
}

/** Which tab is showing: the one asked for, or the last when a union shrank
 * under it. Never negative, so an empty union shows no tab rather than
 * reading index -1. */
export function tabIndex(requested: number, count: number): number {
  return Math.max(0, Math.min(requested, count - 1));
}

/** A selection as a union tab writes it: its type first, then the keys. With
 * no type (a table over one set) it is the selection unchanged. */
export function typedSelection(clauses: Clause[], typeId: string | null): Clause[] {
  return typeId ? [{ property: OBJECT_TYPE_CLAUSE, op: "eq", value: typeId }, ...clauses] : clauses;
}

/** A selection as this tab reads it back: the clauses, unless they name
 * another type, in which case none of their keys are this tab's. */
export function selectionIn(raw: unknown, typeId: string | null): unknown {
  if (!typeId || !Array.isArray(raw)) return raw;
  const other = raw.some(
    (c) => !!c && typeof c === "object"
      && (c as Clause).property === OBJECT_TYPE_CLAUSE && (c as Clause).value !== typeId,
  );
  return other ? [] : raw;
}

/** p.450's two kinds of filter over a union (§687).
 *
 * > "Common property: The properties that the different object types have in
 * > common. The properties must have the same property ID to be matched
 * > together… Single property: A unique property that exists on only one of
 * > the object types." (p.450)
 *
 * A property's id here is its api name. **A property some types share and
 * others lack is neither**, and p.450 offers only the two. A single property
 * is named with its type, since a filter's label is all a viewer has to tell
 * whose it is. Each keeps the first type's property otherwise, in that type's
 * order.
 *
 * **Nothing until every type has loaded** (`undefined` for one that has not):
 * over some of the types, a property only they share would be offered as
 * common and taken back a moment later. */
export function unionProperties<P extends { api_name: string; display_name: string }>(
  loading: readonly ({ displayName: string; properties: readonly P[] } | undefined)[],
): { common: P[]; single: P[] } {
  if (loading.some((t) => !t)) return { common: [], single: [] };
  const types = loading as readonly { displayName: string; properties: readonly P[] }[];
  const holders = (name: string) =>
    types.filter((t) => t.properties.some((p) => p.api_name === name)).length;
  const common = (types[0]?.properties ?? []).filter((p) => holders(p.api_name) === types.length);
  const single = types.flatMap((t) => t.properties
    .filter((p) => types.length > 1 && holders(p.api_name) === 1)
    .map((p) => ({ ...p, display_name: `${p.display_name || p.api_name} (${t.displayName})` })));
  return { common, single };
}

/** The type a selection names, if it names one (§688): what tells a union's
 * rows with the same key apart when the selection is read back. */
export function selectedType(raw: unknown): string | null {
  if (!Array.isArray(raw)) return null;
  const clause = raw.find(
    (c) => !!c && typeof c === "object" && (c as Clause).property === OBJECT_TYPE_CLAUSE,
  ) as Clause | undefined;
  return typeof clause?.value === "string" ? clause.value : null;
}

// ---- p.225's Combine multiple object types (§689) ---------------------------
/** > "When enabled, all object types will be displayed within a single table
 * > and, across object types, property types that share both display names
 * > and IDs will be combined into a single column." (p.225)
 *
 * Every type's properties in type order, one column for each api name and
 * display name pair, and `covers` the types whose objects have a value
 * there. A pair shared by two types is one column; the same api name under
 * two display names is two, each blank for the other type's rows.
 *
 * **None until every type has loaded** (`undefined` for one that has not),
 * for `unionProperties`' reason: columns from some of the types would be
 * drawn and redrawn. */
export function combinedColumns<P extends { api_name: string; display_name: string }>(
  loading: readonly ({ id: string; properties: readonly P[] } | undefined)[],
): (P & { covers: string[] })[] {
  if (loading.some((t) => !t)) return [];
  const columns: (P & { covers: string[] })[] = [];
  for (const type of loading as readonly { id: string; properties: readonly P[] }[]) {
    for (const p of type.properties) {
      const same = columns.find(
        (c) => c.api_name === p.api_name && c.display_name === p.display_name,
      );
      if (same) same.covers.push(type.id);
      else columns.push({ ...p, covers: [type.id] });
    }
  }
  return columns;
}

/** Several objects of several types, as one clause (§689): `[type, key]`
 * pairs. The server's `OBJECTS_CLAUSE`; a test there reads it out of this
 * file. Written beside the keys' own clause, so everything that reads a
 * selection's keys still reads them. */
export const OBJECTS_CLAUSE = "$objects";

/** One selected object: its key, and its type where the key alone is not
 * enough to say which object it is. */
export interface Picked {
  type: string | null;
  key: string;
}

/** A selection read back. Over one set, or one tab, the keys (a tab's
 * already filtered to its own type); in a combined table each object with
 * its type, from the pairs or from the type the selection names. */
export function pickedIn(raw: unknown, combined: boolean, tabType: string | null): Picked[] {
  if (!combined) return keysOf(selectionIn(raw, tabType)).map((key) => ({ type: null, key }));
  const pairs = Array.isArray(raw)
    ? (raw.find((c) => !!c && typeof c === "object" && (c as Clause).property === OBJECTS_CLAUSE) as
        Clause | undefined)
    : undefined;
  if (pairs && Array.isArray(pairs.value)) {
    return pairs.value
      .filter((pair): pair is [string, string] => Array.isArray(pair) && pair.length === 2)
      .map(([type, key]) => ({ type: String(type), key: String(key) }));
  }
  const type = selectedType(raw);
  return keysOf(raw).map((key) => ({ type, key }));
}

/** A selection written: one type's objects as that type's keys, and
 * several types' as their pairs beside all their keys. */
export function pickedClauses(
  picked: readonly Picked[], combined: boolean, tabType: string | null,
): Clause[] {
  const keys = picked.map((p) => p.key);
  if (!combined) return typedSelection(selectionClauses(keys), tabType);
  const types = [...new Set(picked.map((p) => p.type))];
  if (types.length > 1) {
    return [
      { property: OBJECTS_CLAUSE, op: "in", value: picked.map((p) => [p.type, p.key]) },
      ...selectionClauses(keys),
    ];
  }
  return typedSelection(selectionClauses(keys), types[0] ?? null);
}

/** Whether a row is one of these: its key, and its type when the entry has one. */
export function isPicked(
  picked: readonly Picked[], row: { primary_key: string; object_type_id?: string | null },
): boolean {
  return picked.some((p) => p.key === row.primary_key
    && (p.type === null || p.type === (row.object_type_id ?? null)));
}

/** This row as an entry: with its type in a combined table. */
export function pickOf(
  row: { primary_key: string; object_type_id?: string | null }, combined: boolean,
): Picked {
  return { type: combined ? row.object_type_id ?? null : null, key: row.primary_key };
}

/** The server's `union_reads.MAX_DEPTH`: how far a combined table pages. */
export const UNION_PAGE_DEPTH = 200;
