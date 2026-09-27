import { describe, expect, it } from "vitest";
import { inlineActionChoices, inlineParameterFor, liveInlineParameter } from "./property-inline-action";

const writes = (property: string, parameter: string, extra: Record<string, unknown> = {}) =>
  ({ kind: "modify_object", config: { property, parameter, ...extra } });

const set = {
  id: "a1", object_type_id: "t1", inline_edit_refusals: [],
  rules: [writes("status", "new_status")],
};

describe("a property's inline action (§594, p.266)", () => {
  it("is the parameter a rule on the action's own object writes it from", () => {
    expect(inlineParameterFor(set, "status")).toBe("new_status");
    expect(inlineParameterFor(set, "priority")).toBeNull();
    expect(inlineParameterFor({ rules: [writes("status", "p", { object: "other" })] }, "status")).toBeNull();
    expect(inlineParameterFor({ rules: [{ kind: "create_object", config: { property: "status", parameter: "p" } }] },
      "status")).toBeNull();
    expect(inlineParameterFor({ rules: [{ kind: "modify_object", config: { property: "status" } }] },
      "status")).toBeNull();
    expect(inlineParameterFor({ rules: [{ kind: "modify_object", config: null }] }, "status")).toBeNull();
    expect(inlineParameterFor(null, "status")).toBeNull();
  });

  it("offers eligible actions on the type that write the property", () => {
    const actions = [
      set,
      { ...set, id: "a2", object_type_id: "t2" },
      { ...set, id: "a3", inline_edit_refusals: ["no"] },
      { ...set, id: "a4", inline_edit_refusals: undefined },
      { ...set, id: "a5", rules: [writes("priority", "p")] },
    ];
    expect(inlineActionChoices(actions, "t1", "status").map((a) => a.id)).toEqual(["a1"]);
    expect(inlineActionChoices(undefined, "t1", "status")).toEqual([]);
  });

  it("draws an editor only while the action still backs the property", () => {
    expect(liveInlineParameter(set, "status")).toBe("new_status");
    expect(liveInlineParameter({ ...set, inline_edit_refusals: ["now refused"] }, "status")).toBeNull();
    expect(liveInlineParameter({ ...set, rules: [] }, "status")).toBeNull();
    expect(liveInlineParameter(undefined, "status")).toBeNull();
  });
});
