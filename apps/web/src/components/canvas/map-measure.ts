/**
 * p.302's measurements of a shape drawn on the Workshop Map (§575).
 *
 * > "Enable measurements: Allow users to view the measurements of their drawn
 * > shapes. Units are based on map settings if configured, or default to
 * > organization settings. Enable polygon perimeter: Show the length of each
 * > segment or the total perimeter length along a drawn polygon's edges.
 * > Enable polygon area: Show the polygon's area in the center of the drawn
 * > polygon. Enable line measurements: Show either individual segment
 * > lengths or the total length of a drawn line" (p.302)
 *
 * **Measured on the ground, along the edges the map draws**, which are the
 * edges the selection reads: `object_sets.in_polygon` takes a shape's edges
 * as straight in longitude and latitude, and so does the map. They are not
 * great circles, and measuring them as great circles would measure a shape
 * other than the one that selects. So:
 *
 * - **area** is exact: R² times ∮ sin(lat) d(lon) round the outline, which
 *   along an edge straight in longitude and latitude has a closed form.
 * - **an edge's length** is R times ∫ √(dlat² + cos²(lat) dlon²),
 *   integrated numerically; exact for an edge along a parallel or a
 *   meridian, as a rectangle's are.
 * - **a circle** is a cap on the sphere, which is exact: circumference
 *   2πR·sin(r/R) and area 2πR²·(1 − cos(r/R)).
 *
 * Units are metric: there are no map or organization unit settings here.
 * Lines are not drawn here yet, so neither are their measurements.
 *
 * Pure.
 */

import {
  EARTH_RADIUS_M, isCircle, isPolygon, type Area, type Frame, type View,
} from "./map-area";

export const PERIMETER_MODES = ["segments", "total"] as const;
export type PerimeterMode = (typeof PERIMETER_MODES)[number];

export function perimeterModeOf(raw: unknown): PerimeterMode {
  return raw === "segments" ? "segments" : "total";
}

type LonLat = { lat: number; lon: number };
const rad = (d: number) => (d * Math.PI) / 180;
/** Steps of the numerical integration along an edge: Simpson's rule, which
 * this many steps makes exact to well under a metre on any edge the map can
 * hold. */
const STEPS = 64;

/** A shape's corners in order, the edge back to the first implied. */
export function cornersOf(area: Area): LonLat[] {
  if (isPolygon(area)) return area.points;
  if (isCircle(area)) return [];
  const { north, south, east, west } = area;
  return [
    { lat: south, lon: west }, { lat: south, lon: east },
    { lat: north, lon: east }, { lat: north, lon: west },
  ];
}

/** The length of an edge straight in longitude and latitude, in metres. */
export function edgeM(a: LonLat, b: LonLat): number {
  const dLat = rad(b.lat - a.lat);
  const dLon = rad(b.lon - a.lon);
  const at = (t: number) => Math.hypot(dLat, Math.cos(rad(a.lat) + t * dLat) * dLon);
  let sum = at(0) + at(1);
  for (let n = 1; n < STEPS; n++) sum += (n % 2 ? 4 : 2) * at(n / STEPS);
  return (EARTH_RADIUS_M * sum) / (3 * STEPS);
}

/** Each edge's length in metres, the closing edge last. */
export function segmentsM(area: Area): number[] {
  const corners = cornersOf(area);
  return corners.map((p, n) => edgeM(p, corners[(n + 1) % corners.length]!));
}

export function perimeterM(area: Area): number {
  if (isCircle(area)) return 2 * Math.PI * EARTH_RADIUS_M * Math.sin(area.radius / EARTH_RADIUS_M);
  return segmentsM(area).reduce((sum, m) => sum + m, 0);
}

/** The area on the ground in square metres. */
export function areaM2(area: Area): number {
  const R = EARTH_RADIUS_M;
  if (isCircle(area)) return 2 * Math.PI * R * R * (1 - Math.cos(area.radius / R));
  const corners = cornersOf(area);
  let total = 0;
  corners.forEach((a, n) => {
    const b = corners[(n + 1) % corners.length]!;
    const [p1, p2] = [rad(a.lat), rad(b.lat)];
    const dLon = rad(b.lon - a.lon);
    // ∫ sin(lat) d(lon) along the edge, lat and lon both linear in it.
    total += p1 === p2 ? dLon * Math.sin(p1) : (dLon * (Math.cos(p1) - Math.cos(p2))) / (p2 - p1);
  });
  return Math.abs(total) * R * R;
}

const whole = (n: number) => Math.round(n).toLocaleString("en-US");
const tenths = (n: number) =>
  n < 100 ? String(Math.round(n * 10) / 10) : whole(n);

/** A length as a reader reads one: metres under a kilometre, else km. */
export function lengthLabel(m: number): string {
  return Math.round(m) < 1000 ? `${Math.round(m)} m` : `${tenths(m / 1000)} km`;
}

/** An area: square metres under a square kilometre, else km². */
export function areaLabel(m2: number): string {
  return Math.round(m2) < 1_000_000 ? `${whole(m2)} m²` : `${tenths(m2 / 1_000_000)} km²`;
}

export interface MeasureLabel {
  kind: "segment" | "perimeter" | "area";
  text: string;
  x: number;
  y: number;
}

/** The labels a measured shape shows, placed on the map's frame: each
 * segment's at its middle, and the perimeter and area at the shape's centre
 * (the area first, with the perimeter under it). */
export function measureLabels(
  area: Area,
  options: { perimeter: PerimeterMode | null; area: boolean },
  view: View,
  frame: Frame,
): MeasureLabel[] {
  const h = view.w * (frame.height / frame.width);
  const px = (p: LonLat) => ({
    x: ((p.lon - view.x) / view.w) * frame.width,
    y: ((-p.lat - view.y) / h) * frame.height,
  });
  const corners = cornersOf(area);
  const centre = isCircle(area) ? px(area)
    : px({
      lat: corners.reduce((s, p) => s + p.lat, 0) / corners.length,
      lon: corners.reduce((s, p) => s + p.lon, 0) / corners.length,
    });
  const out: MeasureLabel[] = [];
  if (options.area) {
    out.push({ kind: "area", text: areaLabel(areaM2(area)), ...centre });
  }
  if (options.perimeter === "total" || (options.perimeter === "segments" && isCircle(area))) {
    // A circle has no segments: its circumference is its one length.
    out.push({ kind: "perimeter", text: lengthLabel(perimeterM(area)),
      x: centre.x, y: centre.y + (options.area ? 14 : 0) });
  } else if (options.perimeter === "segments") {
    segmentsM(area).forEach((m, n) => {
      const a = corners[n]!;
      const b = corners[(n + 1) % corners.length]!;
      out.push({ kind: "segment", text: lengthLabel(m),
        ...px({ lat: (a.lat + b.lat) / 2, lon: (a.lon + b.lon) / 2 }) });
    });
  }
  return out;
}
