import { describe, expect, it } from "vitest";

import {
  CONSTRAINABLE, constraintBaseType, constraintNote, fieldChoices, fieldNotes, isStructParameter,
  multipleChoice,
} from "./parameter-constraint";
import type { ValueConstraint } from "@/lib/types";

const PRIORITIES: ValueConstraint = { kind: "enum", values: ["P0", "P1", "P2"] };
const SUMMARY: ValueConstraint = { kind: "range", minimum: 10, maximum: 500 };

describe("which parameters take a constraint (§584)", () => {
  it("is the scalar types, and arrays of them by their items", () => {
    for (const type of CONSTRAINABLE) {
      expect(constraintBaseType({ data_type: type })).toBe(type);
    }
    expect(constraintBaseType({ data_type: "array", array_of: "integer" })).toBe("integer");
    expect(constraintBaseType({ data_type: "array", array_of: "geopoint" })).toBeNull();
    expect(constraintBaseType({ data_type: "array" })).toBeNull();
    expect(constraintBaseType({ data_type: "object" })).toBeNull();
    expect(constraintBaseType({ data_type: "struct" })).toBeNull();
  });
});

describe("p.8's multiple choice (§584)", () => {
  it("is the options, as the type holds them", () => {
    expect(multipleChoice({ data_type: "string", value_constraint: PRIORITIES }))
      .toEqual(["P0", "P1", "P2"]);
    expect(multipleChoice({ data_type: "integer", value_constraint: { kind: "enum", values: [1, 2] } }))
      .toEqual([1, 2]);
    // Each item of a list is picked from them.
    expect(multipleChoice({ data_type: "array", array_of: "string", value_constraint: PRIORITIES }))
      .toEqual(["P0", "P1", "P2"]);
  });

  it("is not for typed input or another kind", () => {
    expect(multipleChoice({ data_type: "string" })).toBeNull();
    expect(multipleChoice({ data_type: "string", value_constraint: null })).toBeNull();
    expect(multipleChoice({ data_type: "string", value_constraint: SUMMARY })).toBeNull();
  });
});

describe("the note under a constrained box (§584)", () => {
  it("says the server's summary", () => {
    expect(constraintNote({ data_type: "string", value_constraint: SUMMARY,
      constraint_summary: "between 10 and 500" })).toBe("Allowed: between 10 and 500.");
    expect(constraintNote({ data_type: "array", array_of: "string", value_constraint: SUMMARY,
      constraint_summary: "between 10 and 500" })).toBe("Each item: between 10 and 500.");
  });

  it("says nothing for User input or a dropdown", () => {
    expect(constraintNote({ data_type: "string", constraint_summary: "" })).toBe("");
    expect(constraintNote({ data_type: "string", value_constraint: PRIORITIES,
      constraint_summary: "one of P0, P1, P2" })).toBe("");
    expect(constraintNote({ data_type: "string", value_constraint: SUMMARY })).toBe("");
  });
});

describe("p.71-72's struct fields (§585)", () => {
  const fields = [
    { api_name: "summary", display_name: "Summary" },
    { api_name: "kind", display_name: " " },
    { api_name: "hours", display_name: "Hours" },
  ];
  const resolution = {
    struct_fields: fields,
    field_constraints: {
      summary: SUMMARY,
      kind: { kind: "enum", values: ["fix", "wontfix"] } as ValueConstraint,
    },
    field_constraint_summaries: { summary: "between 10 and 500", kind: "one of fix, wontfix" },
  };

  it("offers a dropdown for each multiple-choice field", () => {
    expect(fieldChoices(resolution)).toEqual({ kind: ["fix", "wontfix"] });
    expect(fieldChoices({ field_constraints: { summary: SUMMARY } })).toBeNull();
    expect(fieldChoices({})).toBeNull();
  });

  it("says the others by the field's label", () => {
    expect(fieldNotes(resolution)).toEqual(["Summary: between 10 and 500."]);
    // A blank label is the api_name, as the form draws it.
    expect(fieldNotes({ ...resolution, field_constraints: { kind: SUMMARY } }))
      .toEqual(["kind: one of fix, wontfix."]);
    expect(fieldNotes({ field_constraints: { summary: SUMMARY } })).toEqual([]);
  });
});

describe("which parameters have fields to constrain (§585)", () => {
  it("is a struct, or a list of them", () => {
    expect(isStructParameter({ data_type: "struct" })).toBe(true);
    expect(isStructParameter({ data_type: "array", array_of: "struct" })).toBe(true);
    expect(isStructParameter({ data_type: "array", array_of: "string" })).toBe(false);
    expect(isStructParameter({ data_type: "string" })).toBe(false);
  });
});
