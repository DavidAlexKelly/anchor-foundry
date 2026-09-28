import { describe, expect, it } from "vitest";

import {
  MAX_GEOMETRIES, geometriesOf, geometryShapes, withGeometryEarlier, withGeometrySetting, withNewGeometry,
  withoutGeometry,
} from "./map-geometry";

/** p.300's Geometry on a Map layer (§670). */

describe("a layer's geometries", () => {
  it("reads each by its own rules, and leaves out what is not one", () => {
    expect(geometriesOf([
      { id: "geometry-1", property: "area", color: "#aa3300", legend: false },
      { id: "geometry-2", property: "", color: "red" },
      { id: "geometry-1", property: "again" }, { property: "no id" }, null, "x",
    ])).toEqual([
      { id: "geometry-1", property: "area", color: "#aa3300", legend: false },
      { id: "geometry-2", property: null, color: null, legend: true },
    ]);
    expect(geometriesOf({})).toEqual([]);
    const many = Array.from({ length: MAX_GEOMETRIES + 1 }, (_, n) => ({ id: `g${n}` }));
    expect(geometriesOf(many)).toHaveLength(MAX_GEOMETRIES);
  });

  it("adds, sets, removes and moves one earlier", () => {
    const one = withNewGeometry(undefined);
    expect(one).toEqual([{ id: "geometry-1", property: null, color: null, legend: true }]);
    const two = withNewGeometry([{ id: "geometry-2" }]);
    expect(two.map((g) => g.id)).toEqual(["geometry-2", "geometry-3"]);
    const full = Array.from({ length: MAX_GEOMETRIES }, (_, n) => ({ id: `g${n}` }));
    expect(withNewGeometry(full)).toHaveLength(MAX_GEOMETRIES);
    expect(withGeometrySetting(two, "geometry-3", "property", "area")[1]!.property).toBe("area");
    expect(withGeometrySetting(two, "geometry-3", "property", "area")[0]!.property).toBeNull();
    expect(withoutGeometry(two, "geometry-2").map((g) => g.id)).toEqual(["geometry-3"]);
    expect(withGeometryEarlier(two, "geometry-3").map((g) => g.id)).toEqual(["geometry-3", "geometry-2"]);
    expect(withGeometryEarlier(two, "geometry-2").map((g) => g.id)).toEqual(["geometry-2", "geometry-3"]);
    expect(withGeometryEarlier(two, "nope").map((g) => g.id)).toEqual(["geometry-2", "geometry-3"]);
  });
});

describe("geometryShapes", () => {
  const square = { type: "Polygon", coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] };
  const objects = [
    { id: "1", primary_key: "A", properties: { area: square, name: "Alpha" } },
    { id: "2", primary_key: "B", properties: { area: "not a shape" } },
    { id: "3", primary_key: "C", properties: { area: null, name: "Gamma" } },
    { id: "4", primary_key: "D", properties: { name: "Delta" } },
    { id: "5", primary_key: "E", properties: { area: "" } },
  ];
  const geometry = { id: "geometry-1", property: "area", color: null, legend: true };

  it("is one shape per object holding a value, in the layer's colour or its own", () => {
    expect(geometryShapes("layer-1", geometry, objects, "name", "#aa3300")).toEqual([
      { id: "layer-1-geometry-1-1", label: "Alpha", value: square, color: "#aa3300" },
      // Not a geometry, still handed on, for the map to count.
      { id: "layer-1-geometry-1-2", label: "B", value: "not a shape", color: "#aa3300" },
    ]);
    expect(geometryShapes("layer-1", { ...geometry, color: "#112233" }, objects, null, null)
      .map((s) => [s.label, s.color])).toEqual([["A", "#112233"], ["B", "#112233"]]);
    // Its own colour over the layer's.
    expect(geometryShapes("layer-1", { ...geometry, color: "#112233" }, objects, null, "#aa3300")[0]!.color)
      .toBe("#112233");
  });

  it("is nothing without a property", () => {
    expect(geometryShapes("layer-1", { ...geometry, property: null }, objects, null, null)).toEqual([]);
  });
});
