/** Chart XY's function-backed layers (Workshop p.280, p.284; §771), and the
 * inputs they share with a function column (§770). */
import { describe, expect, it } from "vitest";

import { inputValues, inputsOf, unsetRequired } from "./function-inputs";
import { functionLayerOf, gridFrom, layerProblem, pointsFrom } from "./function-layers";
import type { FunctionDetail, FunctionVersion } from "@/lib/types";

function version(over: Partial<FunctionVersion> = {}): FunctionVersion {
  return {
    id: "v", version: "1.0.0", inputs: ["t"], sql: "", created_at: "",
    output: { kind: "aggregation" },
    parameters: [{ api_name: "region", data_type: "string", required: true },
                 { api_name: "note", data_type: "string", required: false }],
    ...over,
  };
}

function fn(versions: FunctionVersion[] = [version({ version: "1.1.0" }), version()]): FunctionDetail {
  return { id: "f", api_name: "by_region", display_name: "", description: "",
    latest_version: versions[0]?.version ?? null, created_at: "", updated_at: "", versions };
}

describe("a layer's function, read from a saved chart", () => {
  it("is null for a layer over a set, and read defensively otherwise", () => {
    expect(functionLayerOf(null)).toBeNull();
    expect(functionLayerOf([])).toBeNull();
    expect(functionLayerOf({ function_id: 3 })).toBeNull();
    expect(functionLayerOf({ function_id: "f", version: "", inputs: { a: { value: 1 } } }))
      .toEqual({ function_id: "f", version: null, inputs: { a: { value: 1 } } });
    expect(functionLayerOf({ function_id: "f", version: "1.0.0" }))
      .toEqual({ function_id: "f", version: "1.0.0", inputs: {} });
  });
});

describe("a function's inputs", () => {
  it("keep only a variable or a value", () => {
    expect(inputsOf({ a: { variable: "v" }, b: { value: 0 }, c: { variable: "" }, d: 3, e: {} }))
      .toEqual({ a: { variable: "v" }, b: { value: 0 } });
    expect(inputsOf([])).toEqual({});
    expect(inputsOf(null)).toEqual({});
  });

  it("are read as they stand", () => {
    expect(inputValues({ a: { variable: "v" }, b: { value: 2 } }, { v: "north" }))
      .toEqual({ a: "north", b: 2 });
  });

  it("name a required parameter nothing feeds", () => {
    expect(unsetRequired(version(), {})).toBe("region needs a value or a variable.");
    expect(unsetRequired(version(), { region: { value: "x" } })).toBeNull();
    expect(unsetRequired(version(), {}, "region")).toBeNull();
  });
});

describe("a function's buckets as a layer", () => {
  it("draws a 2D aggregation as points", () => {
    expect(pointsFrom({ kind: "aggregation", version: "1", dimensions: 2,
      buckets: [{ key: "north", value: 40 }, { key: "south", value: 25 }] }))
      .toEqual([{ label: "north", value: 40 }, { label: "south", value: 25 }]);
    expect(pointsFrom({ kind: "aggregation", version: "1", dimensions: 3, buckets: [] })).toBeNull();
    expect(pointsFrom({ kind: "table", version: "1" })).toBeNull();
    expect(pointsFrom(undefined)).toBeNull();
  });

  it("draws a 3D aggregation as a grid, zero where a pair has no bucket", () => {
    expect(gridFrom({ kind: "aggregation", version: "1", dimensions: 3, buckets: [
      { key: "north", segment: "big", value: 1 },
      { key: "north", segment: "small", value: 2 },
      { key: "south", segment: "big", value: 3 },
    ] })).toEqual({ categories: ["north", "south"], segments: ["big", "small"],
      values: [[1, 2], [3, 0]] });
    expect(gridFrom({ kind: "aggregation", version: "1", dimensions: 2, buckets: [] })).toBeNull();
    expect(gridFrom({ kind: "map", version: "1" })).toBeNull();
    expect(gridFrom(undefined)).toBeNull();
  });
});

describe("why a layer cannot be drawn", () => {
  const layer = { function_id: "f", version: null, inputs: { region: { value: "north" } } };
  it("has nothing to say about one that can", () => {
    expect(layerProblem(layer, fn())).toBeNull();
  });

  it("names what is missing", () => {
    expect(layerProblem({ ...layer, function_id: "" }, undefined))
      .toBe("Choose the function this layer draws.");
    expect(layerProblem(layer, undefined)).toBe("The function this layer draws does not exist.");
    expect(layerProblem({ ...layer, version: "9.0.0" }, fn())).toBe("by_region has no version 9.0.0.");
    expect(layerProblem({ ...layer, version: "1.0.0" }, fn())).toBeNull();
    expect(layerProblem(layer, fn([version({ output: { kind: "map", object_type_id: "t" } })])))
      .toContain("does not return an aggregation");
    expect(layerProblem({ ...layer, inputs: {} }, fn())).toBe("region needs a value or a variable.");
  });
});
