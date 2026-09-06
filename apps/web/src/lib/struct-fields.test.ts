import { describe, expect, it } from "vitest";
import {
  FIELD_TYPES,
  blankField,
  parseStructDefault,
  problem,
  renamedFields,
  structRows,
  toFieldApiName,
} from "./struct-fields";
import type { StructField } from "@/lib/types";

function field(api_name: string, extra: Partial<StructField> = {}): StructField {
  return { api_name, display_name: "", description: "", data_type: "string", ...extra };
}

const ADDRESS = [
  field("street", { display_name: "Street" }),
  field("postal_code", { display_name: "Postal code" }),
  field("floors", { data_type: "integer" }),
];

describe("problem", () => {
  it("refuses a struct with no fields, because p.149 does", () => {
    // "Structs must have at least 1 field." A struct with none is a `json`
    // property with a more specific name.
    expect(problem([])).toMatch(/at least one field/);
  });

  it("says nothing about a declaration the server would accept", () => {
    expect(problem(ADDRESS)).toBeNull();
  });

  it("names the field that has no name, by position", () => {
    // The row number is the only handle a nameless row has, and "a field needs
    // a name" with three rows on screen is a sentence that does not help.
    expect(problem([field("street"), field("")])).toBe("Field 2 needs a name.");
  });

  it("refuses a name the property naming rule refuses", () => {
    // The same rule one level down, deliberately: a field name is read the way
    // a property name is, and two conventions one level apart is a thing to
    // get wrong rather than a freedom.
    expect(problem([field("Street")])).toMatch(/not a valid field name/);
    expect(problem([field("1st_line")])).toMatch(/not a valid field name/);
  });

  it("refuses two fields with one name", () => {
    expect(problem([field("street"), field("street")])).toMatch(/both named street/);
  });

  it("complains about one thing at a time", () => {
    // Two faults, one sentence: a list of every complaint about a half-typed
    // form is a list somebody reads to find the one they already fixed.
    const answer = problem([field(""), field("Street")]);
    expect(answer).toBe("Field 1 needs a name.");
  });

  it("refuses a padded name rather than trimming it", () => {
    // **The trim used to be here and it was dead code.** `toFieldApiName` is
    // what fills the name box and it cannot produce whitespace, so nothing
    // could reach a trim — a mutant removing it survived. Refusing is also the
    // more honest answer: the server trims nothing, so a name that only
    // *looked* valid here would have been refused there.
    expect(problem([field("  street  ")])).toMatch(/not a valid field name/);
  });
});

describe("renamedFields", () => {
  it("finds a name that changed in place", () => {
    const after = [field("road"), ...ADDRESS.slice(1)];
    expect(renamedFields(ADDRESS, after)).toEqual(["street"]);
  });

  it("says nothing about a declaration that has not been renamed", () => {
    expect(renamedFields(ADDRESS, ADDRESS)).toEqual([]);
  });

  it("does not call a newly added field a rename", () => {
    // p.158's warning is about a name applications already hold. A row that
    // has never been saved has no old name to warn about, and warning anyway
    // would train somebody to ignore the warning.
    expect(renamedFields(ADDRESS, [...ADDRESS, field("county")])).toEqual([]);
  });

  it("says nothing about a struct being declared for the first time", () => {
    expect(renamedFields(null, ADDRESS)).toEqual([]);
    expect(renamedFields([], ADDRESS)).toEqual([]);
  });

  it("does not warn while a name is being cleared before it is retyped", () => {
    // Emptying the box is the first keystroke of a rename, not a rename. A
    // warning that appears mid-edit is a warning about a state nobody is in.
    expect(renamedFields(ADDRESS, [field(""), ...ADDRESS.slice(1)])).toEqual([]);
  });
});

describe("structRows", () => {
  it("reads a value in the declared order, not the value's own", () => {
    // Two rows of one dataset can hold their keys in different orders; the
    // declaration is the author's statement about the value (p.154) and the
    // order `_coerce_struct` rebuilds it in.
    expect(
      structRows(ADDRESS, { floors: 3, street: "12 Main St", postal_code: "N1 9GU" }),
    ).toEqual([
      ["Street", "12 Main St"],
      ["Postal code", "N1 9GU"],
      ["floors", 3],
    ]);
  });

  it("falls back to the field's own name when it has no display name", () => {
    expect(structRows([field("floors")], { floors: 3 })).toEqual([["floors", 3]]);
  });

  it("draws a row for a field the value has nothing for", () => {
    // p.59's "semantic grouping" is the point of the type: an address that
    // silently omits its postcode looks like an address without one, rather
    // than like a value that is missing it.
    expect(structRows(ADDRESS, { street: "12 Main St" })).toEqual([
      ["Street", "12 Main St"],
      ["Postal code", null],
      ["floors", null],
    ]);
  });

  it("shows nothing the declaration does not name", () => {
    // The difference between this type and `json`, at the last hop: the sync
    // already dropped the undeclared key, and a renderer that read the value's
    // own keys would put it back for anything written another way.
    expect(structRows(ADDRESS, { street: "A", county: "Greater London" })).toEqual([
      ["Street", "A"],
      ["Postal code", null],
      ["floors", null],
    ]);
  });

  it("declines a value that is not a struct, so the caller can fall back", () => {
    for (const value of [null, undefined, "text", 7, [1, 2]]) {
      expect(structRows(ADDRESS, value)).toBeNull();
    }
  });

  it("declines when there is no declaration to read it against", () => {
    // Which is what makes this safe to call from a renderer that is sometimes
    // handed a property and sometimes not.
    expect(structRows(null, { street: "A" })).toBeNull();
    expect(structRows([], { street: "A" })).toBeNull();
  });
});

describe("the field types offered", () => {
  it("is p.149's list and not this platform's property types", () => {
    // The server's list is the one that refuses; this is the copy the dialog
    // draws, and `test_struct_properties.py` scans this file to keep the two
    // in step. Asserted here as well because a mirror nobody states is a
    // mirror nobody notices.
    expect([...FIELD_TYPES].sort()).toEqual([
      "boolean", "date", "float", "geopoint", "integer", "string", "timestamp",
    ]);
  });

  it("does not offer a struct, because p.149 refuses nesting", () => {
    expect(FIELD_TYPES).not.toContain("struct");
  });
});

describe("toFieldApiName", () => {
  it("takes what somebody would type and makes a field name of it", () => {
    expect(toFieldApiName("Postal Code")).toBe("postal_code");
    expect(toFieldApiName("postal-code")).toBe("postal_code");
    expect(toFieldApiName("  Street  ")).toBe("street");
  });

  it("still leaves something `problem` has to refuse", () => {
    // The reason both exist. Normalising cannot fix a name that starts with a
    // digit - there is nothing to turn `1st_line` into that the author would
    // recognise - so the check downstream is reachable through this box rather
    // than only through the API. A guard nothing can reach is the shape §213
    // deletes; this one is not that.
    const typed = toFieldApiName("1st line");
    expect(typed).toBe("1st_line");
    expect(problem([field(typed)])).toMatch(/not a valid field name/);
  });
});

describe("blankField", () => {
  it("starts on a type rather than on nothing", () => {
    // A select with no value selected is a control whose first click is
    // undoing a state nobody chose.
    expect(blankField().data_type).toBe("string");
    expect(blankField().api_name).toBe("");
  });
});

describe("parseStructDefault", () => {
  it("reads what somebody typed as a struct", () => {
    // `workshop` p.152: "A struct variable can be initialized statically
    // within Workshop." The box holds text; the document has to hold an
    // object, because `extract_struct_field` refuses anything else.
    expect(parseStructDefault('{"street": "1 Main St", "floors": 3}')).toEqual({
      value: { street: "1 Main St", floors: 3 },
    });
  });

  it("treats an empty box as no default rather than as an empty struct", () => {
    // Two different statements: "this variable starts from nothing" and "this
    // variable starts from a struct with no fields in it".
    expect(parseStructDefault("")).toEqual({});
    expect(parseStructDefault("   ")).toEqual({});
  });

  it("says what is wrong with half-written JSON without losing the last value", () => {
    // Half-written is the normal state of a box being typed into. The caller
    // writes nothing when there is an error, so the variable keeps the last
    // thing that parsed.
    const answer = parseStructDefault('{"street": ');
    expect(answer.error).toMatch(/valid JSON/);
    expect(answer.value).toBeUndefined();
  });

  it("refuses a list, because a struct is not one", () => {
    // p.75: a struct "maps string fieldIDs to values". An array of them is the
    // struct-array kind this platform does not have, and accepting one here
    // would produce a variable whose first extraction fails at view time.
    expect(parseStructDefault('["a", "b"]').error).toMatch(/field names and values/);
    expect(parseStructDefault("7").error).toMatch(/field names and values/);
    expect(parseStructDefault('"text"').error).toMatch(/field names and values/);
    expect(parseStructDefault("null").error).toMatch(/field names and values/);
  });

  it("accepts a struct with no fields typed into it", () => {
    // Distinct from the empty box above: `{}` is a value, and the server
    // stores it. Nothing about a *variable* requires at least one field —
    // p.149's "at least 1 field" is a rule about a property's declaration.
    expect(parseStructDefault("{}")).toEqual({ value: {} });
  });
});
