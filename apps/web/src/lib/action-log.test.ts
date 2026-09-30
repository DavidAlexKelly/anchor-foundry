import { describe, expect, it } from "vitest";

import { referenceChoices, referencesSummary, withReference } from "./action-log";
import type { ActionParameter } from "@/lib/types";

function param(over: Partial<ActionParameter>): ActionParameter {
  return {
    id: "", api_name: "p", display_name: "", data_type: "string", required: false,
    default_value: null, hidden: false, sort_order: 0, ...over,
  };
}

describe("p.168's object reference parameters (§586)", () => {
  it("offers single object parameters, with the type they hold", () => {
    const choices = referenceChoices({
      parameters: [
        param({ api_name: "status" }),
        param({ api_name: "also", display_name: "Also", data_type: "object", object_type_id: "t1" }),
        param({ api_name: "other", data_type: "object" }),
        param({ api_name: "untyped", data_type: "object" }),
        // p.168: not for a parameter that allows multiple values.
        param({ api_name: "many", data_type: "array", array_of: "object", object_type_id: "t1" }),
      ],
      rules: [{ config: { object: "other", object_type: "t2" } }, { config: { property: "x" } }],
    });
    expect(choices).toEqual([
      { parameter: "also", label: "Also", typeId: "t1" },
      { parameter: "other", label: "other", typeId: "t2" },
      { parameter: "untyped", label: "untyped", typeId: null },
    ]);
  });
});

describe("choosing properties (§586)", () => {
  it("ticks and unticks, once each, and drops an empty parameter", () => {
    let chosen = withReference({}, "also", "priority", true);
    chosen = withReference(chosen, "also", "priority", true);
    chosen = withReference(chosen, "also", "status", true);
    expect(chosen).toEqual({ also: ["priority", "status"] });
    chosen = withReference(chosen, "also", "priority", false);
    expect(chosen).toEqual({ also: ["status"] });
    expect(withReference(chosen, "also", "status", false)).toEqual({});
  });

  it("says what a log keeps", () => {
    expect(referencesSummary({ also: ["priority", "status"] }))
      .toBe("Keeps also: priority, status.");
    expect(referencesSummary({})).toBe("Keeps no object properties.");
    expect(referencesSummary(null)).toBe("Keeps no object properties.");
  });
});
