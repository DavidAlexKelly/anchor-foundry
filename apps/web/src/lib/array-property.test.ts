/**
 * An array property's element type, in the editor (§347; Foundry
 * `object-link-types` p.86, p.140; db 0087).
 *
 * The list itself is guarded against the *server's* by
 * `apps/api/tests/test_array_properties.py`, which is the direction that
 * catches an addition. What is here is the part the server cannot see: the
 * states this dialog is allowed to be in.
 */
import { describe, expect, it } from "vitest";
import {
  DEFAULT_ELEMENT, ELEMENT_TYPES, elementRefusal, needsFields,
  structuresTheElement, withDataType,
} from "./array-property";
import type { PropertyDataType } from "@/lib/types";

const row = (over: Record<string, unknown> = {}) => ({
  data_type: "string" as PropertyDataType,
  array_of: null as PropertyDataType | null,
  ...over,
});

describe("changing a property's base type (§347)", () => {
  it("seeds an element type when it becomes an array", () => {
    // db 0087 refuses an array that does not say what of, so the row must
    // never be in that state — not "must report it".
    expect(withDataType(row(), "array")).toMatchObject({
      data_type: "array", array_of: DEFAULT_ELEMENT,
    });
  });

  it("keeps an element type already chosen", () => {
    // Switching away and back should not silently retype somebody's list.
    const held = row({ data_type: "array", array_of: "date" });
    expect(withDataType(held, "array").array_of).toBe("date");
  });

  it("clears the element type when it stops being an array", () => {
    // **The half a plain `{...prop, data_type}` gets wrong**, and it gets it
    // wrong silently: the row still looks right, and the server refuses the
    // save with a message about a field the dropdown no longer shows.
    const held = row({ data_type: "array", array_of: "date" });
    expect(withDataType(held, "string")).toMatchObject({
      data_type: "string", array_of: null,
    });
  });

  it("leaves everything else on the row alone", () => {
    // The negative control: a version that returned a fresh two-field object
    // would pass all three above and erase the property's name.
    const held = row({ api_name: "tags", required: true, data_type: "array",
                       array_of: "string" });
    expect(withDataType(held, "integer")).toMatchObject({
      api_name: "tags", required: true,
    });
  });
});

describe("which rows need the Fields dialog (p.140)", () => {
  it("a struct property does", () => {
    expect(needsFields(row({ data_type: "struct" }))).toBe(true);
  });

  it("an array of structs does, and it is about the element", () => {
    const held = row({ data_type: "array", array_of: "struct" });
    expect(needsFields(held)).toBe(true);
    // The distinction the button's label depends on: db 0064's column holds
    // the *element's* fields in this case.
    expect(structuresTheElement(held)).toBe(true);
    expect(structuresTheElement(row({ data_type: "struct" }))).toBe(false);
  });

  it("an array of anything else does not", () => {
    // Without this a Fields button would appear on every array, opening a
    // dialog about fields the property has no use for.
    expect(needsFields(row({ data_type: "array", array_of: "string" }))).toBe(false);
    expect(needsFields(row({ data_type: "string" }))).toBe(false);
  });
});

describe("what the editor refuses before saving (§347)", () => {
  it("an array with no element type", () => {
    // Unreachable through `withDataType`, and reachable through a workspace
    // that predates this build or a document hand-edited through the API —
    // which is why the Save button asks rather than trusting the transition.
    expect(elementRefusal(row({ data_type: "array" }))).toContain("element type");
  });

  it("an element type this editor cannot declare", () => {
    const said = elementRefusal(row({ data_type: "array", array_of: "attachment" }));
    expect(said).toContain("attachment");
  });

  it("is silent about a row the server will take", () => {
    // The negative control: a refusal that fired on everything would pass both
    // assertions above.
    for (const held of ELEMENT_TYPES) {
      expect(elementRefusal(row({ data_type: "array", array_of: held }))).toBe("");
    }
    expect(elementRefusal(row({ data_type: "string" }))).toBe("");
  });

  it("says nothing about a non-array carrying an element type", () => {
    // That pairing is `withDataType`'s to prevent and the server's to refuse;
    // duplicating it here would be a third answer to one question (§213).
    expect(elementRefusal(row({ data_type: "string", array_of: "date" }))).toBe("");
  });
});
