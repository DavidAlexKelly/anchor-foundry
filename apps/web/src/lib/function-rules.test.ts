/** An action's Function rule (`action-types` p.22, p.75-83; §773). */
import { describe, expect, it } from "vitest";

import {
  BLANK_FUNCTION_RULE, canAutoUpgrade, defaultInputs, functionRuleOf, functionRuleProblem,
  parametersToCreate, resolveVersion,
} from "./function-rules";
import type { FunctionDetail, FunctionVersion } from "./types";

function version(v: string, over: Partial<FunctionVersion> = {}): FunctionVersion {
  return {
    id: v, version: v, inputs: ["t"], sql: "", created_at: "",
    output: { kind: "edits", object_type_id: "t" },
    parameters: [
      { api_name: "ticket", data_type: "object", object_type_id: "t", required: true },
      { api_name: "note", data_type: "string", display_name: "Note", required: false },
      { api_name: "minimum", data_type: "integer", required: true },
    ],
    ...over,
  };
}

function fn(versions: FunctionVersion[]): FunctionDetail {
  return { id: "f", api_name: "close", display_name: "", description: "",
    latest_version: versions[0]?.version ?? null, created_at: "", updated_at: "", versions };
}

describe("a saved rule, read", () => {
  it("keeps the three sources and drops anything else", () => {
    expect(functionRuleOf(null)).toEqual(BLANK_FUNCTION_RULE);
    expect(functionRuleOf([])).toEqual(BLANK_FUNCTION_RULE);
    expect(functionRuleOf({ function_id: "f", version: "1.0.0", auto_upgrade: "yes", inputs: {
      a: { subject: true }, b: { parameter: "p" }, c: { value: 0 }, d: { parameter: "" },
      e: null, f: { subject: "true" } } }))
      .toEqual({ function_id: "f", version: "1.0.0", auto_upgrade: false, inputs: {
        a: { subject: true }, b: { parameter: "p" }, c: { value: 0 } } });
    expect(functionRuleOf({ function_id: 1, version: 2, auto_upgrade: true, inputs: [] }))
      .toEqual({ ...BLANK_FUNCTION_RULE, auto_upgrade: true });
    expect(functionRuleOf({ inputs: { a: { parameter: 3 } } }).inputs).toEqual({});
  });
});

describe("the version an action runs (p.80-82)", () => {
  const all = fn([version("2.0.0"), version("1.3.0-rc.1"), version("1.2.1"), version("1.2.0"),
                  version("1.1.0"), version("0.4.0"), version("0.3.0")]);

  it("is the pinned one without auto upgrade", () => {
    expect(resolveVersion(all, { ...BLANK_FUNCTION_RULE, version: "1.1.0" })?.version)
      .toBe("1.1.0");
  });

  it("is the newest release of the same major with it", () => {
    const rule = { ...BLANK_FUNCTION_RULE, version: "1.1.0", auto_upgrade: true };
    // Not 2.0.0, a breaking change; not 1.3.0-rc.1, not a release.
    expect(resolveVersion(all, rule)?.version).toBe("1.2.1");
    expect(resolveVersion(all, { ...rule, version: "1.2.1" })?.version).toBe("1.2.1");
  });

  it("never auto-upgrades a 0.y.z version", () => {
    expect(canAutoUpgrade("0.3.0")).toBe(false);
    expect(canAutoUpgrade("1.0.0")).toBe(true);
    expect(canAutoUpgrade("nonsense")).toBe(false);
    expect(resolveVersion(all, { ...BLANK_FUNCTION_RULE, version: "0.3.0", auto_upgrade: true })
      ?.version).toBe("0.3.0");
  });

  it("is nothing for a version the function does not have", () => {
    expect(resolveVersion(all, { ...BLANK_FUNCTION_RULE, version: "9.0.0" })).toBeUndefined();
    expect(resolveVersion(undefined, { ...BLANK_FUNCTION_RULE, version: "1.1.0" }))
      .toBeUndefined();
  });
});

describe("the inputs a chosen function starts with (p.79)", () => {
  it("is this object for the first of the action's type, a parameter otherwise", () => {
    const v = version("1.0.0", { parameters: [
      { api_name: "ticket", data_type: "object", object_type_id: "t", required: true },
      { api_name: "other", data_type: "object", object_type_id: "t", required: true },
      { api_name: "site", data_type: "object", object_type_id: "s", required: true },
      { api_name: "keys", data_type: "object_set", object_type_id: "t", required: false },
      { api_name: "note", data_type: "string", required: false },
    ] });
    expect(defaultInputs(v, "t")).toEqual({
      ticket: { subject: true }, other: { parameter: "other" }, site: { parameter: "site" },
      note: { parameter: "note" } });
    expect(defaultInputs(v, null).ticket).toEqual({ parameter: "ticket" });
  });

  it("creates the parameters they read that the action lacks", () => {
    const v = version("1.0.0");
    const inputs = defaultInputs(v, "t");
    expect(parametersToCreate(v, inputs, ["minimum"])).toEqual([
      { api_name: "note", display_name: "Note", data_type: "string", object_type_id: null,
        required: false }]);
    expect(parametersToCreate(v, { ticket: { parameter: "ticket" } }, [])).toEqual([
      { api_name: "ticket", display_name: "ticket", data_type: "object", object_type_id: "t",
        required: true }]);
    // An object set has no action parameter to be (p.33's types).
    const withSet = version("1.0.0", { parameters: [
      { api_name: "keys", data_type: "object_set", object_type_id: "t", required: true }] });
    expect(parametersToCreate(withSet, { keys: { parameter: "keys" } }, [])).toEqual([]);
    // A value, this object, or a name the function does not have: none.
    expect(parametersToCreate(v, { note: { value: "x" }, ticket: { subject: true },
                                   minimum: { parameter: "gone" } }, [])).toEqual([]);
  });
});

describe("why a rule cannot run", () => {
  const f = fn([version("1.1.0"), version("1.0.0"),
                version("0.1.0", { output: { kind: "value", data_type: "integer" } })]);
  const ok = { function_id: "f", version: "1.0.0", auto_upgrade: false, inputs: {
    ticket: { subject: true as const }, minimum: { parameter: "minimum" } } };

  it("says nothing when it can", () => {
    expect(functionRuleProblem(ok, f, ["minimum"], "t")).toBeNull();
    expect(functionRuleProblem({ ...ok, auto_upgrade: true }, f, ["minimum"], "t")).toBeNull();
  });

  it("names what is missing, in the order the form asks for it", () => {
    expect(functionRuleProblem(BLANK_FUNCTION_RULE, f, [], "t"))
      .toBe("Choose the function this action calls.");
    expect(functionRuleProblem(ok, undefined, [], "t"))
      .toBe("The function this rule calls does not exist.");
    expect(functionRuleProblem({ ...ok, version: "" }, f, [], "t"))
      .toBe("Choose the version this action calls.");
    expect(functionRuleProblem({ ...ok, version: "3.0.0" }, f, [], "t"))
      .toBe("close has no version 3.0.0.");
    expect(functionRuleProblem({ ...ok, version: "0.1.0", auto_upgrade: true }, f, [], "t"))
      .toBe("A 0.y.z version cannot auto-upgrade (action-types p.82).");
    expect(functionRuleProblem({ ...ok, version: "0.1.0" }, f, [], "t"))
      .toBe("close is not an edit function: it returns value.");
    expect(functionRuleProblem({ ...ok, inputs: { ticket: { subject: true } } }, f, [], "t"))
      .toBe("minimum needs a parameter, a value or this object.");
    expect(functionRuleProblem(ok, f, [], "t"))
      .toBe("minimum reads minimum, which is not a parameter of this action.");
    expect(functionRuleProblem(ok, f, ["minimum"], "other"))
      .toBe("ticket is not an object of this action's type, so it cannot be this object.");
    expect(functionRuleProblem({ ...ok, inputs: { ...ok.inputs, minimum: { subject: true } } },
                               f, ["minimum"], "t"))
      .toBe("minimum is not an object of this action's type, so it cannot be this object.");
  });

  it("lets an optional parameter go unfed", () => {
    expect(functionRuleProblem(ok, f, ["minimum"], "t")).toBeNull();
  });
});
