/** A GeoJSON geometry as a page reads one (§425). */
import { describe, expect, it } from "vitest";
import {
  GEOMETRY_TYPES, GEOSHAPE_PLACEHOLDER, isGeometry, positionCount, summarise,
} from "./geoshape";

const POINT = { type: "Point" as const, coordinates: [-0.1278, 51.5074] };
const LINE = {
  type: "LineString" as const,
  coordinates: [[0, 0], [1, 1], [2, 2]],
};
const POLYGON = {
  type: "Polygon" as const,
  coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]],
};

describe("what looks like a geometry", () => {
  it("accepts every type RFC 7946 names", () => {
    for (const type of GEOMETRY_TYPES) {
      expect(isGeometry({ type }), type).toBe(true);
    }
  });

  it("refuses a value that is not one", () => {
    expect(isGeometry(null)).toBe(false);
    expect(isGeometry("Point")).toBe(false);
    expect(isGeometry({ type: "Feature" })).toBe(false);
    expect(isGeometry({ coordinates: [0, 0] })).toBe(false);
  });

  it("refuses a Feature, which is a geometry plus properties", () => {
    // The distinction the server draws too: a property that stored a Feature
    // would be an object type holding a second object type's worth of fields
    // where the schema says it holds a shape.
    expect(isGeometry({ type: "Feature", geometry: POINT })).toBe(false);
  });
});

describe("counting positions", () => {
  it("counts a bare position as one", () => {
    expect(positionCount([0, 0])).toBe(1);
    // With an altitude, which RFC 7946 allows.
    expect(positionCount([0, 0, 12])).toBe(1);
  });

  it("counts through every level of nesting", () => {
    expect(positionCount(LINE)).toBe(3);
    expect(positionCount(POLYGON)).toBe(4);
    expect(positionCount({
      type: "MultiPolygon", coordinates: [POLYGON.coordinates, POLYGON.coordinates],
    })).toBe(8);
  });

  it("counts a collection's members together", () => {
    expect(positionCount({
      type: "GeometryCollection", geometries: [POINT, LINE],
    })).toBe(4);
  });

  it("is nothing for something that is not a geometry", () => {
    expect(positionCount("Point")).toBe(0);
    expect(positionCount(null)).toBe(0);
  });
});

describe("what a cell says", () => {
  it("says nothing for a value that is not a geometry", () => {
    expect(summarise({ type: "Feature" })).toBeNull();
  });

  it("gives a point its position, labelled", () => {
    // **Labelled, because an unlabelled pair beside a geopoint's unlabelled
    // pair is the mistake this type invites.** A geopoint reads lat,lon; this
    // reads lon,lat, and the two sit in the same table.
    expect(summarise(POINT)).toBe("Point -0.1278, 51.5074 (lon, lat)");
  });

  it("gives a shape its type and its size rather than its coordinates", () => {
    // A polygon's coordinates are a paragraph, and a cell holding them would
    // push every other column off the screen.
    expect(summarise(LINE)).toBe("LineString · 3 points");
    expect(summarise(POLYGON)).toBe("Polygon · 4 points");
  });

  it("counts a collection in shapes, not in points", () => {
    // What a reader wants to know about a collection is how many things are
    // in it; the points are the members' business.
    expect(summarise({ type: "GeometryCollection", geometries: [POINT, LINE] }))
      .toBe("GeometryCollection · 2 shapes");
  });

  it("says one point rather than 1 points", () => {
    expect(summarise({ type: "MultiPoint", coordinates: [[0, 0]] }))
      .toBe("MultiPoint · 1 point");
    expect(summarise({ type: "GeometryCollection", geometries: [POINT] }))
      .toBe("GeometryCollection · 1 shape");
  });

  it("falls back to the type when a Point has no readable position", () => {
    // A geometry the server would refuse can still reach an old row, and a
    // cell that threw would take the whole table with it.
    expect(summarise({ type: "Point", coordinates: "nowhere" }))
      .toBe("Point · 0 points");
  });
});

describe("the placeholder", () => {
  it("names the order and shows it", () => {
    expect(GEOSHAPE_PLACEHOLDER).toContain("longitude, latitude");
    expect(GEOSHAPE_PLACEHOLDER).toContain('"type":"Point"');
  });

  it("uses numbers that give the order away", () => {
    // 51.5 is not a plausible longitude for the same place 0.1278 is a
    // plausible latitude for, so a reader with them the wrong way round can
    // see it. An example like [1, 2] would teach nothing.
    const [lon, lat] = JSON.parse(
      GEOSHAPE_PLACEHOLDER.slice(0, GEOSHAPE_PLACEHOLDER.indexOf("}") + 1),
    ).coordinates;
    expect(Math.abs(lat)).toBeGreaterThan(Math.abs(lon));
  });
});
