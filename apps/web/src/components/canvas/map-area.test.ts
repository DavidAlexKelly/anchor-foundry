import { describe, expect, it } from "vitest";

import {
  AREA_OP, CIRCLE_OP, DRAWN_OPACITY, DRAW_TOOLS, EARTH_RADIUS_M, drawToolsOf, drawnOpacityOf,
  withDrawTool, MAX_RADIUS_M, POLYGON_OP, areaOf, boxBetween, boxRect,
  circleBetween, circlePath, circleRings, closes, distanceM, isCircle, isDrag, isPolygon, lonLatAt,
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

describe("a drawn circle (§572)", () => {
  const circle = { lat: 52, lon: 5, radius: 470_000 };
  const degree = (EARTH_RADIUS_M * Math.PI) / 180;

  it("measures on the ground, as object_sets.distance_m does", () => {
    expect(distanceM({ lat: 0, lon: 0 }, { lat: 0, lon: 1 })).toBeCloseTo(degree, 6);
    expect(distanceM({ lat: 0, lon: 0 }, { lat: 1, lon: 0 })).toBeCloseTo(degree, 6);
    expect(distanceM({ lat: 0, lon: 0 }, { lat: 0, lon: 180 })).toBeCloseTo(degree * 180, 6);
    // The server's own figure for the two rows its tests hold a circle to.
    expect(distanceM({ lat: 52, lon: 5 }, { lat: 55, lon: 10 })).toBeCloseTo(469509.72736757, 4);
    expect(distanceM({ lat: 0, lon: 179.5 }, { lat: 0, lon: -179.5 })).toBeCloseTo(degree, 6);
    // A haversine term that rounds to just over 1 (object_sets.distance_m).
    expect(distanceM({ lat: -87.5, lon: 0 }, { lat: 87.5, lon: -180 })).toBeCloseTo(degree * 180, 6);
  });

  it("is the drag from its centre out to its edge, to the metre", () => {
    expect(circleBetween({ lat: 0, lon: 0 }, { lat: 0, lon: 1 }))
      .toEqual({ lat: 0, lon: 0, radius: Math.round(degree) });
    // A centre dragged from past the map's edge is held to the world.
    expect(circleBetween({ lat: 95, lon: 190 }, { lat: 89, lon: 180 }))
      .toEqual({ lat: 90, lon: 180, radius: Math.round(degree) });
    expect(circleBetween({ lat: 0, lon: 0 }, { lat: 0, lon: 0 }).radius).toBe(1);
    expect(circleBetween({ lat: 90, lon: 0 }, { lat: -90, lon: 0 }).radius).toBe(MAX_RADIUS_M);
  });

  it("writes a within_distance, one area to a property of any kind", () => {
    const box = { north: 45, south: 40, east: 10, west: 0 };
    const drawn = withArea(withArea([], "site", box), "site", circle);
    expect(drawn).toEqual([{ property: "site", op: CIRCLE_OP, value: circle }]);
    expect(areaOf(drawn, "site")).toEqual(circle);
    expect(isCircle(circle)).toBe(true);
    expect(isCircle(box)).toBe(false);
    expect(isPolygon(circle)).toBe(false);
    const read = (value: unknown) => areaOf([{ property: "site", op: CIRCLE_OP, value }], "site");
    expect(read({ lat: 1, lon: 1 })).toBeNull();
    expect(read({ lat: 1, lon: "1", radius: 5 })).toBeNull();
    expect(read(null)).toBeNull();
    expect(read({ lat: 1, lon: 2, radius: 3, odd: true })).toEqual({ lat: 1, lon: 2, radius: 3 });
  });

  it("walks its edge the radius from the centre", () => {
    const [edge, ...more] = circleRings(circle);
    expect(more).toEqual([]);
    expect(edge).toHaveLength(90);
    for (const p of edge!) expect(distanceM(circle, p)).toBeCloseTo(circle.radius, 3);
    // Due north first: the same meridian, 470 km up.
    expect(edge![0]!.lon).toBeCloseTo(5, 9);
    expect(edge![0]!.lat).toBeGreaterThan(52);
  });

  it("keeps its edge whole across the antimeridian", () => {
    const [edge] = circleRings({ lat: 0, lon: 179, radius: 500_000 });
    const lons = edge!.map((p) => p.lon);
    expect(Math.max(...lons)).toBeGreaterThan(180);
    for (let n = 1; n < lons.length; n++) expect(Math.abs(lons[n]! - lons[n - 1]!)).toBeLessThan(1);
  });

  it("closes a circle round one pole along that pole's edge", () => {
    for (const [lat, pole] of [[80, 90], [-80, -90]] as const) {
      const [band, ...more] = circleRings({ lat, lon: 0, radius: 2_000_000 });
      expect(more).toEqual([]);
      expect(band).toHaveLength(92);
      const [a, b] = band!.slice(-2);
      expect([a!.lat, b!.lat]).toEqual([pole, pole]);
      // The band goes once round the world.
      expect(Math.abs(a!.lon - b!.lon)).toBeGreaterThan(350);
      expect(b!.lon).toBe(band![0]!.lon);
      expect(a!.lon).toBe(band![89]!.lon);
    }
  });

  it("leaves the far cap out of a circle round both poles", () => {
    const rings = circleRings({ lat: 0, lon: 0, radius: 15_000_000 });
    expect(rings).toHaveLength(2);
    expect(rings[0]).toEqual([{ lat: 90, lon: -180 }, { lat: 90, lon: 180 },
      { lat: -90, lon: 180 }, { lat: -90, lon: -180 }]);
    for (const p of rings[1]!) expect(distanceM({ lat: 0, lon: 0 }, p)).toBeCloseTo(15_000_000, 3);
  });

  it("draws each ring as a closed path on the frame", () => {
    const small = { lat: 40, lon: 0, radius: 1000 };
    const d = circlePath(small, view, frame);
    expect(d.match(/M/g)).toHaveLength(1);
    expect(d.endsWith("Z")).toBe(true);
    // The first point due north of (40, 0): 100px in, just above 100px down.
    const [x, y] = d.slice(1).split("L")[0]!.split(",").map(Number);
    expect(x).toBeCloseTo(100, 6);
    expect(y).toBeLessThan(100);
    expect(y).toBeGreaterThan(99.8);
    expect(circlePath({ lat: 0, lon: 0, radius: 15_000_000 }, view, frame).match(/M/g))
      .toHaveLength(2);
  });
});

describe("p.301's draw options and drawn shape style (§573)", () => {
  it("offers the tools named, in the toolbar's order, and all three by default", () => {
    expect(drawToolsOf(undefined)).toEqual([...DRAW_TOOLS]);
    expect(drawToolsOf(null)).toEqual(["rectangle", "polygon", "circle"]);
    expect(drawToolsOf(["circle", "rectangle", "line"])).toEqual(["rectangle", "circle"]);
    expect(drawToolsOf([])).toEqual([]);
  });

  it("turns one tool on or off, keeping the rest", () => {
    expect(withDrawTool(null, "rectangle", false)).toEqual(["polygon", "circle"]);
    expect(withDrawTool(["circle"], "rectangle", true)).toEqual(["rectangle", "circle"]);
    expect(withDrawTool(["circle"], "circle", false)).toEqual([]);
    expect(withDrawTool(["circle"], "circle", true)).toEqual(["circle"]);
  });

  it("holds the fill opacity from 0 to 1, and falls back for nothing", () => {
    expect(drawnOpacityOf(0.6)).toBe(0.6);
    expect(drawnOpacityOf("0.6")).toBe(0.6);
    expect(drawnOpacityOf(0)).toBe(0);
    expect(drawnOpacityOf(-1)).toBe(0);
    expect(drawnOpacityOf(3)).toBe(1);
    expect(drawnOpacityOf("")).toBe(DRAWN_OPACITY);
    expect(drawnOpacityOf("  ")).toBe(DRAWN_OPACITY);
    expect(drawnOpacityOf("x")).toBe(DRAWN_OPACITY);
    expect(drawnOpacityOf(undefined)).toBe(0.35);
  });
});
