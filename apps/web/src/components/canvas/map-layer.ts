/**
 * p.300's settings for the Map's object layer (§559).
 *
 * > "Label: Rename the layer display title … Selected objects: Specify an
 * > object set variable that represents the collection of selected objects in
 * > a layer … This variable is bidirectional … Layer visibility: Control
 * > whether the contents of the layer are visible or hidden in the map. This
 * > setting can be configured as a static value or a boolean variable. Lock
 * > layer: … Objects in locked layers cannot be selected by users. Style: …
 * > the default color, opacity …" (p.300)
 *
 * The map has one object layer - its object set - so these are that layer's.
 * **Selected objects** is held the way the Object Table holds its own
 * (§207, `object-table-selection.ts`): a clause list in an array variable a
 * `narrow_set` reads, which is what makes it bidirectional - anything that
 * writes the variable moves the selection on the map.
 */

/** A layer colour as the panel stores it, or null for the theme's own. */
export function layerColorOf(raw: unknown): string | null {
  return typeof raw === "string" && /^#[0-9a-fA-F]{6}$/.test(raw) ? raw : null;
}

/** A layer opacity, held to a range where the layer can still be seen and
 * clicked: an invisible layer is what Layer visibility is for. */
export function layerOpacityOf(raw: unknown): number {
  const n = typeof raw === "number" ? raw : Number(raw);
  return Number.isFinite(n) ? Math.min(1, Math.max(0.1, n)) : 1;
}

/** Whether the layer shows: its boolean variable's value when one is bound
 * and holds a boolean, the static setting otherwise - and shown unless it
 * says otherwise. */
export function layerVisibleOf(staticValue: unknown, variableValue: unknown, bound: boolean): boolean {
  if (bound && typeof variableValue === "boolean") return variableValue;
  return staticValue !== false;
}
