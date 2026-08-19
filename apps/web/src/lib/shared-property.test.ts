/**
 * Attaching a property to a shared property (Foundry `object-link-types`
 * p.187–188).
 *
 * The server decides what is *legal* and is tested in
 * `apps/api/tests/test_shared_properties.py`. This is the form's copy of the
 * same list, asked for a different reason: what the row should show the moment
 * somebody picks one, before anything is saved.
 *
 * It gets its own tests because both ways of getting the list wrong are
 * silent. A field left out is one the server overwrites on save; a field added
 * that Foundry does not share is one the server refuses on the *next* save,
 * from a value this file put there.
 */
import { describe, expect, it } from "vitest";

import type { PropertyInput } from "@/lib/api";
import type { SharedProperty } from "@/lib/types";
import { attached, detached, offerableTo } from "./shared-property";

const SHARED: SharedProperty = {
  id: "sp1",
  api_name: "start_date",
  display_name: "Start date",
  description: "The day they began working",
  data_type: "date",
  visibility: "prominent",
  value_format: { kind: "datetime", style: "date" },
  usage_count: 2,
  value_type_id: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function property(): PropertyInput {
  return {
    api_name: "began_on",
    display_name: "Began on",
    description: "",
    data_type: "date",
    visibility: "normal",
    value_format: null,
    conditional_format: [
      { kind: "standard", property: "began_on", comparison: "is_null", colour: "#ff0000" },
    ],
    required: true,
    edit_only: true,
    derivation: null,
    shared_property_id: null,
  };
}

describe("attached", () => {
  it("takes the four fields Foundry calls shared metadata", () => {
    const out = attached(property(), SHARED);
    expect(out.shared_property_id).toBe("sp1");
    expect(out.display_name).toBe("Start date");
    expect(out.description).toBe(SHARED.description);
    expect(out.visibility).toBe("prominent");
    expect(out.value_format).toEqual(SHARED.value_format);
  });

  it("leaves the api_name alone", () => {
    // p.188: "the property ID and API name of the object-specific property
    // will remain unchanged so as to not break existing downstream workflows
    // that leverage them." This is the assertion that would fail if attaching
    // were implemented as "become the shared property".
    expect(attached(property(), SHARED).api_name).toBe("began_on");
  });

  it("leaves the settings that are about this object type alone", () => {
    // None of these is on p.181/p.184/p.190's list, and each is a statement
    // about one object type rather than about the property's meaning:
    // required is data quality, edit_only is backing datasets, and a
    // conditional format may compare against another property of the same
    // type (p.105).
    const out = attached(property(), SHARED);
    expect(out.required).toBe(true);
    expect(out.edit_only).toBe(true);
    expect(out.conditional_format).toEqual(property().conditional_format);
  });

  it("does not mutate what it is given", () => {
    const before = property();
    attached(before, SHARED);
    expect(before.display_name).toBe("Began on");
    expect(before.shared_property_id).toBeNull();
  });
});

describe("detached", () => {
  it("removes only the association", () => {
    const out = detached(attached(property(), SHARED));
    expect(out.shared_property_id).toBeNull();
    // Detaching is not a way to lose a display name - the server keeps the
    // last inherited values for the same reason (p.185's revert).
    expect(out.display_name).toBe("Start date");
    expect(out.value_format).toEqual(SHARED.value_format);
  });
});

describe("offerableTo", () => {
  const other: SharedProperty = { ...SHARED, id: "sp2", api_name: "grade", data_type: "integer" };

  it("offers only the shared properties whose base type matches", () => {
    expect(offerableTo([SHARED, other], "date").map((s) => s.id)).toEqual(["sp1"]);
    expect(offerableTo([SHARED, other], "integer").map((s) => s.id)).toEqual(["sp2"]);
  });

  it("offers nothing rather than everything when none matches", () => {
    // The alternative - falling back to the whole list - is offering a save
    // p.181 refuses, which is the trap this function exists to avoid.
    expect(offerableTo([SHARED, other], "string")).toEqual([]);
  });
});
