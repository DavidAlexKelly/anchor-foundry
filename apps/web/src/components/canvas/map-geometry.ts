/**
 * p.300's Geometry on a Map widget's object layer (§670; `workshop` p.300).
 *
 * > "Under the Geometry section, a user can edit the styling for a specific
 * > geometry displayed on the map. Like in the Map application, geometries
 * > are different ways of representing the layer's objects. Geometries can be
 * > added by selecting Add geometry. Reorder geometries by dragging them … and
 * > delete them … If an object type includes a Geoshape property and you
 * > configure it in a Map layer geometry, the Map widget automatically loads
 * > and renders it." (p.300)
 * >
 * > "An object layer and its geometries are visible by default in the legend
 * > panel of the map. Under the Legend visibility section, you can toggle the
 * > visibility of the entire layer or individual geometries." (p.300)
 *
 * A layer's pins are its first way of representing its objects, from a
 * geopoint property; a geometry is another, a geoshape property (§425) drawn
 * as the shape it holds, under the pins, in its own colour or the layer's.
 * Later geometries are drawn over earlier ones, so the order is the stacking.
 */

import type { MapShape } from "./map";

export interface MapGeometry {
  id: string;
  /** The geoshape property drawn. */
  property: string | null;
  /** Its own colour; null for the layer's. */
  color: string | null;
  /** p.300's Legend visibility, for this geometry. */
  legend: boolean;
}

/** Geometries per layer: each is one more shape per object, so the number is
 * bounded. */
export const MAX_GEOMETRIES = 4;

const HEX = /^#[0-9a-fA-F]{6}$/;

export function geometriesOf(raw: unknown): MapGeometry[] {
  if (!Array.isArray(raw)) return [];
  const seen = new Set<string>();
  const out: MapGeometry[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const g = item as Record<string, unknown>;
    const id = typeof g.id === "string" && g.id ? g.id : null;
    if (!id || seen.has(id)) continue;
    seen.add(id);
    out.push({
      id,
      property: typeof g.property === "string" && g.property ? g.property : null,
      color: typeof g.color === "string" && HEX.test(g.color) ? g.color : null,
      legend: g.legend !== false,
    });
    if (out.length === MAX_GEOMETRIES) break;
  }
  return out;
}

/** The geometries with an empty one after them, under an id none has;
 * unchanged at the cap. */
export function withNewGeometry(raw: unknown): MapGeometry[] {
  const geometries = geometriesOf(raw);
  if (geometries.length >= MAX_GEOMETRIES) return geometries;
  let n = geometries.length + 1;
  while (geometries.some((g) => g.id === `geometry-${n}`)) n += 1;
  return [...geometries, { id: `geometry-${n}`, property: null, color: null, legend: true }];
}

export function withGeometrySetting<K extends keyof MapGeometry>(
  raw: unknown, id: string, key: K, value: MapGeometry[K],
): MapGeometry[] {
  return geometriesOf(raw).map((g) => (g.id === id ? { ...g, [key]: value } : g));
}

export function withoutGeometry(raw: unknown, id: string): MapGeometry[] {
  return geometriesOf(raw).filter((g) => g.id !== id);
}

/** p.300's reorder: the geometry one place earlier, drawn under the one it
 * passes. The first stays first. */
export function withGeometryEarlier(raw: unknown, id: string): MapGeometry[] {
  const geometries = geometriesOf(raw);
  const at = geometries.findIndex((g) => g.id === id);
  if (at < 1) return geometries;
  const out = [...geometries];
  [out[at - 1], out[at]] = [out[at]!, out[at - 1]!];
  return out;
}

/** A layer's objects as one geometry's shapes: each object holding a value in
 * the property is a shape, labelled as its pin is. An object with no value has
 * no shape; one whose value is not a geometry is still handed on, for the map
 * to count as a shape it cannot draw rather than drop. */
export function geometryShapes(
  layerId: string,
  geometry: MapGeometry,
  instances: readonly { id: string; primary_key: unknown; properties: Record<string, unknown> }[],
  labelProperty: string | null,
  color: string | null,
): MapShape[] {
  return instances.flatMap((instance) => {
    // No property reads as no value, so no shapes (a guard for it survived
    // the sweep as equivalent: an api name is never empty).
    const value = instance.properties[geometry.property ?? ""];
    if (value === null || value === undefined || value === "") return [];
    const raw = labelProperty ? instance.properties[labelProperty] : null;
    return [{
      id: `${layerId}-${geometry.id}-${instance.id}`,
      label: raw === null || raw === undefined ? String(instance.primary_key) : String(raw),
      value,
      color: geometry.color ?? color,
    }];
  });
}
