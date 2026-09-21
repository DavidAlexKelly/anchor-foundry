/**
 * A GeoJSON geometry, drawn on the map (§426; `object-views` p.11).
 *
 * > "Objects with prominent geohash, **geoshape**, or geotemporal series
 * > reference (GTSR) properties will render on a Map." (p.11)
 *
 * §425 gave this platform the type; this is the rendering p.11 asks for. Pure
 * and in its own module because `map.tsx` is a component and a projection is
 * arithmetic — the same split `lib/pipeline-graph` made for the same reason.
 *
 * ---
 *
 * **The same projection the pins use**, which is the whole reason this takes a
 * `MapView` rather than computing one: a shape drawn by its own transform sits
 * beside a pin drawn by the map's, and nothing on the screen says which of the
 * two moved. The arithmetic is one multiply and one subtract, and it is
 * duplicated here exactly once — in `place`, which every function below goes
 * through.
 *
 * **Nothing is clipped.** A polygon half off the view is drawn half off the
 * view and the SVG clips it, which is what an SVG does; clipping the
 * *coordinates* would change a shape's outline the moment somebody panned. A
 * shape entirely outside the view is counted instead, for the reason the map
 * counts off-screen pins: "no shape here" and "you have panned away from it"
 * look identical otherwise.
 *
 * **A geometry this cannot place is counted, never dropped.** That is
 * `map.tsx`'s own rule, one value type along.
 */

import type { MapView } from "./map";
// Relative, and a value import rather than a type one: vitest resolves no
// `@/` alias, so an aliased value import is a module this file's own tests
// cannot load.
import { isGeometry, type Geometry } from "../../lib/geoshape";

/** The map's own canvas, restated here rather than imported, because these two
 *  numbers are the *shape of the drawing surface* and `map.tsx` exports its
 *  view rather than its size. A test holds the pair against each other. */
export const WIDTH = 640;
export const HEIGHT = 340;
export const ASPECT = HEIGHT / WIDTH;

/** One GeoJSON position — `[longitude, latitude]` — in SVG coordinates.
 *
 * **Longitude first**, which is the order a geoshape's positions come in
 * (`functions` p.40) and the opposite of a geopoint's. The map's pin
 * arithmetic takes `lat`/`lon` by name and cannot get this wrong; here the
 * pair is positional, so the order is the one thing worth a sentence. */
export function place(
  position: readonly number[], view: MapView,
): { x: number; y: number } {
  const h = view.w * ASPECT;
  return {
    x: ((position[0]! - view.x) / view.w) * WIDTH,
    y: ((-position[1]! - view.y) / h) * HEIGHT,
  };
}

function isPosition(value: unknown): value is number[] {
  return Array.isArray(value)
    && value.length >= 2
    && typeof value[0] === "number"
    && typeof value[1] === "number";
}

/** Every position in a geometry, at any depth. */
function positions(value: unknown): number[][] {
  if (isPosition(value)) return [value];
  if (Array.isArray(value)) return value.flatMap(positions);
  return [];
}

/** One ring or line as SVG path data. */
function line(ring: unknown, view: MapView, close: boolean): string {
  const points = positions(ring).map((p) => place(p, view));
  if (points.length === 0) return "";
  const head = `M ${points[0]!.x} ${points[0]!.y}`;
  const rest = points.slice(1).map((p) => `L ${p.x} ${p.y}`).join(" ");
  // **`Z` on a polygon ring even when the coordinates already repeat the
  // first position**, which RFC 7946 requires them to. A duplicated final
  // point draws the closing segment anyway; `Z` is what makes the subpath
  // *closed*, which is what `fill-rule` needs to cut a hole for an inner ring.
  return close ? `${head} ${rest} Z`.replace("  ", " ") : `${head} ${rest}`;
}

export interface DrawnShape {
  /** SVG path data, or `""` for a geometry with nothing to draw. */
  d: string;
  /** Whether the path encloses an area — a polygon fills, a line does not. */
  filled: boolean;
  /** Where a label sits: the first position, which is on the shape rather
   *  than at a centroid that may fall outside a crescent. */
  at: { x: number; y: number } | null;
}

/**
 * A geometry as SVG paths.
 *
 * **A list, not one path**, because a MultiPolygon's parts and a collection's
 * members can differ in whether they fill: a GeometryCollection holding a
 * polygon and a line is one value and two drawings.
 *
 * A `Point` draws as a tiny closed diamond rather than being handed to the
 * pin layer: the pin layer clusters, and a shape's point is part of a shape
 * rather than a thing to count with the others.
 */
export function pathsFor(value: unknown, view: MapView): DrawnShape[] {
  if (!isGeometry(value)) return [];
  const shape = value as Geometry;
  switch (shape.type) {
    case "GeometryCollection":
      return (shape.geometries ?? []).flatMap((part) => pathsFor(part, view));
    case "Point": {
      if (!isPosition(shape.coordinates)) return [];
      const at = place(shape.coordinates as number[], view);
      const r = 4;
      return [{
        d: `M ${at.x} ${at.y - r} L ${at.x + r} ${at.y} L ${at.x} ${at.y + r} `
          + `L ${at.x - r} ${at.y} Z`,
        filled: true,
        at,
      }];
    }
    case "MultiPoint":
      return positions(shape.coordinates).flatMap((p) =>
        pathsFor({ type: "Point", coordinates: p }, view));
    case "LineString": {
      const d = line(shape.coordinates, view, false);
      return d ? [{ d, filled: false, at: firstAt(shape.coordinates, view) }] : [];
    }
    case "MultiLineString":
      return (shape.coordinates as unknown[] ?? []).flatMap((part) =>
        pathsFor({ type: "LineString", coordinates: part }, view));
    case "Polygon": {
      // **Every ring in one path**, outer and inner together: that is what
      // makes `fill-rule="evenodd"` cut the hole. Two paths would draw a
      // filled island inside the lake.
      const rings = (shape.coordinates as unknown[] ?? [])
        .map((ring) => line(ring, view, true))
        .filter(Boolean);
      return rings.length
        ? [{ d: rings.join(" "), filled: true, at: firstAt(shape.coordinates, view) }]
        : [];
    }
    case "MultiPolygon":
      return (shape.coordinates as unknown[] ?? []).flatMap((part) =>
        pathsFor({ type: "Polygon", coordinates: part }, view));
    default:
      return [];
  }
}

function firstAt(coordinates: unknown, view: MapView): { x: number; y: number } | null {
  const first = positions(coordinates)[0];
  return first ? place(first, view) : null;
}

/** The view that shows a whole geometry, in the units `map.fitView` speaks.
 *
 * Returns `null` for a geometry with no positions, so the caller keeps
 * whatever view it had rather than jumping to the middle of the ocean. */
export function boundsOf(value: unknown): {
  minLon: number; maxLon: number; minLat: number; maxLat: number;
} | null {
  if (!isGeometry(value)) return null;
  const shape = value as Geometry;
  const all = shape.geometries
    ? shape.geometries.flatMap((part) => positions(part.coordinates ?? []))
    : positions(shape.coordinates);
  if (all.length === 0) return null;
  const lons = all.map((p) => p[0]!);
  const lats = all.map((p) => p[1]!);
  return {
    minLon: Math.min(...lons), maxLon: Math.max(...lons),
    minLat: Math.min(...lats), maxLat: Math.max(...lats),
  };
}

/** Whether any part of a geometry is inside the view.
 *
 * **Bounds against bounds**, which over-reports: a diagonal line whose box
 * overlaps the view may itself miss it entirely. That is the safe direction —
 * the count exists to say "you have panned away from your data", and a shape
 * wrongly called visible is a count of zero that is correct about the
 * *interesting* case. */
export function onScreen(value: unknown, view: MapView): boolean {
  const box = boundsOf(value);
  if (box === null) return false;
  const h = view.w * ASPECT;
  return box.maxLon >= view.x && box.minLon <= view.x + view.w
    && -box.minLat >= view.y && -box.maxLat <= view.y + h;
}
