/**
 * p.303's search around on the Map (§734).
 *
 * > "Enable search around: Enable search arounds using the toolbar and context
 * > menu." (`workshop` p.303)
 *
 * p.303 names the setting and where it is reached from, and nothing else; what
 * a search around *is* is `action-types` p.37's sentence, the one definition
 * the corpus gives:
 *
 * > "A Search Around would create a new set by traversing a link on every
 * > object in the current set." (`action-types` p.37)
 *
 * So the current set is where a search starts, and the two places p.303 names
 * are two ways of saying which set that is:
 *
 * * **The toolbar** starts from the map's own layer - the objects selected on
 *   it when some are, and every object on it when none is, since "every object
 *   in the current set" with nothing chosen is the layer itself.
 * * **The context menu** on a pin starts from that one object.
 *
 * The new set is an ordinary object set definition - the far type, reached by
 * `via` from the set below - which the server already walks
 * (`object_set_eval.resolve_traversal`) and already refuses past its depth
 * limit, so a search around from a search around is the same request one
 * level deeper. It is drawn on the map as a layer of its own, beside the ones
 * the builder added, until the viewer removes it.
 *
 * **Which links are offered is p.217's visibility**: "A prominent side of a
 * link type will lead applications to show this side of the link type first
 * to users. A hidden side of a link type will not appear in user
 * applications." (`object-link-types` p.217)
 */

import { PRIMARY_KEY } from "./object-table-selection";

/** Whether the map offers search around: off unless the builder turned it on,
 * which is how every map saved before there was a choice behaves. */
export function searchAroundOf(raw: unknown): boolean {
  return raw === true;
}

/** Where a search around starts: the set it traverses from, its object type
 * (which decides the links that apply), and what to call it. */
export interface SearchStart {
  label: string;
  typeId: string;
  base: Record<string, unknown>;
}

/** The toolbar's start: the map's own set, narrowed to the selection when
 * there is one. Null when the set is not over one object type - a union, or
 * not resolved yet - since then no link applies to all of it. */
export function toolbarStart(
  definition: unknown, keys: readonly string[], layerLabel: string,
): SearchStart | null {
  if (!definition || typeof definition !== "object") return null;
  const set = definition as { object_type_id?: unknown; filters?: unknown };
  if (typeof set.object_type_id !== "string") return null;
  const name = layerLabel.trim() || "Objects";
  if (keys.length === 0) {
    return { label: name, typeId: set.object_type_id, base: { ...set } };
  }
  return {
    label: `${keys.length.toLocaleString()} selected`,
    typeId: set.object_type_id,
    base: {
      ...set,
      // The selection's own clause, as a `narrow_set` downstream reads it.
      filters: [...(Array.isArray(set.filters) ? set.filters : []),
        { property: PRIMARY_KEY, op: "in", value: [...keys] }],
    },
  };
}

/** The context menu's start: the one object a pin stands for. */
export function pinStart(typeId: string, primaryKey: string, label: string): SearchStart {
  return {
    label,
    typeId,
    base: { object_type_id: typeId, filters: [{ property: PRIMARY_KEY, op: "in", value: [primaryKey] }] },
  };
}

/** A link from the start's type, as the ontology lists a type's links. */
export interface Hop {
  link_type_id: string;
  side_name: string;
  far_type_id: string;
  far_type_display_name: string;
  side_visibility?: string;
  direction?: "outbound" | "inbound";
}

/** The links a search around offers, by p.217: prominent sides first, then
 * normal ones, and hidden ones not at all. Otherwise in the ontology's order.
 *
 * **A link from a type to itself is offered once**, outbound: a traversal
 * names no direction, the server derives it from the type it starts at
 * (`object_sets.far_end`), and for a self-link that is always outbound - so
 * the inbound entry would be a second item doing the first one's walk. */
export function searchAroundLinks<T extends Hop>(links: readonly T[], here: string): T[] {
  const walkable = links.filter((l) => !(l.far_type_id === here && l.direction === "inbound"));
  return [
    ...walkable.filter((l) => l.side_visibility === "prominent"),
    ...walkable.filter((l) => l.side_visibility !== "prominent" && l.side_visibility !== "hidden"),
  ];
}

/** What a link reads as in the picker: the side it arrives at, and the type
 * that side is when the name does not already say it. */
export function hopLabel(link: Hop): string {
  const side = link.side_name.trim();
  if (!side) return link.far_type_display_name;
  return side.toLowerCase() === link.far_type_display_name.trim().toLowerCase()
    ? side
    : `${side} (${link.far_type_display_name})`;
}

/** The set a search around creates: the far type, reached by the link from
 * the set it started at. */
export function searchAroundSet(start: SearchStart, link: Hop): Record<string, unknown> {
  return {
    object_type_id: link.far_type_id,
    filters: [],
    via: { link_type_id: link.link_type_id, base: start.base },
  };
}

/** p.37's own wording for the result - "Github Issue of Current Employee" -
 * which is the label its layer carries on the map and in the legend. */
export function resultLabel(start: SearchStart, link: Hop): string {
  return `${link.side_name.trim() || link.far_type_display_name} of ${start.label}`;
}

/** The far type's properties a result's objects can stand at. */
export function locationProperties(
  properties: readonly { api_name: string; data_type?: string }[],
): string[] {
  return properties.filter((p) => p.data_type === "geopoint").map((p) => p.api_name);
}

/** A result layer's colour, one per layer in turn: distinct from each other
 * and from the theme's accent, which the map's own layer wears. */
export const RESULT_COLORS = ["#c2410c", "#7c3aed", "#0f766e", "#b91c1c", "#a16207", "#1d4ed8"];

export function resultColor(n: number): string {
  return RESULT_COLORS[((n % RESULT_COLORS.length) + RESULT_COLORS.length) % RESULT_COLORS.length]!;
}

/** One search around on the map. */
export interface SearchResult {
  id: string;
  label: string;
  typeId: string;
  definition: Record<string, unknown>;
  locationProperty: string;
  /** The arrived-at type's title property, which names its pins. */
  labelProperty: string | null;
  color: string;
}
