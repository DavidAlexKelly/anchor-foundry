/** A GeoJSON geometry, drawn on the map (§426; `object-views` p.11). */
import { describe, expect, it } from "vitest";
import {
  ASPECT, HEIGHT, WIDTH, boundsOf, onScreen, pathsFor, place,
} from "./map-shapes";
import type { MapView } from "./map";

/** The whole world, which is what `fitView` returns for nothing. */
const WORLD: MapView = { x: -180, y: -90, w: 360 };

const POINT = { type: "Point", coordinates: [0, 0] };
const LINE = { type: "LineString", coordinates: [[-90, 45], [90, 45]] };
/** A square with a square hole in it — the one shape that tells a one-path
 *  polygon from a two-path one. */
const HOLED = {
  type: "Polygon",
  coordinates: [
    [[-10, -10], [10, -10], [10, 10], [-10, 10], [-10, -10]],
    [[-5, -5], [5, -5], [5, 5], [-5, 5], [-5, -5]],
  ],
};

describe("the projection", () => {
  it("is the map's own", () => {
    // These two numbers are the drawing surface, restated here because
    // `map.tsx` exports its view rather than its size. Held against each
    // other so a change to one is a failure rather than a drift.
    expect(WIDTH).toBe(640);
    expect(HEIGHT).toBe(340);
    expect(ASPECT).toBe(HEIGHT / WIDTH);
  });

  it("puts 0,0 in the middle of a world view", () => {
    const at = place([0, 0], WORLD);
    expect(at.x).toBeCloseTo(WIDTH / 2);
    // A world view is taller than the surface, so the vertical middle is the
    // middle of the *view* rather than of the latitudes.
    expect(at.y).toBeCloseTo((90 / (360 * ASPECT)) * HEIGHT);
  });

  it("reads longitude first", () => {
    // **The one thing worth a sentence here**: a geoshape's positions are
    // [lon, lat] and a geopoint's are lat,lon, and this pair is positional so
    // nothing names it. East of Greenwich is right of centre; north is above.
    const east = place([90, 0], WORLD);
    const north = place([0, 45], WORLD);
    expect(east.x).toBeGreaterThan(place([0, 0], WORLD).x);
    expect(east.y).toBeCloseTo(place([0, 0], WORLD).y);
    expect(north.y).toBeLessThan(place([0, 0], WORLD).y);
    expect(north.x).toBeCloseTo(place([0, 0], WORLD).x);
  });

  it("moves with the view", () => {
    const zoomed: MapView = { x: -10, y: -10, w: 20 };
    expect(place([0, 0], zoomed).x).toBeCloseTo(WIDTH / 2);
  });
});

describe("what a geometry draws as", () => {
  it("draws nothing for a value that is not a geometry", () => {
    expect(pathsFor(null, WORLD)).toEqual([]);
    expect(pathsFor({ type: "Feature" }, WORLD)).toEqual([]);
  });

  it("fills a polygon and does not fill a line", () => {
    expect(pathsFor(HOLED, WORLD)[0]!.filled).toBe(true);
    expect(pathsFor(LINE, WORLD)[0]!.filled).toBe(false);
  });

  it("closes a polygon's subpaths and leaves a line open", () => {
    expect(pathsFor(HOLED, WORLD)[0]!.d).toContain("Z");
    expect(pathsFor(LINE, WORLD)[0]!.d).not.toContain("Z");
  });

  it("puts both rings of a holed polygon in one path", () => {
    // **The assertion the hole depends on.** Two paths draw a filled island
    // inside the lake; one path with two closed subpaths lets `evenodd` cut
    // it out.
    const drawn = pathsFor(HOLED, WORLD);
    expect(drawn).toHaveLength(1);
    expect(drawn[0]!.d.match(/Z/g)).toHaveLength(2);
    expect(drawn[0]!.d.match(/M /g)).toHaveLength(2);
  });

  it("draws each part of a multi-geometry", () => {
    expect(pathsFor({
      type: "MultiPolygon",
      coordinates: [HOLED.coordinates, HOLED.coordinates],
    }, WORLD)).toHaveLength(2);
    expect(pathsFor({
      type: "MultiLineString", coordinates: [LINE.coordinates, LINE.coordinates],
    }, WORLD)).toHaveLength(2);
    expect(pathsFor({
      type: "MultiPoint", coordinates: [[0, 0], [1, 1], [2, 2]],
    }, WORLD)).toHaveLength(3);
  });

  it("draws a collection's members, each the way its own type draws", () => {
    // One value, two drawings — which is why this returns a list.
    const drawn = pathsFor({
      type: "GeometryCollection", geometries: [HOLED, LINE],
    }, WORLD);
    expect(drawn.map((s) => s.filled)).toEqual([true, false]);
  });

  it("gives a point a mark of its own rather than a pin", () => {
    // The pin layer clusters, and a shape's point is part of a shape rather
    // than a thing to count with the others.
    const drawn = pathsFor(POINT, WORLD);
    expect(drawn).toHaveLength(1);
    expect(drawn[0]!.filled).toBe(true);
    expect(drawn[0]!.d.match(/L /g)).toHaveLength(3);
  });

  it("gives a point's mark a size, not a zero-radius diamond", () => {
    // **A sweep found this**: a diamond of radius 0 still has four segments
    // and the same centre, so every check on its *shape* passed while it drew
    // nothing at all — §214's invisible control, in path data.
    const d = pathsFor(POINT, WORLD)[0]!.d;
    const xs = [...d.matchAll(/(-?[\d.]+) (-?[\d.]+)/g)].map((m) => Number(m[1]));
    const ys = [...d.matchAll(/(-?[\d.]+) (-?[\d.]+)/g)].map((m) => Number(m[2]));
    expect(Math.max(...xs) - Math.min(...xs)).toBeGreaterThan(1);
    expect(Math.max(...ys) - Math.min(...ys)).toBeGreaterThan(1);
  });

  it("labels a shape at a position on it, not at a centroid", () => {
    // A centroid falls outside a crescent, and a label in the sea beside the
    // bay it names is worse than one on the coast.
    const drawn = pathsFor(HOLED, WORLD);
    expect(drawn[0]!.at).toEqual(place([-10, -10], WORLD));
  });

  it("draws nothing for a geometry with no positions", () => {
    expect(pathsFor({ type: "Polygon", coordinates: [] }, WORLD)).toEqual([]);
    expect(pathsFor({ type: "LineString", coordinates: [] }, WORLD)).toEqual([]);
  });
});

describe("the bounds of a geometry", () => {
  it("covers every position", () => {
    expect(boundsOf(HOLED)).toEqual({
      minLon: -10, maxLon: 10, minLat: -10, maxLat: 10,
    });
  });

  it("covers a collection's members together", () => {
    expect(boundsOf({ type: "GeometryCollection", geometries: [POINT, LINE] }))
      .toEqual({ minLon: -90, maxLon: 90, minLat: 0, maxLat: 45 });
  });

  it("is nothing rather than a point in the ocean", () => {
    // A caller with no bounds keeps the view it had; one handed {0,0,0,0}
    // would jump to the middle of the Atlantic.
    expect(boundsOf({ type: "Polygon", coordinates: [] })).toBeNull();
    expect(boundsOf("nowhere")).toBeNull();
  });
});

describe("whether a shape is on screen", () => {
  it("says yes for a shape in the view", () => {
    expect(onScreen(HOLED, WORLD)).toBe(true);
  });

  it("says no for one panned away from", () => {
    // The whole reason the count exists: "no shape here" and "you have panned
    // away from it" look identical otherwise.
    expect(onScreen(HOLED, { x: 100, y: -10, w: 20 })).toBe(false);
  });

  it("says yes for one the view only overlaps", () => {
    // Half a polygon is still something to see, and clipping the coordinates
    // would change the outline the moment somebody panned.
    expect(onScreen(HOLED, { x: 5, y: -10, w: 20 })).toBe(true);
  });

  it("says no for a geometry with nothing in it", () => {
    expect(onScreen({ type: "Polygon", coordinates: [] }, WORLD)).toBe(false);
  });

  it("checks latitude as well as longitude", () => {
    // The negative control for the axis a y-flip makes easy to get wrong: a
    // view over the far north does not contain a shape at the equator.
    expect(onScreen(HOLED, { x: -10, y: -85, w: 20 })).toBe(false);
  });
});
