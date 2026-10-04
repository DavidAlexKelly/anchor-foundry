/** An Object Table's function-backed columns (Workshop p.221; §770). */
import { describe, expect, it } from "vitest";

import type { FunctionColumn } from "./derived-columns";
import { callKey, callValues, cellOf, columnProblem, objectParameters, versionOf } from "./function-columns";
import type { FunctionDetail, FunctionVersion } from "@/lib/types";

function version(over: Partial<FunctionVersion> = {}): FunctionVersion {
  return {
    id: "v", version: "1.0.0", inputs: ["t"], sql: "", created_at: "",
    output: { kind: "map", object_type_id: "t" },
    parameters: [
      { api_name: "shown", data_type: "object_set", object_type_id: "t", required: true },
      { api_name: "cutoff", data_type: "integer", required: true },
      { api_name: "note", data_type: "string", required: false },
    ],
    ...over,
  };
}

function fn(versions: FunctionVersion[] = [version({ version: "1.1.0" }), version()]): FunctionDetail {
  return { id: "f", api_name: "urgency", display_name: "U", description: "",
    latest_version: versions[0]?.version ?? null, created_at: "", updated_at: "", versions };
}

function column(over: Partial<FunctionColumn> = {}): FunctionColumn {
  return { api_name: "u", kind: "function", function_id: "f", version: null,
    objects_parameter: "shown", field: "", inputs: { cutoff: { value: 4 } }, ...over };
}

describe("the version a column calls", () => {
  it("is the one it names, or the newest", () => {
    expect(versionOf(fn(), null)?.version).toBe("1.1.0");
    expect(versionOf(fn(), "1.0.0")?.version).toBe("1.0.0");
    expect(versionOf(fn(), "9.0.0")).toBeUndefined();
    expect(versionOf(undefined, null)).toBeUndefined();
  });
});

describe("what a call sends", () => {
  it("is the page's keys and each input as it stands now", () => {
    const c = column({ inputs: { cutoff: { variable: "v1" }, note: { value: "x" } } });
    expect(callValues(c, ["S1", "S2"], { v1: 4 })).toEqual({
      shown: ["S1", "S2"], cutoff: 4, note: "x" });
    // A variable nothing has resolved is undefined, which JSON leaves out.
    expect(JSON.parse(JSON.stringify(callValues(c, [], {})))).toEqual({ shown: [], note: "x" });
  });

  it("is one call for columns that differ only in their field", () => {
    expect(callKey(column({ field: "a", api_name: "a" })))
      .toBe(callKey(column({ field: "b", api_name: "b" })));
    expect(callKey(column({ version: "1.0.0" }))).not.toBe(callKey(column()));
    expect(callKey(column({ inputs: { cutoff: { value: 5 } } }))).not.toBe(callKey(column()));
    expect(callKey(column({ inputs: { a: { value: 1 }, b: { value: 2 } } })))
      .toBe(callKey(column({ inputs: { b: { value: 2 }, a: { value: 1 } } })));
  });
});

describe("a row's cell", () => {
  const result = { kind: "map" as const, version: "1",
    columns: [{ name: "level", data_type: "VARCHAR" }, { name: "n", data_type: "BIGINT" }],
    entries: { S1: { level: "High", n: 3 } } };

  it("is its entry's field, or the first field when none is named", () => {
    expect(cellOf(result, "S1", "n")).toBe(3);
    expect(cellOf(result, "S1", "")).toBe("High");
    expect(cellOf(result, "S2", "n")).toBeUndefined();
    expect(cellOf(undefined, "S1", "n")).toBeUndefined();
  });
});

describe("why a column cannot be drawn", () => {
  it("has nothing to say about a column that can", () => {
    expect(columnProblem(column(), fn(), "t")).toBeNull();
  });

  it("names a missing function or version", () => {
    expect(columnProblem(column(), undefined, "t")).toBe(
      "The function this column calls does not exist.");
    expect(columnProblem(column({ version: "2.0.0" }), fn(), "t")).toBe(
      "urgency has no version 2.0.0.");
  });

  it("names a function that does not answer per object of this type", () => {
    expect(columnProblem(column(), fn([version({ output: { kind: "table" } })]), "t"))
      .toContain("does not give a value per object");
    expect(columnProblem(column(), fn(), "other")).toBe(
      "urgency gives values for another object type.");
  });

  it("needs the table's objects to go to an object set of its type", () => {
    expect(columnProblem(column({ objects_parameter: "" }), fn(), "t")).toBe(
      "Choose the parameter that receives the table's objects.");
    expect(columnProblem(column({ objects_parameter: "cutoff" }), fn(), "t")).toBe(
      "Choose the parameter that receives the table's objects.");
    const elsewhere = version({ parameters: [
      { api_name: "shown", data_type: "object_set", object_type_id: "x", required: true }] });
    expect(columnProblem(column({ inputs: {} }), fn([elsewhere]), "t")).toBe(
      "Choose the parameter that receives the table's objects.");
  });

  it("names a required input left unset, and not an optional one", () => {
    expect(columnProblem(column({ inputs: {} }), fn(), "t")).toBe(
      "cutoff needs a value or a variable.");
  });

  it("offers only object sets of the table's type for the objects", () => {
    expect(objectParameters(version(), "t").map((p) => p.api_name)).toEqual(["shown"]);
    expect(objectParameters(version(), "x")).toEqual([]);
    expect(objectParameters(undefined, "t")).toEqual([]);
  });
});
