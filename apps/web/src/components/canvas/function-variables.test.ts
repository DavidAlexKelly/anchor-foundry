/** Function-backed variables (Workshop p.73; `functions` p.80; §772). */
import { describe, expect, it } from "vitest";

import {
  callOf, derivationOf, FUNCTION_KINDS, functionVariableProblem, NO_CALL, outputFor,
} from "./function-variables";
import type { FunctionDetail, FunctionVersion } from "@/lib/types";

function version(over: Partial<FunctionVersion> = {}): FunctionVersion {
  return {
    id: "v", version: "1.0.0", inputs: ["t"], sql: "", created_at: "",
    output: { kind: "value", data_type: "integer" },
    parameters: [{ api_name: "region", data_type: "string", required: true },
                 { api_name: "note", data_type: "string", required: false }],
    ...over,
  };
}

function fn(versions: FunctionVersion[] = [version({ version: "1.1.0" }), version()]): FunctionDetail {
  return { id: "f", api_name: "total", display_name: "", description: "",
    latest_version: versions[0]?.version ?? null, created_at: "", updated_at: "", versions };
}

describe("the call a derivation holds, and back", () => {
  it("keeps variables as inputs in order and fixed values in config", () => {
    const d = derivationOf({ function_id: "f", version: "1.0.0", inputs: {
      region: { variable: "v_region" }, minimum: { value: 15 }, site: { variable: "v_site" } } });
    expect(d).toEqual({ transform: "function", inputs: ["v_region", "v_site"], config: {
      function_id: "f", version: "1.0.0", parameters: ["region", "site"],
      values: { minimum: 15 } } });
    expect(callOf(d)).toEqual({ function_id: "f", version: "1.0.0", inputs: {
      region: { variable: "v_region" }, minimum: { value: 15 }, site: { variable: "v_site" } } });
  });

  it("starts empty, calling the newest", () => {
    expect(derivationOf(NO_CALL)).toEqual({ transform: "function", inputs: [], config: {
      function_id: "", version: null, parameters: [], values: {} } });
    expect(callOf(derivationOf(NO_CALL))).toEqual(NO_CALL);
  });

  it("reads a saved document defensively", () => {
    expect(callOf({ transform: "function", inputs: [] })).toEqual(NO_CALL);
    expect(callOf({ transform: "function", inputs: ["a", "", "b"], config: {
      function_id: 3, version: "", parameters: ["x", "y", 4], values: [1] } }))
      .toEqual({ function_id: "", version: null, inputs: { x: { variable: "a" } } });
    expect(callOf({ transform: "function", inputs: ["a"], config: {
      function_id: "f", parameters: "x" } }).inputs).toEqual({});
    // A parameter both fed and given a value is the variable's, as the server
    // spreads the inputs over the values.
    expect(callOf({ transform: "function", inputs: ["a"], config: {
      function_id: "f", parameters: ["x"], values: { x: 1 } } }).inputs)
      .toEqual({ x: { variable: "a" } });
  });
});

describe("what a kind takes", () => {
  it("is the service's mapping", () => {
    expect(FUNCTION_KINDS).toEqual(
      ["string", "number", "boolean", "date", "timestamp", "array", "object_set"]);
    expect(outputFor("number")).toBe("value");
    expect(outputFor("string")).toBe("value");
    expect(outputFor("array")).toBe("array");
    expect(outputFor("object_set")).toBe("object_set");
  });
});

describe("why a function variable cannot resolve", () => {
  const call = { function_id: "f", version: null, inputs: { region: { variable: "v" } } };

  it("says nothing when it can", () => {
    expect(functionVariableProblem("number", call, fn())).toBeNull();
  });

  it("names each thing missing, in the order the editor asks for them", () => {
    expect(functionVariableProblem("struct", call, fn()))
      .toBe("A function cannot fill a struct variable.");
    expect(functionVariableProblem("number", NO_CALL, fn()))
      .toBe("Choose the function this variable calls.");
    expect(functionVariableProblem("number", call, undefined))
      .toBe("The function this variable calls does not exist.");
    expect(functionVariableProblem("number", { ...call, version: "9.0.0" }, fn()))
      .toBe("total has no version 9.0.0.");
    expect(functionVariableProblem("number", { ...call, inputs: {} }, fn()))
      .toBe("region needs a value or a variable.");
  });

  it("refuses an output the kind does not hold", () => {
    expect(functionVariableProblem("array", call, fn()))
      .toBe("total returns value, and a array variable takes array.");
    const sets = fn([version({ output: { kind: "object_set", object_type_id: "t" } })]);
    expect(functionVariableProblem("number", call, sets))
      .toBe("total returns object set, and a number variable takes value.");
    expect(functionVariableProblem("object_set", call, sets)).toBeNull();
  });

  it("reads the version it names, not the newest", () => {
    const two = fn([version({ version: "2.0.0", output: { kind: "array", data_type: "string" } }),
                    version()]);
    expect(functionVariableProblem("number", call, two)).toMatch(/returns array/);
    expect(functionVariableProblem("number", { ...call, version: "1.0.0" }, two)).toBeNull();
  });
});
