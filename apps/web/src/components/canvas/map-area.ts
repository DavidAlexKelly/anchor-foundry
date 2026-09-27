/**
 * p.302's shape-based selection on the Map, with a rectangle (§550).
 *
 * > "Enable shaped-based selection: Enable a tool to select objects on the map
 * > that intersect a drawn shape." (p.302)
 *
 * §230 built the data half: `within_box` narrows an object set to the objects
 * whose declared geopoint is inside a bounding box, on both stores, a box
 * across the antimeridian included (decision 0006 §3). This is the half a
 * reader holds: a rectangle dragged on the map becomes that clause, written
 * into an array variable the way a Filter List writes its clauses, so a
 * `narrow_set` downstream reads the objects inside it.
 *
 * **A rectangle, and as of §571 a polygon**, each its own operator: a polygon
 * answered as its bounding box would select objects outside what the reader
 * drew, so it is `within_polygon`, which both stores answer by the even-odd
 * rule `object_sets.in_polygon` states. A property holds one area of either
 * shape. Circles and lines stay ○.
 *
 * Pure: the map's projection is `map.tsx`'s, handed in as a view and a frame.
 */

import type { Clause } from "./filter-clause";

export interface Box {
  north: number;
  south: number;
  east: number;
  west: number;
}

export interface View {
  /** Left edge, in degrees of longitude. */
  x: number;
  /** Top edge, in degrees of -latitude (SVG's y grows downward). */
  y: number;
  /** Width in degrees; the height is `w * frame.height / frame.width`. */
  w: number;
}

export interface Frame { width: number; height: number }

export const AREA_OP = "within_box";
/** §571's shape: corners in order, the edge back to the first implied. */
export const POLYGON_OP = "within_polygon";
/** `object_sets.MAX_POLYGON_POINTS`: the corners a drawn shape may have. */
export const MAX_POLYGON_POINTS = 100;
/** A click this near the first corner closes the shape. */
export const CLOSE_PX = 10;

export interface Polygon {
  points: { lat: number; lon: number }[];
}

/** The area a map holds: a rectangle or a drawn shape. */
export type Area = Box | Polygon;

export function isPolygon(area: Area): area is Polygon {
  return Array.isArray((area as Polygon).points);
}

/** The longitude and latitude under a point of the map's frame. */
export function lonLatAt(px: number, py: number, view: View, frame: Frame): {
  lon: number; lat: number;
} {
  const h = view.w * (frame.height / frame.width);
  return { lon: view.x + (px / frame.width) * view.w, lat: -(view.y + (py / frame.height) * h) };
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/** The box two corners of a drag span, whichever way it was dragged, held to
 * the world: a drag past the map's edge selects to the edge. */
export function boxBetween(a: { lon: number; lat: number }, b: { lon: number; lat: number }): Box {
  return {
    north: clamp(Math.max(a.lat, b.lat), -90, 90),
    south: clamp(Math.min(a.lat, b.lat), -90, 90),
    east: clamp(Math.max(a.lon, b.lon), -180, 180),
    west: clamp(Math.min(a.lon, b.lon), -180, 180),
  };
}

/** A drag this short is a click on the map, not an area. */
export const MIN_DRAG_PX = 4;

export function isDrag(a: { x: number; y: number }, b: { x: number; y: number }): boolean {
  return Math.abs(a.x - b.x) >= MIN_DRAG_PX && Math.abs(a.y - b.y) >= MIN_DRAG_PX;
}

const isArea = (c: Clause, property: string) =>
  c.property === property && (c.op === AREA_OP || c.op === POLYGON_OP);

/** The area this property is narrowed to, read back from the clauses: a box,
 * a drawn shape, or nothing for a value that is neither. */
export function areaOf(clauses: readonly Clause[], property: string): Area | null {
  const found = clauses.find((c) => isArea(c, property));
  if (found?.op === POLYGON_OP) {
    const points = (found.value as Partial<Polygon> | undefined)?.points;
    const ok = Array.isArray(points) && points.length >= 3
      && points.every((p) => typeof p?.lat === "number" && typeof p?.lon === "number");
    return ok ? { points: points as Polygon["points"] } : null;
  }
  const v = found?.value as Partial<Box> | undefined;
  if (!v || !["north", "south", "east", "west"].every((k) => typeof v[k as keyof Box] === "number")) {
    return null;
  }
  return v as Box;
}

/** The clauses with this property's area replaced by a box or a shape, or
 * removed for `null`: one area to a property, of either kind. */
export function withArea(clauses: readonly Clause[], property: string, area: Area | null): Clause[] {
  const rest = clauses.filter((c) => !isArea(c, property));
  if (!area) return rest;
  return [...rest, { property, op: isPolygon(area) ? POLYGON_OP : AREA_OP, value: area }];
}

/** Where a shape's corners sit on the map's frame, as an SVG `points` list. */
export function polygonPoints(polygon: Polygon, view: View, frame: Frame): string {
  const h = view.w * (frame.height / frame.width);
  return polygon.points
    .map((p) => `${((p.lon - view.x) / view.w) * frame.width},${((-p.lat - view.y) / h) * frame.height}`)
    .join(" ");
}

/** Whether a click closes the shape being drawn: near its first corner, with
 * three corners already there to close. */
export function closes(corners: readonly { x: number; y: number }[], at: { x: number; y: number }): boolean {
  const first = corners[0];
  return corners.length >= 3 && !!first
    && Math.hypot(first.x - at.x, first.y - at.y) <= CLOSE_PX;
}

/** Where a box sits on the map's frame, for drawing it. */
export function boxRect(box: Box, view: View, frame: Frame): {
  x: number; y: number; width: number; height: number;
} {
  const h = view.w * (frame.height / frame.width);
  const px = (lon: number) => ((lon - view.x) / view.w) * frame.width;
  const py = (lat: number) => ((-lat - view.y) / h) * frame.height;
  return {
    x: px(box.west), y: py(box.north),
    width: px(box.east) - px(box.west), height: py(box.south) - py(box.north),
  };
}
