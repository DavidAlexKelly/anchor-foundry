/**
 * p.301's Drawn shapes on the Workshop Map, as GeoJSON (§574).
 *
 * > "Shape output type: Control whether the GeoJSON string output of the
 * > drawn shapes variable and selected shape variable are represented as a
 * > GeoJSON feature or geometry collection. Drawn shapes: A bidirectional
 * > string variable that reflects the shapes drawn within the map interface
 * > as a GeoJSON string. On drawn shape: Configure Workshop events to trigger
 * > when a shape is drawn in the map." (p.301)
 *
 * The shapes here are the map's areas (§550, §571, §572): one drawn shape at
 * a time in p.301's single draw mode, and as of §640 several out of it, each
 * written in the order it was drawn. Written out:
 *
 * - **as features**, a FeatureCollection whose feature says which tool drew
 *   it (`properties.shape`). A circle is a Point at its centre with its
 *   `radius` in metres, the usual GeoJSON convention for a circle, so it
 *   reads back as the same circle.
 * - **as geometries**, a GeometryCollection, which has nowhere to put a
 *   radius. A circle is written as its outline, walked the way the map draws
 *   it, and reads back as a shape with that many corners.
 *
 * Read back, each shape in the text is one of the map's areas (the first
 * alone in single draw mode): a Polygon
 * (a rectangle when its feature says so), or a Point with a radius. Text
 * that is none of those is not a shape, and changes nothing.
 *
 * Pure.
 */

import {
  MAX_POLYGON_POINTS, MAX_RADIUS_M, MAX_SHAPES, circleRings, isCircle, isPolygon, type Area,
  type Box,
} from "./map-area";

export const SHAPE_OUTPUTS = ["features", "geometries"] as const;
export type ShapeOutput = (typeof SHAPE_OUTPUTS)[number];

export function shapeOutputOf(raw: unknown): ShapeOutput {
  return raw === "geometries" ? "geometries" : "features";
}

type Position = [number, number];
type Geometry =
  | { type: "Polygon"; coordinates: Position[][] }
  | { type: "Point"; coordinates: Position }
  | { type: "LineString"; coordinates: Position[] };

/** p.301's drawn line (§634): its points in order. It encloses nothing, so it
 * is never the map's area; it lives in the Drawn shapes text alone. */
export type Line = { lat: number; lon: number }[];
type Feature = { type: "Feature"; geometry: Geometry; properties: Record<string, unknown> };

const round = (n: number) => Math.round(n * 1e6) / 1e6;
const closed = (ring: Position[]): Position[] => [...ring, ring[0]!];

function ringsOf(area: Area): Position[][] {
  if (isPolygon(area)) return [closed(area.points.map((p) => [p.lon, p.lat]))];
  if (isCircle(area)) {
    return circleRings(area).map((ring) => closed(ring.map((p) => [round(p.lon), round(p.lat)])));
  }
  const { north, south, east, west } = area;
  return [closed([[west, south], [east, south], [east, north], [west, north]])];
}

function featureOf(area: Area): Feature {
  if (isCircle(area)) {
    return {
      type: "Feature",
      geometry: { type: "Point", coordinates: [area.lon, area.lat] },
      properties: { shape: "circle", radius: area.radius },
    };
  }
  return {
    type: "Feature",
    geometry: { type: "Polygon", coordinates: ringsOf(area) },
    properties: { shape: isPolygon(area) ? "polygon" : "rectangle" },
  };
}

const listOf = (areas: Area | readonly Area[] | null): readonly Area[] =>
  !areas ? [] : Array.isArray(areas) ? areas : [areas as Area];

/** The map's drawn shapes as p.301's GeoJSON text, in the order they were
 * drawn, or "" for none. */
export function shapesText(areas: Area | readonly Area[] | null, output: ShapeOutput): string {
  const drawn = listOf(areas);
  if (drawn.length === 0) return "";
  if (output === "geometries") {
    return JSON.stringify({
      type: "GeometryCollection",
      geometries: drawn.map((area) => ({ type: "Polygon", coordinates: ringsOf(area) })),
    });
  }
  return JSON.stringify({ type: "FeatureCollection", features: drawn.map(featureOf) });
}

/** A drawn line as p.301's GeoJSON text, or "" for none. */
export function lineText(line: Line | null, output: ShapeOutput): string {
  if (!line || line.length < 2) return "";
  const geometry: Geometry = {
    type: "LineString", coordinates: line.map((p) => [round(p.lon), round(p.lat)]),
  };
  if (output === "geometries") {
    return JSON.stringify({ type: "GeometryCollection", geometries: [geometry] });
  }
  return JSON.stringify({ type: "FeatureCollection", features: [
    { type: "Feature", geometry, properties: { shape: "line" } }] });
}

const isNumber = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);
const position = (p: unknown): Position | null =>
  Array.isArray(p) && p.length >= 2 && isNumber(p[0]) && isNumber(p[1])
    && Math.abs(p[0]) <= 180 && Math.abs(p[1]) <= 90 ? [p[0], p[1]] : null;

type Found = { geometry: unknown; properties: Record<string, unknown> };

/** The geometries in GeoJSON, in order, each with the properties of the
 * feature that holds it. */
function shapesIn(json: unknown): Found[] {
  if (!json || typeof json !== "object") return [];
  const g = json as { type?: unknown; features?: unknown; geometries?: unknown; geometry?: unknown;
    properties?: unknown };
  if (g.type === "FeatureCollection") {
    return Array.isArray(g.features) ? g.features.flatMap(shapesIn) : [];
  }
  if (g.type === "GeometryCollection") {
    return Array.isArray(g.geometries) ? g.geometries.flatMap(shapesIn) : [];
  }
  if (g.type === "Feature") {
    const properties = g.properties && typeof g.properties === "object"
      ? g.properties as Record<string, unknown> : {};
    return g.geometry ? [{ geometry: g.geometry, properties }] : [];
  }
  return [{ geometry: json, properties: {} }];
}

/** GeoJSON text, parsed, or undefined for text that is not JSON. Blank text
 * fails to parse like any other (a separate check for it survived the sweep
 * as equivalent). */
function parsed(text: unknown): unknown {
  if (typeof text !== "string") return undefined;
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

/** p.301's GeoJSON text as the map's areas (§640): every shape in it the map
 * can draw, in order. A line, or anything else that is not an area, is left
 * out rather than refusing the rest. */
export function areasOfShapes(text: unknown): Area[] {
  return shapesIn(parsed(text)).flatMap((found) => {
    const area = areaOfShape(found);
    return area ? [area] : [];
  });
}

function areaOfShape(found: Found): Area | null {
  const geometry = found.geometry as { type?: unknown; coordinates?: unknown };
  if (geometry.type === "Point") {
    const at = position(geometry.coordinates);
    const radius = found.properties.radius;
    if (!at || !isNumber(radius) || radius <= 0 || radius > MAX_RADIUS_M) return null;
    return { lon: at[0], lat: at[1], radius };
  }
  if (geometry.type !== "Polygon" || !Array.isArray(geometry.coordinates)) return null;
  const outer = geometry.coordinates[0];
  if (!Array.isArray(outer)) return null;
  const ring = outer.map(position);
  if (ring.some((p) => p === null)) return null;
  const points = (ring as Position[]).slice();
  const [first, last] = [points[0], points[points.length - 1]];
  if (points.length > 1 && first![0] === last![0] && first![1] === last![1]) points.pop();
  if (points.length < 3 || points.length > MAX_POLYGON_POINTS) return null;
  // `object_sets.parse_polygon`'s refusal: an outline wider than half the
  // world does not say which way round it goes.
  const lons = points.map((p) => p[0]);
  if (Math.max(...lons) - Math.min(...lons) > 180) return null;
  if (found.properties.shape === "rectangle") {
    const lats = points.map((p) => p[1]);
    const box: Box = {
      north: Math.max(...lats), south: Math.min(...lats),
      east: Math.max(...lons), west: Math.min(...lons),
    };
    return box;
  }
  return { points: points.map(([lon, lat]) => ({ lat, lon })) };
}

/** p.301's GeoJSON text as a drawn line: its first shape when that is a
 * LineString of at least two points the map can place, or null. */
export function lineOfShapes(text: unknown): Line | null {
  const found = shapesIn(parsed(text))[0];
  const geometry = found?.geometry as { type?: unknown; coordinates?: unknown } | undefined;
  if (!geometry || geometry.type !== "LineString" || !Array.isArray(geometry.coordinates)) {
    return null;
  }
  const points = geometry.coordinates.map(position);
  if (points.length < 2 || points.length > MAX_POLYGON_POINTS || points.some((p) => !p)) {
    return null;
  }
  return (points as Position[]).map(([lon, lat]) => ({ lat, lon }));
}

/** What the map writes when its area and its drawn shapes variable disagree:
 * whichever of the two changed since it last looked wins. On first look, a
 * shape the variable already holds is drawn onto a map with no area, which is
 * how an author's default shape arrives; otherwise the area is written out. */
export type ShapesSync =
  | { write: "area"; areas: Area[] }
  | { write: "shapes"; text: string }
  | null;

/** `single` is p.301's single draw mode (§640): the map draws only the first
 * of the shapes the variable holds, and writes that one back. */
export function syncShapes(
  before: { area: string; shapes: string } | null,
  now: { areas: readonly Area[]; shapes: string },
  output: ShapeOutput,
  single = true,
): ShapesSync {
  const areaText = shapesText(now.areas, output);
  if (areaText === now.shapes) return null;
  const none = now.areas.length === 0;
  // A drawn line with no area agrees with itself (§634): a line encloses
  // nothing, so the map having no area is what it means.
  if (none && lineOfShapes(now.shapes)) return null;
  const shapesMoved = before === null ? none : before.shapes !== now.shapes;
  const areaMoved = before !== null && before.area !== areaText;
  if (shapesMoved && !areaMoved) {
    const areas = areasOfShapes(now.shapes).slice(0, single ? 1 : MAX_SHAPES);
    // Text that is no shape clears the area only when it is empty; anything
    // else unreadable is left alone rather than wiping what was drawn.
    if (areas.length > 0 || !now.shapes.trim()) return { write: "area", areas };
    return null;
  }
  return { write: "shapes", text: areaText };
}
