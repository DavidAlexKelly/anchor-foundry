import { describe, expect, it } from "vitest";

import { suggestedFields, suggestedInput, suggestedTypeLabel } from "./suggested-property";
import type { StructField, SuggestedProperty } from "./types";

const base: SuggestedProperty = {
  api_name: "address", display_name: "Address", data_type: "string", required: false,
  source_column: "address",
};
const field = (api_name: string): StructField => ({ api_name, display_name: api_name, description: "", data_type: "string" });

describe("a suggested property, for the dialog (§735)", () => {
  it("labels an array by its element", () => {
    expect(suggestedTypeLabel({ ...base, data_type: "array", array_of: "string" })).toBe("array of string");
    expect(suggestedTypeLabel({ ...base, data_type: "array" })).toBe("array");
    expect(suggestedTypeLabel({ ...base, data_type: "struct" })).toBe("struct");
  });

  it("lists a struct's automapped fields", () => {
    expect(suggestedFields({ ...base, data_type: "struct", struct_fields: [field("street"), field("number")] }))
      .toBe("street, number");
    expect(suggestedFields({ ...base, struct_fields: [] })).toBeNull();
    expect(suggestedFields(base)).toBeNull();
  });

  it("sends a struct's fields and an array's element with the type", () => {
    expect(suggestedInput(base)).toEqual({ api_name: "address", data_type: "string", required: false });
    expect(suggestedInput({ ...base, required: true })).toEqual(
      { api_name: "address", data_type: "string", required: true });
    expect(suggestedInput({ ...base, data_type: "array", array_of: "struct", struct_fields: [field("a")] }))
      .toEqual({ api_name: "address", data_type: "array", required: false, array_of: "struct",
        struct_fields: [field("a")] });
    expect(suggestedInput({ ...base, array_of: null, struct_fields: [] })).toEqual(
      { api_name: "address", data_type: "string", required: false });
  });
});
