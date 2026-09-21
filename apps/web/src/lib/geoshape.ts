/**
 * A GeoJSON geometry, as this platform reads and writes one (§425;
 * `object-link-types` p.127; `functions` p.40).
 *
 * > "GeoShape represents any valid GeoJSON geometry, including Points,
 * > Polygons, LineStrings, and other shapes… Note that positional arguments
 * > follow **longitude, latitude** order as per the GeoJSON spec."
 *
 * **The server decides what a geoshape is; this decides what to draw.**
 * `services/property_values.py` refuses a malformed geometry on both write
 * paths, and a second validator here would be a second opinion free to
 * disagree with the one that refuses (§191). What is here instead is the
 * reading half: a summary a table cell can hold, and the coordinate order
 * said out loud in the one place a person types one.
 *
 * **The axes are the opposite way round to a geopoint**, which is the fact
 * this module exists to keep visible. A geopoint is `lat,lon`
 * (`object-link-types` p.273); a geoshape's positions are `[lon, lat]`. A
 * value with them swapped is valid, plottable, and in the wrong hemisphere —
 * so nothing here guesses, and the input says which order it wants.
 */

/** The geometry types RFC 7946 names, in its own spelling. */
export const GEOMETRY_TYPES = [
  "Point", "MultiPoint", "LineString", "MultiLineString",
  "Polygon", "MultiPolygon", "GeometryCollection",
] as const;

export type GeometryType = (typeof GEOMETRY_TYPES)[number];

export interface Geometry {
  type: GeometryType;
  coordinates?: unknown;
  geometries?: Geometry[];
}

/** Whether a value is shaped like something this module can read.
 *
 * **A shape check, not a validation.** It answers "is there a geometry here
 * to summarise", which is what a renderer needs; whether the coordinates are
 * in range is the server's answer and it has already given it by the time a
 * value reaches a page.
 */
export function isGeometry(value: unknown): value is Geometry {
  if (typeof value !== "object" || value === null) return false;
  const kind = (value as { type?: unknown }).type;
  return typeof kind === "string"
    && (GEOMETRY_TYPES as readonly string[]).includes(kind);
}

/** How many positions a geometry's coordinates hold, at any depth.
 *
 * Counted rather than derived from the type, because the same type holds
 * different amounts: a LineString of two points and one of four hundred are
 * both LineStrings, and the count is the part a reader wants. */
export function positionCount(value: unknown): number {
  if (Array.isArray(value)) {
    // A position is a flat pair or triple of numbers; anything else is a list
    // of positions, or a list of those.
    if (value.every((part) => typeof part === "number")) return 1;
    return value.reduce<number>((sum, part) => sum + positionCount(part), 0);
  }
  if (isGeometry(value)) {
    if (value.geometries) {
      return value.geometries.reduce((sum, part) => sum + positionCount(part), 0);
    }
    return positionCount(value.coordinates);
  }
  return 0;
}

/** What a table cell says about a shape.
 *
 * **Not the coordinates.** A polygon's coordinates are a paragraph, and a cell
 * that held them would push every other column off the screen — the type and
 * the size are what tell a reader whether this is the shape they meant, and
 * the value itself is one click away in the raw editor.
 *
 * A Point is the one case where the position *is* the summary, and it reads
 * `lon, lat` — labelled, because an unlabelled pair of numbers beside a
 * geopoint's unlabelled pair is the mistake this whole type invites.
 */
export function summarise(value: unknown): string | null {
  if (!isGeometry(value)) return null;
  if (value.type === "Point" && Array.isArray(value.coordinates)) {
    const [lon, lat] = value.coordinates as number[];
    if (typeof lon === "number" && typeof lat === "number") {
      return `Point ${lon}, ${lat} (lon, lat)`;
    }
  }
  const points = positionCount(value);
  if (value.type === "GeometryCollection") {
    const members = value.geometries?.length ?? 0;
    return `GeometryCollection · ${members} ${members === 1 ? "shape" : "shapes"}`;
  }
  return `${value.type} · ${points} ${points === 1 ? "point" : "points"}`;
}

/** The placeholder the one control a person types a geometry into shows.
 *
 * **A whole example rather than a format string**, because the format is JSON
 * and nobody types a format string into JSON correctly. The example is a
 * Point, and its numbers are chosen so the order is unmistakable: 0.1278 is a
 * plausible latitude and 51.5 is not a plausible longitude for the same
 * place, so a reader who has them the wrong way round can see it. */
export const GEOSHAPE_PLACEHOLDER =
  '{"type":"Point","coordinates":[-0.1278,51.5074]}  — [longitude, latitude]';
