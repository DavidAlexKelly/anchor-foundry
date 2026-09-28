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

/** p.300's Add object layer (§642).
 *
 * > "In the widget editor, select Add object layer to add a new layer to the
 * > map. Then, open the newly created layer, and create a new object set
 * > variable or reuse an existing one … Once added, the new object layer will
 * > populate on the map." (p.300)
 *
 * The map's own object set is its first layer, configured by the widget's
 * own settings as it always was. Each layer added after it carries the same
 * settings for itself - its object set and where its objects are, its label,
 * Selected objects, visibility, lock and style - and is drawn over the ones
 * before it. */
export interface MapLayer {
  id: string;
  objectSetVariable: string | null;
  locationProperty: string | null;
  labelProperty: string | null;
  label: string;
  selectedVariable: string | null;
  visible: boolean;
  visibleVariable: string | null;
  locked: boolean;
  color: string | null;
  opacity: number;
}

/** The layers a map adds, beyond its own. Each is a set read in full on every
 * change, so the number is bounded. */
export const MAX_LAYERS = 8;

const text = (v: unknown): string | null => (typeof v === "string" && v ? v : null);

/** The added layers as the widget stores them, each read with its own
 * settings' rules; anything that is not a layer is left out. */
export function layersOf(raw: unknown): MapLayer[] {
  if (!Array.isArray(raw)) return [];
  const seen = new Set<string>();
  const out: MapLayer[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const l = item as Record<string, unknown>;
    const id = text(l.id);
    if (!id || seen.has(id)) continue;
    seen.add(id);
    out.push({
      id,
      objectSetVariable: text(l.objectSetVariable),
      locationProperty: text(l.locationProperty),
      labelProperty: text(l.labelProperty),
      label: typeof l.label === "string" ? l.label : "",
      selectedVariable: text(l.selectedVariable),
      visible: l.visible !== false,
      visibleVariable: text(l.visibleVariable),
      locked: l.locked === true,
      color: layerColorOf(l.color),
      // A missing opacity reads as 1 by `layerOpacityOf`'s own rule (a
      // default written here survived the sweep as equivalent).
      opacity: layerOpacityOf(l.opacity),
    });
    if (out.length === MAX_LAYERS) break;
  }
  return out;
}

/** The layers with a new, empty one after them, under an id none of them
 * has; unchanged at the cap. */
export function withNewLayer(raw: unknown): MapLayer[] {
  const layers = layersOf(raw);
  if (layers.length >= MAX_LAYERS) return layers;
  let n = layers.length + 2;
  while (layers.some((l) => l.id === `layer-${n}`)) n += 1;
  return [...layers, {
    id: `layer-${n}`, objectSetVariable: null, locationProperty: null, labelProperty: null,
    label: "", selectedVariable: null, visible: true, visibleVariable: null, locked: false,
    color: null, opacity: 1,
  }];
}

/** The layers with one setting of one layer changed. */
export function withLayerSetting<K extends keyof MapLayer>(
  raw: unknown, id: string, key: K, value: MapLayer[K],
): MapLayer[] {
  return layersOf(raw).map((l) => (l.id === id ? { ...l, [key]: value } : l));
}

export function withoutLayer(raw: unknown, id: string): MapLayer[] {
  return layersOf(raw).filter((l) => l.id !== id);
}

/** A bubble of pins' colour: their layer's when every pin in it shares one,
 * the map's own otherwise. */
export function bubbleColor(colors: readonly (string | null | undefined)[], fallback: string): string {
  const tint = new Set(colors.map((c) => c ?? fallback));
  return tint.size === 1 ? [...tint][0]! : fallback;
}

/** A layer's objects as pins: each where its location property says, and
 * counted rather than dropped where it says nowhere. */
export function layerPoints<P>(
  layer: MapLayer,
  instances: readonly { id: string; primary_key: unknown; properties: Record<string, unknown> }[],
  locate: (value: unknown) => { lat: number; lon: number } | null,
  pin: (instance: (typeof instances)[number], at: { lat: number; lon: number }, label: string) => P,
): { points: P[]; unplaceable: number } {
  const points: P[] = [];
  let unplaceable = 0;
  for (const instance of instances) {
    // No location property reads as no location (a guard for it survived the
    // sweep as equivalent: an api name is never empty).
    const at = locate(instance.properties[layer.locationProperty ?? ""]);
    if (!at) {
      unplaceable += 1;
      continue;
    }
    const raw = layer.labelProperty ? instance.properties[layer.labelProperty] : null;
    points.push(pin(instance, at, raw === null || raw === undefined ? String(instance.primary_key) : String(raw)));
  }
  return { points, unplaceable };
}
