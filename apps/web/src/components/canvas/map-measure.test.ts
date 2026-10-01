import { describe, expect, it } from "vitest";

import { EARTH_RADIUS_M as R } from "./map-area";
import {
  areaLabel, areaM2, cornersOf, edgeM, lengthLabel, lineLabels, lineM, measureLabels, perimeterM,
  perimeterModeOf, segmentsM,
} from "./map-measure";

const degree = (R * Math.PI) / 180;
const rad = (d: number) => (d * Math.PI) / 180;

/** ∫∫ cos(lat) d(lat) d(lon) over a triangle, by a fine midpoint grid: the
 * area on the sphere of a shape straight in longitude and latitude, from
 * its definition rather than from Green's theorem. */
function gridArea(a: [number, number], b: [number, number], c: [number, number]): number {
  const [lats, lons] = [[a[0], b[0], c[0]], [a[1], b[1], c[1]]];
  const [s, n, w, e] = [Math.min(...lats), Math.max(...lats), Math.min(...lons), Math.max(...lons)];
  const steps = 1000;
  const [dLat, dLon] = [(n - s) / steps, (e - w) / steps];
  const side = (p: number[], q: number[], x: number, y: number) =>
    (q[1]! - p[1]!) * (y - p[0]!) - (q[0]! - p[0]!) * (x - p[1]!);
  let sum = 0;
  for (let i = 0; i < steps; i++) {
    const lat = s + (i + 0.5) * dLat;
    for (let j = 0; j < steps; j++) {
      const lon = w + (j + 0.5) * dLon;
      const d = [side(a, b, lon, lat), side(b, c, lon, lat), side(c, a, lon, lat)];
      if (d.every((v) => v >= 0) || d.every((v) => v <= 0)) sum += Math.cos(rad(lat));
    }
  }
  return sum * rad(dLat) * rad(dLon) * R * R;
}

describe("the area on the ground (§575)", () => {
  it("of a rectangle is exact", () => {
    const world = { north: 90, south: -90, east: 180, west: -180 };
    expect(areaM2(world)).toBeCloseTo(4 * Math.PI * R * R, -3);
    expect(areaM2({ north: 90, south: 0, east: 180, west: -180 })).toBeCloseTo(2 * Math.PI * R * R, -3);
    expect(areaM2({ north: 1, south: 0, east: 1, west: 0 }))
      .toBeCloseTo(R * R * rad(1) * Math.sin(rad(1)), -1);
    expect(areaM2({ north: 61, south: 60, east: 11, west: 10 }))
      .toBeCloseTo(R * R * rad(1) * (Math.sin(rad(61)) - Math.sin(rad(60))), -1);
  });

  it("of a drawn shape is the same whichever way round it was drawn", () => {
    const points = [{ lat: 50, lon: 0 }, { lat: 54, lon: 0 }, { lat: 50, lon: 12 }];
    const forward = areaM2({ points });
    expect(areaM2({ points: [...points].reverse() })).toBeCloseTo(forward, -1);
    expect(areaM2({ points: [points[1]!, points[2]!, points[0]!] })).toBeCloseTo(forward, -1);
  });

  it("of a drawn shape matches the shape's own integral", () => {
    const tri = (a: [number, number], b: [number, number], c: [number, number]) =>
      areaM2({ points: [a, b, c].map(([lat, lon]) => ({ lat, lon })) });
    for (const [a, b, c] of [
      [[50, 0], [54, 0], [50, 12]],
      [[-10, 20], [30, 35], [5, 60]],
      [[60, -40], [80, 10], [65, 30]],
    ] as [number, number][][]) {
      const want = gridArea(a!, b!, c!);
      expect(Math.abs(tri(a!, b!, c!) - want) / want).toBeLessThan(2e-3);
    }
  });

  it("of a circle is its cap", () => {
    expect(areaM2({ lat: 10, lon: 20, radius: (R * Math.PI) / 2 }))
      .toBeCloseTo(2 * Math.PI * R * R, -3);
    // A small circle is very nearly flat.
    const small = areaM2({ lat: 52, lon: 5, radius: 1000 });
    expect(Math.abs(small - Math.PI * 1e6) / small).toBeLessThan(1e-6);
  });
});

describe("lengths on the ground (§575)", () => {
  it("are exact along a parallel or a meridian", () => {
    expect(edgeM({ lat: 0, lon: 0 }, { lat: 0, lon: 1 })).toBeCloseTo(degree, 6);
    expect(edgeM({ lat: 0, lon: 0 }, { lat: 1, lon: 0 })).toBeCloseTo(degree, 6);
    expect(edgeM({ lat: 60, lon: 5 }, { lat: 60, lon: 3 })).toBeCloseTo(degree, 6);
    expect(edgeM({ lat: -30, lon: 0 }, { lat: 30, lon: 0 })).toBeCloseTo(60 * degree, 5);
  });

  it("run along the edge as drawn, which is no shorter than a great circle", () => {
    const a = { lat: 10, lon: 0 };
    const b = { lat: 60, lon: 80 };
    // By a far finer trapezoid rule, for the one that edgeM uses.
    const steps = 20_000;
    let fine = 0;
    for (let n = 0; n < steps; n++) {
      const lat = rad(a.lat + ((n + 0.5) / steps) * (b.lat - a.lat));
      fine += Math.hypot(rad(b.lat - a.lat), Math.cos(lat) * rad(b.lon - a.lon)) / steps;
    }
    expect(edgeM(a, b)).toBeCloseTo(fine * R, -1);
    const p1 = rad(a.lat);
    const p2 = rad(b.lat);
    const h = Math.sin((p2 - p1) / 2) ** 2
      + Math.cos(p1) * Math.cos(p2) * Math.sin(rad(b.lon - a.lon) / 2) ** 2;
    expect(edgeM(a, b)).toBeGreaterThan(2 * R * Math.asin(Math.sqrt(h)));
  });

  it("go round a shape's edges, the closing edge last", () => {
    const box = { north: 1, south: 0, east: 1, west: 0 };
    expect(cornersOf(box)).toEqual([{ lat: 0, lon: 0 }, { lat: 0, lon: 1 }, { lat: 1, lon: 1 },
      { lat: 1, lon: 0 }]);
    const [south, east, north, west] = segmentsM(box);
    expect(south).toBeCloseTo(degree, 6);
    expect(east).toBeCloseTo(degree, 6);
    expect(north).toBeCloseTo(degree * Math.cos(rad(1)), 6);
    expect(west).toBeCloseTo(degree, 6);
    expect(perimeterM(box)).toBeCloseTo(3 * degree + degree * Math.cos(rad(1)), 5);
    const shape = { points: [{ lat: 0, lon: 0 }, { lat: 0, lon: 2 }, { lat: 3, lon: 0 }] };
    expect(segmentsM(shape)[2]).toBeCloseTo(3 * degree, 5);
  });

  it("of a circle is its circumference on the sphere", () => {
    expect(perimeterM({ lat: 0, lon: 0, radius: (R * Math.PI) / 2 })).toBeCloseTo(2 * Math.PI * R, 3);
    expect(perimeterM({ lat: 52, lon: 5, radius: 1000 })).toBeCloseTo(2 * Math.PI * 1000, 3);
    expect(cornersOf({ lat: 52, lon: 5, radius: 1000 })).toEqual([]);
  });
});

describe("what the labels say (§575)", () => {
  it("in metres under a kilometre, else in km", () => {
    expect(lengthLabel(0)).toBe("0 m");
    expect(lengthLabel(999.4)).toBe("999 m");
    expect(lengthLabel(999.6)).toBe("1 km");
    expect(lengthLabel(12_345)).toBe("12.3 km");
    expect(lengthLabel(99_960)).toBe("100 km");
    expect(lengthLabel(123_456)).toBe("123 km");
    expect(lengthLabel(1_234_567)).toBe("1,235 km");
  });

  it("in square metres under a square kilometre, else in km²", () => {
    expect(areaLabel(5000.4)).toBe("5,000 m²");
    expect(areaLabel(999_999.4)).toBe("999,999 m²");
    expect(areaLabel(999_999.6)).toBe("1 km²");
    expect(areaLabel(12_340_000)).toBe("12.3 km²");
    expect(areaLabel(1_234_500_000)).toBe("1,235 km²");
  });

  it("takes the total unless told the segments", () => {
    expect(perimeterModeOf("segments")).toBe("segments");
    expect(perimeterModeOf("total")).toBe("total");
    expect(perimeterModeOf(undefined)).toBe("total");
  });
});

describe("where the labels go (§575)", () => {
  const frame = { width: 640, height: 320 };
  // Ten pixels a degree, with (lat 50, lon -10) at the top left.
  const view = { x: -10, y: -50, w: 64 };
  const box = { north: 45, south: 40, east: 10, west: 0 };

  it("puts each segment's at its middle", () => {
    const labels = measureLabels(box, { perimeter: "segments", area: false }, view, frame);
    expect(labels.map((l) => [l.kind, l.x, l.y])).toEqual([
      ["segment", 150, 100], ["segment", 200, 75], ["segment", 150, 50], ["segment", 100, 75],
    ]);
    expect(labels[0]!.text).toBe(lengthLabel(segmentsM(box)[0]!));
  });

  it("puts the area at the centre with the perimeter under it", () => {
    const labels = measureLabels(box, { perimeter: "total", area: true }, view, frame);
    expect(labels).toEqual([
      { kind: "area", text: areaLabel(areaM2(box)), x: 150, y: 75 },
      { kind: "perimeter", text: lengthLabel(perimeterM(box)), x: 150, y: 89 },
    ]);
    expect(measureLabels(box, { perimeter: "total", area: false }, view, frame))
      .toEqual([{ kind: "perimeter", text: lengthLabel(perimeterM(box)), x: 150, y: 75 }]);
    expect(measureLabels(box, { perimeter: null, area: false }, view, frame)).toEqual([]);
  });

  it("gives a circle its circumference at its centre, even by segments", () => {
    const circle = { lat: 45, lon: 0, radius: 100_000 };
    const labels = measureLabels(circle, { perimeter: "segments", area: false }, view, frame);
    expect(labels).toEqual([
      { kind: "perimeter", text: lengthLabel(perimeterM(circle)), x: 100, y: 50 }]);
  });
});

describe("p.302's line measurements (§634)", () => {
  const line = [{ lat: 0, lon: 0 }, { lat: 0, lon: 1 }, { lat: 1, lon: 1 }];
  const view = { x: -1, y: -2, w: 4 };
  const frame = { width: 400, height: 400 };

  it("is the sum of its segments, each measured as an edge is", () => {
    expect(lineM(line)).toBeCloseTo(2 * degree, 3);
    expect(lineM([line[0]!])).toBe(0);
  });

  it("labels each segment at its middle, or the whole at the end", () => {
    const segments = lineLabels(line, "segments", view, frame);
    expect(segments.map((l) => [l.kind, l.text])).toEqual([
      ["segment", lengthLabel(degree)], ["segment", lengthLabel(degree)]]);
    expect(segments[0]).toMatchObject({ x: 150, y: 200 });
    const total = lineLabels(line, "total", view, frame);
    expect(total).toEqual([{ kind: "length", text: lengthLabel(2 * degree), x: 200, y: 88 }]);
    expect(lineLabels([line[0]!], "total", view, frame)).toEqual([]);
  });
});
