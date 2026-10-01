import { describe, expect, it } from "vitest";

import {
  areasOfShapes, lineOfShapes, lineText, shapeOutputOf, shapesText, syncShapes,
} from "./map-drawn";
import { distanceM } from "./map-area";

const box = { north: 52, south: 48, east: 3, west: -1 };
const shape = { points: [{ lat: 50, lon: 0 }, { lat: 54, lon: 0 }, { lat: 50, lon: 12 }] };
const circle = { lat: 52, lon: 5, radius: 470_000 };
// The first shape in the text the map can draw, as a map in single draw mode
// reads it.
const areaOfShapes = (text: unknown) => areasOfShapes(text)[0] ?? null;

describe("the drawn shape as GeoJSON (§574)", () => {
  it("writes a feature saying which tool drew it", () => {
    expect(JSON.parse(shapesText(box, "features"))).toEqual({
      type: "FeatureCollection",
      features: [{
        type: "Feature",
        geometry: { type: "Polygon",
          coordinates: [[[-1, 48], [3, 48], [3, 52], [-1, 52], [-1, 48]]] },
        properties: { shape: "rectangle" },
      }],
    });
    expect(JSON.parse(shapesText(shape, "features")).features[0]).toEqual({
      type: "Feature",
      geometry: { type: "Polygon", coordinates: [[[0, 50], [0, 54], [12, 50], [0, 50]]] },
      properties: { shape: "polygon" },
    });
    expect(JSON.parse(shapesText(circle, "features")).features[0]).toEqual({
      type: "Feature",
      geometry: { type: "Point", coordinates: [5, 52] },
      properties: { shape: "circle", radius: 470_000 },
    });
  });

  it("writes geometries, a circle as its outline", () => {
    expect(JSON.parse(shapesText(shape, "geometries"))).toEqual({
      type: "GeometryCollection",
      geometries: [{ type: "Polygon", coordinates: [[[0, 50], [0, 54], [12, 50], [0, 50]]] }],
    });
    const [ring] = JSON.parse(shapesText(circle, "geometries")).geometries[0].coordinates;
    expect(ring).toHaveLength(91);
    expect(ring[90]).toEqual(ring[0]);
    for (const [lon, lat] of ring) expect(distanceM(circle, { lat, lon })).toBeCloseTo(470_000, -1);
  });

  it("writes nothing for no shape", () => {
    expect(shapesText(null, "features")).toBe("");
    expect(shapesText(null, "geometries")).toBe("");
  });

  it("reads back what it writes", () => {
    for (const area of [box, shape, circle]) {
      expect(areaOfShapes(shapesText(area, "features"))).toEqual(area);
    }
    expect(areaOfShapes(shapesText(shape, "geometries"))).toEqual(shape);
    // A geometry has nowhere for a radius: a circle comes back as its outline.
    const outline = areaOfShapes(shapesText(circle, "geometries"));
    expect(outline && "points" in outline && outline.points).toHaveLength(90);
  });

  it("reads a bare geometry, a lone feature and the first of many", () => {
    const polygon = { type: "Polygon", coordinates: [[[0, 50], [0, 54], [12, 50]]] };
    expect(areaOfShapes(JSON.stringify(polygon))).toEqual(shape);
    expect(areaOfShapes(JSON.stringify({ type: "Feature", geometry: polygon, properties: null })))
      .toEqual(shape);
    expect(areaOfShapes(JSON.stringify({ type: "Feature", geometry: polygon,
      properties: { shape: "rectangle" } }))).toEqual({ north: 54, south: 50, east: 12, west: 0 });
    expect(areaOfShapes(JSON.stringify({ type: "GeometryCollection", geometries: [
      polygon, { type: "Point", coordinates: [0, 0] }] }))).toEqual(shape);
    expect(areaOfShapes(JSON.stringify({ type: "FeatureCollection", features: [
      { type: "Feature", geometry: { type: "Point", coordinates: [5, 52] },
        properties: { radius: 1000 } },
      { type: "Feature", geometry: polygon, properties: {} }] })))
      .toEqual({ lat: 52, lon: 5, radius: 1000 });
  });

  it("reads nothing from what is not a shape the map can draw", () => {
    const read = (json: unknown) => areaOfShapes(JSON.stringify(json));
    expect(areaOfShapes("")).toBeNull();
    expect(areaOfShapes("   ")).toBeNull();
    expect(areaOfShapes("{nope")).toBeNull();
    expect(areaOfShapes(42)).toBeNull();
    expect(read(null)).toBeNull();
    expect(read("a string")).toBeNull();
    expect(read({ type: "FeatureCollection", features: [] })).toBeNull();
    expect(read({ type: "FeatureCollection" })).toBeNull();
    expect(read({ type: "GeometryCollection", geometries: [] })).toBeNull();
    expect(read({ type: "Feature", geometry: null })).toBeNull();
    // A point with no radius is a place, not a circle.
    expect(read({ type: "Point", coordinates: [5, 52] })).toBeNull();
    expect(read({ type: "Feature", geometry: { type: "Point", coordinates: [5, 52] },
      properties: { radius: 0 } })).toBeNull();
    expect(read({ type: "Feature", geometry: { type: "Point", coordinates: [5, 52] },
      properties: { radius: 20_000_001 } })).toBeNull();
    expect(read({ type: "Feature", geometry: { type: "Point", coordinates: [5, 91] },
      properties: { radius: 5 } })).toBeNull();
    expect(read({ type: "Feature", geometry: { type: "Point", coordinates: [5, 52] },
      properties: { radius: "5" } })).toBeNull();
    expect(read({ type: "LineString", coordinates: [[0, 0], [1, 1]] })).toBeNull();
    expect(read({ type: "Polygon", coordinates: [[[0, 0], [1, 1], [0, 0]]] })).toBeNull();
    expect(read({ type: "Polygon", coordinates: [[[0, 0], [1, 1], [2, "x"]]] })).toBeNull();
    expect(read({ type: "Polygon", coordinates: [[[0, 0], [1, 1], [181, 0]]] })).toBeNull();
    expect(read({ type: "Polygon", coordinates: "x" })).toBeNull();
    expect(read({ type: "Polygon", coordinates: ["x"] })).toBeNull();
    // Wider than half the world, which object_sets.parse_polygon refuses.
    expect(read({ type: "Polygon", coordinates: [[[-100, 0], [100, 0], [0, 10]]] })).toBeNull();
    const many = Array.from({ length: 101 }, (_, n) => [n / 10, (n % 2) / 10]);
    expect(read({ type: "Polygon", coordinates: [many] })).toBeNull();
    expect(read({ type: "Polygon", coordinates: [many.slice(0, 100)] })).not.toBeNull();
  });

  it("takes features unless told geometries", () => {
    expect(shapeOutputOf("geometries")).toBe("geometries");
    expect(shapeOutputOf("features")).toBe("features");
    expect(shapeOutputOf(undefined)).toBe("features");
    expect(shapeOutputOf("feature")).toBe("features");
  });
});

describe("keeping the area and the variable in step (§574)", () => {
  const text = shapesText(shape, "features");
  const circleText = shapesText(circle, "features");

  it("does nothing when they agree", () => {
    expect(syncShapes(null, { areas: [shape], shapes: text }, "features")).toBeNull();
    expect(syncShapes(null, { areas: [], shapes: "" }, "features")).toBeNull();
  });

  it("draws a shape the variable already holds onto a map with none", () => {
    expect(syncShapes(null, { areas: [], shapes: circleText }, "features"))
      .toEqual({ write: "area", areas: [circle] });
    // Unreadable text is left alone.
    expect(syncShapes(null, { areas: [], shapes: "{nope" }, "features")).toBeNull();
  });

  it("writes the area out when the map starts with one", () => {
    expect(syncShapes(null, { areas: [shape], shapes: circleText }, "features"))
      .toEqual({ write: "shapes", text });
    expect(syncShapes(null, { areas: [shape], shapes: "" }, "features"))
      .toEqual({ write: "shapes", text });
  });

  it("lets whichever moved win", () => {
    const seen = { area: text, shapes: text };
    // Something wrote the variable: the map draws it.
    expect(syncShapes(seen, { areas: [shape], shapes: circleText }, "features"))
      .toEqual({ write: "area", areas: [circle] });
    // Something cleared the variable: the map clears its area.
    expect(syncShapes(seen, { areas: [shape], shapes: "" }, "features"))
      .toEqual({ write: "area", areas: [] });
    // Something wrote the area (a reset, say): the variable follows.
    expect(syncShapes(seen, { areas: [circle], shapes: text }, "features"))
      .toEqual({ write: "shapes", text: circleText });
    expect(syncShapes(seen, { areas: [], shapes: text }, "features"))
      .toEqual({ write: "shapes", text: "" });
  });

  it("leaves the area alone for text that is no shape", () => {
    const seen = { area: text, shapes: text };
    expect(syncShapes(seen, { areas: [shape], shapes: "{nope" }, "features")).toBeNull();
  });

  it("lets the area win when both moved at once", () => {
    const seen = { area: text, shapes: text };
    expect(syncShapes(seen, { areas: [circle], shapes: "" }, "features"))
      .toEqual({ write: "shapes", text: circleText });
  });

  it("writes in the output asked for", () => {
    expect(syncShapes(null, { areas: [shape], shapes: "" }, "geometries"))
      .toEqual({ write: "shapes", text: shapesText(shape, "geometries") });
  });
});

describe("several drawn shapes (§640)", () => {
  const all = shapesText([box, shape, circle], "features");

  it("writes each shape in the order it was drawn, and reads them all back", () => {
    expect(JSON.parse(all).features.map((f: { properties: { shape: string } }) =>
      f.properties.shape)).toEqual(["rectangle", "polygon", "circle"]);
    expect(areasOfShapes(all)).toEqual([box, shape, circle]);
    const geometries = shapesText([box, shape], "geometries");
    expect(JSON.parse(geometries).geometries).toHaveLength(2);
    expect(areasOfShapes(geometries)).toEqual([
      { points: [{ lat: 48, lon: -1 }, { lat: 48, lon: 3 }, { lat: 52, lon: 3 }, { lat: 52, lon: -1 }] },
      shape,
    ]);
    // One shape, given alone or in a list, is the same text.
    expect(shapesText([shape], "features")).toBe(shapesText(shape, "features"));
    expect(shapesText([], "features")).toBe("");
  });

  it("leaves out what is not an area, and keeps the rest", () => {
    const line = { type: "Feature", geometry: { type: "LineString", coordinates: [[0, 0], [1, 1]] },
      properties: { shape: "line" } };
    const text = JSON.stringify({ type: "FeatureCollection", features: [
      line, null, JSON.parse(shapesText(circle, "features")).features[0]] });
    expect(areasOfShapes(text)).toEqual([circle]);
    expect(areasOfShapes("{nope")).toEqual([]);
    expect(areasOfShapes(7)).toEqual([]);
  });

  it("draws them all out of single draw mode, and the first in it", () => {
    expect(syncShapes(null, { areas: [], shapes: all }, "features", false))
      .toEqual({ write: "area", areas: [box, shape, circle] });
    expect(syncShapes(null, { areas: [], shapes: all }, "features"))
      .toEqual({ write: "area", areas: [box] });
    // They agree once the map holds what the text says.
    expect(syncShapes(null, { areas: [box, shape, circle], shapes: all }, "features", false))
      .toBeNull();
  });

  it("draws at most the shapes one filter holds", () => {
    const many = shapesText(Array.from({ length: 21 }, (_, n) => ({ ...circle, radius: n + 1 })),
      "features");
    const sync = syncShapes(null, { areas: [], shapes: many }, "features", false);
    expect(sync?.write === "area" && sync.areas.map((a) => (a as typeof circle).radius))
      .toEqual(Array.from({ length: 20 }, (_, n) => n + 1));
  });
});

describe("p.301's drawn line (§634)", () => {
  const line = [{ lat: 50, lon: 0 }, { lat: 51.5, lon: -0.1234567 }, { lat: 52, lon: 4 }];

  it("is a LineString feature, or a bare geometry, and reads back as itself", () => {
    const features = JSON.parse(lineText(line, "features"));
    expect(features).toEqual({ type: "FeatureCollection", features: [{
      type: "Feature", properties: { shape: "line" },
      geometry: { type: "LineString",
        coordinates: [[0, 50], [-0.123457, 51.5], [4, 52]] } }] });
    const geometries = JSON.parse(lineText(line, "geometries"));
    expect(geometries.type).toBe("GeometryCollection");
    expect(geometries.geometries[0].type).toBe("LineString");
    expect(lineOfShapes(lineText(line, "geometries"))).toEqual(
      [{ lat: 50, lon: 0 }, { lat: 51.5, lon: -0.123457 }, { lat: 52, lon: 4 }]);
  });

  it("is no line with fewer than two points", () => {
    expect(lineText([line[0]!], "features")).toBe("");
    expect(lineText(null, "features")).toBe("");
    expect(lineOfShapes(JSON.stringify({ type: "LineString", coordinates: [[0, 50]] }))).toBeNull();
  });

  it("reads only a line the map can place", () => {
    expect(lineOfShapes("not json")).toBeNull();
    expect(lineOfShapes(7)).toBeNull();
    expect(lineOfShapes(shapesText(box, "features"))).toBeNull();
    expect(lineOfShapes(JSON.stringify({ type: "LineString",
      coordinates: [[0, 50], [200, 50]] }))).toBeNull();
    expect(lineOfShapes(JSON.stringify({ type: "LineString",
      coordinates: Array.from({ length: 101 }, (_, n) => [n / 10, 50]) }))).toBeNull();
    // Points in a row are not a line.
    expect(lineOfShapes(JSON.stringify({ type: "MultiPoint",
      coordinates: [[0, 50], [1, 51]] }))).toBeNull();
    // Not an area, so a line never selects.
    expect(areaOfShapes(lineText(line, "features"))).toBeNull();
  });

  it("agrees with a map that has no area, and yields to one that has", () => {
    const text = lineText(line, "features");
    expect(syncShapes({ area: "", shapes: "" }, { areas: [], shapes: text }, "features"))
      .toBeNull();
    expect(syncShapes(null, { areas: [], shapes: text }, "features")).toBeNull();
    // The line that has just replaced an area: the area went as the line came,
    // and the line is what stays, not the empty text the area now is.
    expect(syncShapes({ area: shapesText(box, "features"), shapes: shapesText(box, "features") },
      { areas: [], shapes: text }, "features")).toBeNull();
    // An area drawn since wins, as any drawn shape does.
    expect(syncShapes({ area: "", shapes: text }, { areas: [box], shapes: text }, "features"))
      .toEqual({ write: "shapes", text: shapesText(box, "features") });
  });
});
