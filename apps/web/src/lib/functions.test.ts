/** Writing and calling a function (§769), mirroring the server's refusals. */
import { describe, expect, it } from "vitest";

import type { FunctionVersion } from "@/lib/types";
import {
  blankDraft, blankParameter, bodyOf, compareVersions, draftOf, draftProblem, nextVersion,
  parametersUsed, resultLine, valuesFor, versionKey,
} from "./functions";

describe("versions (p.49-50)", () => {
  it("orders as the server does, a prerelease before its release", () => {
    const order = ["0.1.0", "1.0.0-rc1", "1.0.0-rc2", "1.0.0", "1.0.1", "1.2.0", "1.10.0", "2.0.0"];
    expect([...order].reverse().sort(compareVersions)).toEqual(order);
    expect(compareVersions("1.0.0", "1.0.0")).toBe(0);
    for (const bad of ["1", "1.0", "v1.0.0", "01.0.0", "1.0.0-", ""]) {
      expect(versionKey(bad), bad).toBeNull();
    }
  });

  it("suggests the next patch, or the release a prerelease led to", () => {
    expect(nextVersion("1.2.3")).toBe("1.2.4");
    expect(nextVersion("1.0.0-rc1")).toBe("1.0.0");
    expect(nextVersion("nonsense")).toBe("");
  });
});

describe("what a version may be saved as", () => {
  const draft = () => ({ ...blankDraft(), sql: "SELECT 1" });

  it("is fine as it starts once it has a query", () => {
    expect(draftProblem(draft(), null)).toBeNull();
    expect(draftProblem(blankDraft(), null)).toBe("Write the query.");
    expect(draftProblem({ ...draft(), sql: "  " }, null)).toBe("Write the query.");
  });

  it("names a version that is not one, or not after the last", () => {
    expect(draftProblem({ ...draft(), version: "one" }, null)).toBe(
      "one is not a version such as 1.0.0.");
    expect(draftProblem({ ...draft(), version: "" }, null)).toBe(
      "That is not a version such as 1.0.0.");
    expect(draftProblem({ ...draft(), version: "1.0.0" }, "1.0.0")).toContain(
      "must come after 1.0.0");
    expect(draftProblem({ ...draft(), version: "1.0.1" }, "1.0.0")).toBeNull();
  });

  it("names a parameter that cannot hold", () => {
    const p = (over = {}) => ({ ...blankParameter(), api_name: "region", ...over });
    const sql = "SELECT $region";
    expect(draftProblem({ ...draft(), sql, parameters: [p({ api_name: "Region" })] }, null))
      .toBe("Parameter 1 needs a name in lower case, such as region.");
    expect(draftProblem({ ...draft(), sql, parameters: [p(), p()] }, null))
      .toBe("Two parameters are called region.");
    expect(draftProblem({ ...draft(), sql, parameters: [p({ data_type: "object" })] }, null))
      .toBe("Choose the object type region refers to.");
    expect(draftProblem({ ...draft(), sql, parameters: [
      p({ data_type: "object", object_type_id: "t" })] }, null)).toBeNull();
  });

  it("names an output missing what its kind needs", () => {
    expect(draftProblem({ ...draft(), output: { kind: "array" } }, null))
      .toBe("Choose the type of value it returns.");
    expect(draftProblem({ ...draft(), output: { kind: "value", data_type: "" } }, null))
      .toBe("Choose the type of value it returns.");
    expect(draftProblem({ ...draft(), output: { kind: "object_set" } }, null))
      .toBe("Choose the object type of the set it returns.");
    expect(draftProblem({ ...draft(), output: { kind: "table" } }, null)).toBeNull();
  });

  it("holds the query's $names to the parameters, both ways", () => {
    expect(parametersUsed("SELECT $a, $b, $a")).toEqual(["a", "b"]);
    expect(draftProblem({ ...draft(), sql: "SELECT $region" }, null))
      .toBe("The query uses $region, which no parameter declares.");
    expect(draftProblem({ ...draft(), parameters: [{ ...blankParameter(), api_name: "x" }] }, null))
      .toBe("x is declared and the query never uses $x.");
  });
});

describe("the request and the run", () => {
  it("sends only the fields each kind uses", () => {
    const body = bodyOf({
      version: "1.0.0",
      parameters: [
        { api_name: "a", data_type: "string", object_type_id: "stale", required: false },
        { api_name: "b", data_type: "object", object_type_id: "t", required: true },
      ],
      inputs: ["t"],
      output: { kind: "value", data_type: "integer", object_type_id: "stale" },
      sql: "SELECT $a, $b",
    });
    expect(body).toEqual({
      version: "1.0.0",
      parameters: [
        { api_name: "a", data_type: "string", required: false },
        { api_name: "b", data_type: "object", required: true, object_type_id: "t" },
      ],
      inputs: ["t"],
      output: { kind: "value", data_type: "integer" },
      sql: "SELECT $a, $b",
    });
    expect(bodyOf({ ...blankDraft(), output: { kind: "object_set", object_type_id: "t",
      data_type: "x" } }).output).toEqual({ kind: "object_set", object_type_id: "t" });
    expect(bodyOf({ ...blankDraft(), output: { kind: "table", data_type: "x" } }).output)
      .toEqual({ kind: "table" });
    expect(bodyOf({ ...blankDraft(), output: { kind: "array", data_type: "date" } }).output)
      .toEqual({ kind: "array", data_type: "date" });
  });

  it("starts a new version from the stored one", () => {
    const stored: FunctionVersion = {
      id: "v", version: "1.2.0", inputs: ["t"], sql: "SELECT 1", created_at: "",
      output: { kind: "table" },
      parameters: [{ api_name: "a", data_type: "string", required: true }],
    };
    const draft = draftOf(stored);
    expect(draft).toEqual({ version: "1.2.1", inputs: ["t"], sql: "SELECT 1",
      output: { kind: "table" },
      parameters: [{ api_name: "a", data_type: "string", required: true, object_type_id: null }] });
    draft.inputs.push("u");
    expect(stored.inputs).toEqual(["t"]);
  });

  it("types what was typed, leaving blanks out", () => {
    const parameters = [
      { api_name: "n", data_type: "integer" as const, required: true },
      { api_name: "f", data_type: "float" as const, required: true },
      { api_name: "b", data_type: "boolean" as const, required: true },
      { api_name: "s", data_type: "string" as const, required: false },
      { api_name: "d", data_type: "date" as const, required: true },
    ];
    expect(valuesFor(parameters, { n: " 3 ", f: "2.5", b: "true", s: "  ", d: "2026-01-02" }))
      .toEqual({ n: 3, f: 2.5, b: true, d: "2026-01-02" });
    expect(valuesFor(parameters, { n: "ten", b: "false" })).toEqual({ n: "ten", b: false });
    expect(valuesFor(parameters, { b: "yes" })).toEqual({ b: "yes" });
  });

  it("says a result in a line", () => {
    expect(resultLine({ kind: "value", version: "1", value: 40 })).toBe("40");
    expect(resultLine({ kind: "value", version: "1", value: null })).toBe("No value");
    expect(resultLine({ kind: "value", version: "1", value: 0 })).toBe("0");
    expect(resultLine({ kind: "array", version: "1", values: [1] })).toBe("1 value");
    expect(resultLine({ kind: "array", version: "1", values: [1, 2] })).toBe("2 values");
    expect(resultLine({ kind: "object_set", version: "1", values: ["a", "b"] })).toBe("2 objects");
    expect(resultLine({ kind: "table", version: "1", rows: [[1]], truncated: false })).toBe("1 row");
    expect(resultLine({ kind: "table", version: "1", rows: [[1], [2]], truncated: true }))
      .toBe("2 rows (the first of more)");
  });
});

describe("an object set in, a map out (§770)", () => {
  const set = { api_name: "shown", data_type: "object_set" as const, object_type_id: null,
    required: true };

  it("needs the object type of each", () => {
    expect(draftProblem({ ...blankDraft(), sql: "SELECT $shown", parameters: [set] }, null))
      .toBe("Choose the object type shown refers to.");
    expect(draftProblem({ ...blankDraft(), sql: "SELECT 1", output: { kind: "map" } }, null))
      .toBe("Choose the object type it gives values for.");
  });

  it("sends their object types", () => {
    const body = bodyOf({ ...blankDraft(), parameters: [{ ...set, object_type_id: "t" }],
      output: { kind: "map", object_type_id: "t", data_type: "x" } });
    expect(body.parameters).toEqual([
      { api_name: "shown", data_type: "object_set", required: true, object_type_id: "t" }]);
    expect(body.output).toEqual({ kind: "map", object_type_id: "t" });
  });

  it("takes keys separated by commas, and counts a map's objects", () => {
    expect(valuesFor([set], { shown: " S1, S2 ,, " })).toEqual({ shown: ["S1", "S2"] });
    expect(resultLine({ kind: "map", version: "1", entries: { a: {}, b: {} } })).toBe("2 objects");
    expect(resultLine({ kind: "map", version: "1", entries: { a: {} } })).toBe("1 object");
    expect(resultLine({ kind: "map", version: "1" })).toBe("0 objects");
    expect(resultLine({ kind: "aggregation", version: "1", buckets: [
      { key: "a", value: 1 }] })).toBe("1 bucket");
    expect(resultLine({ kind: "aggregation", version: "1", buckets: [
      { key: "a", value: 1 }, { key: "b", value: 2 }] })).toBe("2 buckets");
    expect(resultLine({ kind: "aggregation", version: "1" })).toBe("0 buckets");
  });
});
