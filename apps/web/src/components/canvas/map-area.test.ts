import { describe, expect, it } from "vitest";

import {
  AREA_OP, POLYGON_OP, areaOf, boxBetween, boxRect, closes, isDrag, isPolygon, lonLatAt,
  polygonPoints, withArea, type Box,
} from "./map-area";

const frame = { width: 640, height: 320 };
// 64 degrees across a 640px frame: ten pixels a degree, and 32 degrees tall.
const view = { x: -10, y: -50, w: 64 };

describe("the map's projection, read backwards (§550)", () => {
  it("finds the longitude and latitude under a point of the frame", () => {
    expect(lonLatAt(0, 0, view, frame)).toEqual({ lon: -10, lat: 50 });
    expect(lonLatAt(640, 320, view, frame)).toEqual({ lon: 54, lat: 18 });
    expect(lonLatAt(100, 50, view, frame)).toEqual({ lon: 0, lat: 45 });
  });

  it("draws a box where the projection puts it", () => {
    expect(boxRect({ north: 45, south: 40, east: 10, west: 0 }, view, frame))
      .toEqual({ x: 100, y: 50, width: 100, height: 50 });
  });
});

describe("a dragged box (p.302's shape-based selection)", () => {
  it("is the same whichever way it was dragged", () => {
    const box = { north: 45, south: 40, east: 10, west: 0 };
    expect(boxBetween({ lon: 0, lat: 45 }, { lon: 10, lat: 40 })).toEqual(box);
    expect(boxBetween({ lon: 10, lat: 40 }, { lon: 0, lat: 45 })).toEqual(box);
  });

  it("stops at the world's edge", () => {
    expect(boxBetween({ lon: -200, lat: 95 }, { lon: 190, lat: -100 }))
      .toEqual({ north: 90, south: -90, east: 180, west: -180 });
  });

  it("is a drag only past a few pixels each way", () => {
    expect(isDrag({ x: 0, y: 0 }, { x: 4, y: 4 })).toBe(true);
    expect(isDrag({ x: 0, y: 0 }, { x: 3, y: 40 })).toBe(false);
    expect(isDrag({ x: 0, y: 0 }, { x: 40, y: 3 })).toBe(false);
  });
});

describe("the area as a clause", () => {
  const box = { north: 45, south: 40, east: 10, west: 0 };
  const other = { property: "status", op: "eq", value: "open" };

  it("writes a within_box on the location property, replacing the last", () => {
    const once = withArea([other], "site", box);
    expect(once).toEqual([other, { property: "site", op: AREA_OP, value: box }]);
    const twice = withArea(once, "site", { ...box, north: 50 });
    expect(twice).toHaveLength(2);
    expect((areaOf(twice, "site") as Box | null)?.north).toBe(50);
    expect(withArea(twice, "site", null)).toEqual([other]);
    // Only the area: another clause on the same property is somebody else's.
    const named = { property: "site", op: "eq", value: "x" };
    expect(withArea([named], "site", box)).toEqual([
      named, { property: "site", op: AREA_OP, value: box },
    ]);
  });

  it("reads one back only when it is a whole box", () => {
    expect(areaOf([{ property: "site", op: AREA_OP, value: box }], "site")).toEqual(box);
    expect(areaOf([{ property: "site", op: AREA_OP, value: { north: 1 } }], "site")).toBeNull();
    expect(areaOf([{ property: "site", op: "eq", value: box }], "site")).toBeNull();
    expect(areaOf([{ property: "other", op: AREA_OP, value: box }], "site")).toBeNull();
  });
});

describe("a drawn shape as a clause (§571)", () => {
  const shape = { points: [{ lat: 40, lon: 0 }, { lat: 45, lon: 0 }, { lat: 40, lon: 10 }] };
  const box = { north: 45, south: 40, east: 10, west: 0 };

  it("writes a within_polygon, one area to a property of either kind", () => {
    const drawn = withArea([], "site", shape);
    expect(drawn).toEqual([{ property: "site", op: POLYGON_OP, value: shape }]);
    expect(areaOf(drawn, "site")).toEqual(shape);
    // A box after a shape replaces it, and a shape after a box.
    expect(withArea(drawn, "site", box)).toEqual([{ property: "site", op: AREA_OP, value: box }]);
    expect(withArea(withArea([], "site", box), "site", shape)).toEqual(drawn);
    expect(withArea(drawn, "site", null)).toEqual([]);
    expect(isPolygon(shape)).toBe(true);
    expect(isPolygon(box)).toBe(false);
  });

  it("reads a shape back only when it has three whole corners", () => {
    const read = (value: unknown) => areaOf([{ property: "site", op: POLYGON_OP, value }], "site");
    expect(read({ points: shape.points.slice(0, 2) })).toBeNull();
    expect(read({ points: [...shape.points.slice(0, 2), { lat: 1 }] })).toBeNull();
    expect(read({})).toBeNull();
  });

  it("places the corners on the frame", () => {
    // Ten pixels a degree: (lat 40, lon 0) is 100px in and 100px down.
    expect(polygonPoints(shape, view, frame)).toBe("100,100 100,50 200,100");
  });

  it("closes near the first corner, once there are three", () => {
    const corners = [{ x: 0, y: 0 }, { x: 50, y: 0 }, { x: 50, y: 50 }];
    expect(closes(corners, { x: 6, y: 6 })).toBe(true);
    expect(closes(corners, { x: 8, y: 8 })).toBe(false);
    expect(closes(corners.slice(0, 2), { x: 0, y: 0 })).toBe(false);
  });
});
