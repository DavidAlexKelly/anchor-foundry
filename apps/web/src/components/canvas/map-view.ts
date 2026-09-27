/**
 * p.304's viewport on the Workshop Map (§560).
 *
 * > "Viewport bounds: This setting is a bidirectional string variable where
 * > the GeoJSON value represents the current viewing window of the map."
 * > "Viewport auto zoom: … Object set: Centers the map on the content of the
 * > given object set. All objects: Centers the map on all objects added to the
 * > Map widget. Only update if outside viewport: Restrict auto zooming
 * > behavior to instances where the target objects are completely outside of
 * > the current viewport." (p.304)
 *
 * A view is the map's own: a left edge, a top edge in -latitude, and a width
 * in degrees, with the height the width times the frame's aspect. Pure.
 */

export interface View {
  x: number;
  y: number;
  w: number;
}

const round = (n: number) => Math.round(n * 1e6) / 1e6;

/** The view as a GeoJSON polygon: its four corners, closed, as
 * [longitude, latitude]. */
export function boundsText(view: View, aspect: number): string {
  const west = round(view.x);
  const east = round(view.x + view.w);
  const north = round(-view.y);
  const south = round(-(view.y + view.w * aspect));
  return JSON.stringify({
    type: "Polygon",
    coordinates: [[[west, south], [east, south], [east, north], [west, north], [west, south]]],
  });
}

/** A view from any GeoJSON geometry's bounding box, fitted to the frame: the
 * box's width, or its height over the aspect, whichever needs more room. Null
 * for text that is not a geometry with coordinates. */
export function viewOfBounds(text: unknown, aspect: number): View | null {
  // No blank check: `JSON.parse` refuses blank text itself (one survived the
  // sweep as equivalent).
  if (typeof text !== "string") return null;
  let geometry: unknown;
  try {
    geometry = JSON.parse(text);
  } catch {
    return null;
  }
  const pairs: number[][] = [];
  const walk = (node: unknown) => {
    if (Array.isArray(node) && node.length >= 2 && node.every((n) => typeof n === "number")) {
      pairs.push(node as number[]);
    } else if (Array.isArray(node)) {
      node.forEach(walk);
    }
  };
  walk((geometry as { coordinates?: unknown } | null)?.coordinates);
  if (!pairs.length) return null;
  const lons = pairs.map((p) => p[0]!);
  const lats = pairs.map((p) => p[1]!);
  const west = Math.min(...lons);
  const north = Math.max(...lats);
  const w = Math.max(Math.max(...lons) - west, (north - Math.min(...lats)) / aspect);
  return w > 0 ? { x: west, y: -north, w } : null;
}

/** Whether every one of these points is inside the view - p.304's "only
 * update if outside viewport" leaves the view alone when so. */
export function allInside(points: readonly { lat: number; lon: number }[], view: View, aspect: number): boolean {
  return points.every((p) =>
    p.lon >= view.x && p.lon <= view.x + view.w
    && -p.lat >= view.y && -p.lat <= view.y + view.w * aspect);
}

/** Whether two views are the same to the precision a bounds variable holds,
 * so a view written out and read back does not move the map. */
export function sameView(a: View | null, b: View | null, aspect: number): boolean {
  return !!a && !!b && boundsText(a, aspect) === boundsText(b, aspect);
}
