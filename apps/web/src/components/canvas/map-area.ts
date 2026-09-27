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
 * rule `object_sets.in_polygon` states. As of §572 a circle too: a centre and
 * a radius in metres on the ground, `within_distance`, which both stores
 * answer as `object_sets.in_circle`'s great-circle distance. A property holds
 * one area of any of the three. Lines stay ○.
 *
 * **p.301's Draw options and drawn shape style (§573)**: which of the three
 * tools the toolbar offers, and the colour and fill opacity of what is drawn.
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

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
/** §571's shape: corners in order, the edge back to the first implied. */
export const POLYGON_OP = "within_polygon";
/** `object_sets.MAX_POLYGON_POINTS`: the corners a drawn shape may have. */
export const MAX_POLYGON_POINTS = 100;
/** A click this near the first corner closes the shape. */
export const CLOSE_PX = 10;

export interface Polygon {
  points: { lat: number; lon: number }[];
}

/** §572's circle: a centre, and a radius in metres on the ground. */
export const CIRCLE_OP = "within_distance";
/** `object_sets.EARTH_RADIUS_M`: the mean Earth both stores measure on. */
export const EARTH_RADIUS_M = 6371008.7714;
/** `object_sets.MAX_RADIUS_M`. */
export const MAX_RADIUS_M = 20_000_000;

export interface Circle {
  lat: number;
  lon: number;
  radius: number;
}

/** The area a map holds: a rectangle, a drawn shape or a circle. */
export type Area = Box | Polygon | Circle;

export function isPolygon(area: Area): area is Polygon {
  return Array.isArray((area as Polygon).points);
}

export function isCircle(area: Area): area is Circle {
  return typeof (area as Circle).radius === "number";
}

type LonLat = { lat: number; lon: number };
const rad = (d: number) => (d * Math.PI) / 180;
const deg = (r: number) => (r * 180) / Math.PI;

/** `object_sets.distance_m`: great-circle metres by the haversine, with its
 * clamp and for its reason (a term over 1 would make the distance NaN). */
export function distanceM(a: LonLat, b: LonLat): number {
  const h = Math.sin(rad(b.lat - a.lat) / 2) ** 2
    + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(rad(b.lon - a.lon) / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** The circle a drag from its centre to its edge draws: the centre held to
 * the world, and the radius to the metre, at most the widest the server
 * takes. */
export function circleBetween(centre: LonLat, edge: LonLat): Circle {
  const lat = clamp(centre.lat, -90, 90);
  const lon = clamp(centre.lon, -180, 180);
  const radius = Math.round(distanceM({ lat, lon }, { lat: clamp(edge.lat, -90, 90), lon: edge.lon }));
  return { lat, lon, radius: clamp(radius, 1, MAX_RADIUS_M) };
}

/** A circle's outline on the map, as the rings an even-odd fill draws.
 *
 * On a flat map a circle on the ground is not a circle, so its edge is
 * walked point by point, each the radius away from the centre on a bearing,
 * its longitude kept continuous rather than wrapped. A circle round one pole
 * is a band, closed along that pole's edge of the map; one round both is
 * the world with the far side's cap left out. */
export function circleRings(circle: Circle, steps = 90): LonLat[][] {
  const d = circle.radius / EARTH_RADIUS_M;
  const p1 = rad(circle.lat);
  const edge: LonLat[] = [];
  let last: number | null = null;
  for (let n = 0; n < steps; n++) {
    const bearing = (2 * Math.PI * n) / steps;
    const p2 = Math.asin(Math.sin(p1) * Math.cos(d) + Math.cos(p1) * Math.sin(d) * Math.cos(bearing));
    let lon = circle.lon + deg(Math.atan2(Math.sin(bearing) * Math.sin(d) * Math.cos(p1),
      Math.cos(d) - Math.sin(p1) * Math.sin(p2)));
    if (last !== null) lon += 360 * Math.round((last - lon) / 360);
    last = lon;
    edge.push({ lat: deg(p2), lon });
  }
  const north = distanceM(circle, { lat: 90, lon: 0 }) <= circle.radius;
  const south = distanceM(circle, { lat: -90, lon: 0 }) <= circle.radius;
  if (north && south) {
    const world = [{ lat: 90, lon: -180 }, { lat: 90, lon: 180 }, { lat: -90, lon: 180 },
      { lat: -90, lon: -180 }];
    return [world, edge];
  }
  if (north || south) {
    const pole = north ? 90 : -90;
    const first = edge[0]!;
    const end = edge[edge.length - 1]!;
    return [[...edge, { lat: pole, lon: end.lon }, { lat: pole, lon: first.lon }]];
  }
  return [edge];
}

/** A circle's outline on the map's frame, as an SVG path. */
export function circlePath(circle: Circle, view: View, frame: Frame): string {
  const h = view.w * (frame.height / frame.width);
  return circleRings(circle)
    .map((ring) => "M" + ring
      .map((p) => `${((p.lon - view.x) / view.w) * frame.width},${((-p.lat - view.y) / h) * frame.height}`)
      .join("L") + "Z")
    .join("");
}

/** p.301's Draw options (§573): the tools a map's toolbar may offer, in its
 * order. */
export const DRAW_TOOLS = ["rectangle", "polygon", "circle"] as const;
export type DrawTool = (typeof DRAW_TOOLS)[number];
export const DRAW_TOOL_LABELS: Record<DrawTool, string> = {
  rectangle: "Rectangle",
  polygon: "Shape",
  circle: "Circle",
};

/** The tools a map offers: those named, in the toolbar's order, or all
 * three for a map saved before there was a choice. None is a choice too: a
 * map whose area is set only by what writes its variable. */
export function drawToolsOf(raw: unknown): DrawTool[] {
  if (!Array.isArray(raw)) return [...DRAW_TOOLS];
  return DRAW_TOOLS.filter((t) => raw.includes(t));
}

/** The tools with one turned on or off. */
export function withDrawTool(raw: unknown, tool: DrawTool, on: boolean): DrawTool[] {
  const tools = drawToolsOf(raw);
  return DRAW_TOOLS.filter((t) => (t === tool ? on : tools.includes(t)));
}

/** p.301's Drawn shape opacity, of the fill: the outline stays, so a shape
 * at 0 is still there to see. */
export const DRAWN_OPACITY = 0.35;

export function drawnOpacityOf(raw: unknown): number {
  const n = typeof raw === "number" ? raw
    : typeof raw === "string" && raw.trim() !== "" ? Number(raw) : Number.NaN;
  return Number.isFinite(n) ? Math.min(1, Math.max(0, n)) : DRAWN_OPACITY;
}

/** The longitude and latitude under a point of the map's frame. */
export function lonLatAt(px: number, py: number, view: View, frame: Frame): {
  lon: number; lat: number;
} {
  const h = view.w * (frame.height / frame.width);
  return { lon: view.x + (px / frame.width) * view.w, lat: -(view.y + (py / frame.height) * h) };
}


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

const AREA_OPS = [AREA_OP, POLYGON_OP, CIRCLE_OP];
const isArea = (c: Clause, property: string) => c.property === property && AREA_OPS.includes(c.op);

/** The area this property is narrowed to, read back from the clauses: a box,
 * a drawn shape, a circle, or nothing for a value that is none of them. */
export function areaOf(clauses: readonly Clause[], property: string): Area | null {
  const found = clauses.find((c) => isArea(c, property));
  if (found?.op === CIRCLE_OP) {
    const v = found.value as Partial<Circle> | undefined;
    const ok = !!v && ["lat", "lon", "radius"].every((k) => typeof v[k as keyof Circle] === "number");
    return ok ? { lat: v.lat!, lon: v.lon!, radius: v.radius! } : null;
  }
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

/** The clauses with this property's area replaced by a box, a shape or a
 * circle, or removed for `null`: one area to a property, of any kind. */
export function withArea(clauses: readonly Clause[], property: string, area: Area | null): Clause[] {
  const rest = clauses.filter((c) => !isArea(c, property));
  if (!area) return rest;
  const op = isPolygon(area) ? POLYGON_OP : isCircle(area) ? CIRCLE_OP : AREA_OP;
  return [...rest, { property, op, value: area }];
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
