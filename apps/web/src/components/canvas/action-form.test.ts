import { describe, expect, it } from "vitest";

import { inputTypeFor, seedActionForm } from "./pure";

/** The action form's starting values (decision 0007; Foundry p.25, p.27).
 *
 * The form itself is checked in `e2e/test_action_parameters.py` - what a
 * browser draws is a browser's question. What is here is the ordering of the
 * three sources, which is arithmetic and belongs where it can be asked
 * directly.
 */
const parameter = (over: Partial<Parameters<typeof seedActionForm>[0][number]> = {}) => ({
  api_name: "status",
  data_type: "string",
  hidden: false,
  ...over,
});

describe("seedActionForm", () => {
  it("starts from the object's current value", () => {
    expect(seedActionForm([parameter()], { status: "open" })).toEqual({ status: "open" });
  });

  it("falls back to the parameter's default when the object has nothing", () => {
    // p.27's default values, and the case that matters: a parameter not named
    // after a property never has a current value to start from.
    expect(seedActionForm([parameter({ api_name: "reason", default_value: "routine" })], {}))
      .toEqual({ reason: "routine" });
  });

  it("prefers the object's value over the default", () => {
    expect(
      seedActionForm([parameter({ default_value: "triaged" })], { status: "open" }),
    ).toEqual({ status: "open" });
  });

  it("treats a null property as nothing, not as a value", () => {
    // A synced row with an empty column arrives as null. Rendering "null" in
    // the box and submitting it would write the four characters.
    expect(seedActionForm([parameter({ default_value: "triaged" })], { status: null }))
      .toEqual({ status: "triaged" });
    expect(seedActionForm([parameter()], { status: null })).toEqual({ status: "" });
  });

  it("keeps zero and false, which are values", () => {
    // The same trap §125 and §128 both hit: written as a falsiness check, this
    // would replace a real 0 with the default.
    expect(seedActionForm([parameter({ api_name: "n", default_value: 9 })], { n: 0 }))
      .toEqual({ n: "0" });
    expect(seedActionForm([parameter({ api_name: "ok", default_value: true })], { ok: false }))
      .toEqual({ ok: "false" });
  });

  it("seeds hidden parameters too", () => {
    // p.25's whole point: a hidden parameter carries a value the rules use -
    // in Foundry's own example, the *previous* value to compare against. A
    // form that skipped them would leave the action unable to receive what it
    // was built for. Hidden means undrawn, not unsent.
    expect(seedActionForm([parameter({ hidden: true })], { status: "open" }))
      .toEqual({ status: "open" });
  });

  it("renders a structured value as JSON rather than [object Object]", () => {
    // §125, one component over.
    expect(
      seedActionForm([parameter({ api_name: "site" })], { site: { lat: 51.5, lon: -0.1 } }),
    ).toEqual({ site: '{"lat":51.5,"lon":-0.1}' });
  });
});

describe("inputTypeFor", () => {
  it("gives numbers a number field and dates a date field", () => {
    expect(inputTypeFor("integer")).toBe("number");
    expect(inputTypeFor("float")).toBe("number");
    expect(inputTypeFor("date")).toBe("date");
  });

  it("leaves everything else as text, because the server coerces", () => {
    // A browser-side type stricter than `coerce_property_value` would refuse
    // values the platform accepts - a timestamp typed as `datetime-local`
    // cannot express an offset, and ours preserve one.
    expect(inputTypeFor("timestamp")).toBe("text");
    expect(inputTypeFor("geopoint")).toBe("text");
    expect(inputTypeFor("string")).toBe("text");
  });
});
