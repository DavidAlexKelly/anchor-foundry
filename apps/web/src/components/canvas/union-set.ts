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
import type { Clause } from "./object-table-selection";

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
