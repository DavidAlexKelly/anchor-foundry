import { describe, expect, it } from "vitest";

import { allInside, boundsText, sameView, viewOfBounds } from "./map-view";

const aspect = 0.5;
const view = { x: -10, y: -60, w: 40 };

describe("p.304's viewport (§560)", () => {
  it("writes the view as a closed GeoJSON polygon of its corners", () => {
    expect(JSON.parse(boundsText(view, aspect))).toEqual({
      type: "Polygon",
      coordinates: [[[-10, 40], [30, 40], [30, 60], [-10, 60], [-10, 40]]],
    });
  });

  it("reads a view back from any geometry's bounding box, fitted to the frame", () => {
    expect(viewOfBounds(boundsText(view, aspect), aspect)).toEqual(view);
    // A tall box needs its height over the aspect.
    expect(viewOfBounds(JSON.stringify({ type: "LineString",
      coordinates: [[0, 0], [10, 30]] }), aspect)).toEqual({ x: 0, y: -30, w: 60 });
    expect(viewOfBounds("nope", aspect)).toBeNull();
    expect(viewOfBounds(JSON.stringify({ type: "Point", coordinates: [1, 2] }), aspect)).toBeNull();
    expect(viewOfBounds(JSON.stringify({ type: "Polygon" }), aspect)).toBeNull();
    expect(viewOfBounds("", aspect)).toBeNull();
    // A malformed position is passed over rather than spoiling the box.
    expect(viewOfBounds(JSON.stringify({ type: "MultiPoint",
      coordinates: [[0, 0], [5], [20, 10]] }), aspect)).toEqual({ x: 0, y: -10, w: 20 });
    expect(viewOfBounds(null, aspect)).toBeNull();
  });

  it("says whether every point is inside the view, edges included", () => {
    expect(allInside([{ lat: 50, lon: 0 }, { lat: 40, lon: 30 }], view, aspect)).toBe(true);
    expect(allInside([{ lat: 50, lon: 0 }, { lat: 61, lon: 0 }], view, aspect)).toBe(false);
    expect(allInside([{ lat: 50, lon: 31 }], view, aspect)).toBe(false);
    expect(allInside([{ lat: 39, lon: 0 }], view, aspect)).toBe(false);
    expect(allInside([{ lat: 50, lon: -11 }], view, aspect)).toBe(false);
    expect(allInside([], view, aspect)).toBe(true);
  });

  it("treats a view read back from its own bounds as the same view", () => {
    expect(sameView(view, { ...view, x: -10.0000001 }, aspect)).toBe(true);
    expect(sameView(view, { ...view, x: -9 }, aspect)).toBe(false);
    expect(sameView(null, view, aspect)).toBe(false);
  });
});
