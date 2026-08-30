import { describe, expect, it } from "vitest";

import {
  DEFAULT_INVALID_STATE, INVALID_STATES,
  formVisible, headerTitleOf, hideHeaderOf, invalidStateOf, localDefaultsOf,
} from "./action-form";

/** p.510-513's Inline Action widget. */

describe("p.513's form state if invalid", () => {
  it("has the two states p.513 names and defaults to disabled", () => {
    expect(Object.keys(INVALID_STATES).sort()).toEqual(["disabled", "hidden"]);
    expect(DEFAULT_INVALID_STATE).toBe("disabled");
    expect(invalidStateOf(undefined)).toBe("disabled");
    expect(invalidStateOf("hidden")).toBe("hidden");
  });

  it("falls back for a state the widget does not have", () => {
    expect(invalidStateOf("greyed")).toBe("disabled");
    expect(invalidStateOf("constructor")).toBe("disabled");
    expect(invalidStateOf(0)).toBe("disabled");
  });
});

describe("whether the form is drawn", () => {
  it("is drawn when the criteria are met", () => {
    expect(formVisible({ invalidState: "hidden", valid: true })).toBe(true);
    expect(formVisible({ invalidState: "disabled", valid: true })).toBe(true);
  });

  it("is drawn while the answer is still being asked for", () => {
    // **`undefined` is neither valid nor invalid.** A form that vanished
    // mid-check and reappeared a moment later would flicker on every object a
    // viewer clicks — §210's rule that unresolved is not empty.
    expect(formVisible({ invalidState: "hidden", valid: undefined })).toBe(true);
  });

  it("is removed only by the hidden state", () => {
    expect(formVisible({ invalidState: "hidden", valid: false })).toBe(false);
    // The other state keeps the form and disables it, which is p.513's point:
    // a reader can see what they would be submitting and why they cannot.
    expect(formVisible({ invalidState: "disabled", valid: false })).toBe(true);
    expect(formVisible({ invalidState: undefined, valid: false })).toBe(true);
  });
});

describe("p.512's custom action title", () => {
  it("replaces the action's own name", () => {
    expect(headerTitleOf("Close this ticket", "Close ticket")).toBe("Close this ticket");
  });

  it("is trimmed, and a blank one is not a title", () => {
    expect(headerTitleOf("  Close  ", "Close ticket")).toBe("Close");
    expect(headerTitleOf("   ", "Close ticket")).toBe("Close ticket");
    expect(headerTitleOf("", "Close ticket")).toBe("Close ticket");
    expect(headerTitleOf(undefined, "Close ticket")).toBe("Close ticket");
    expect(headerTitleOf(7, "Close ticket")).toBe("Close ticket");
  });

  it("still says something when there is no action to name", () => {
    // The header renders before the action list has arrived, and an empty
    // heading is a gap a reader cannot interpret.
    expect(headerTitleOf("", undefined)).toBe("Action");
    expect(headerTitleOf(undefined, "")).toBe("Action");
  });
});

describe("p.513's hide header", () => {
  it("is off unless a document says so", () => {
    expect(hideHeaderOf(undefined)).toBe(false);
    expect(hideHeaderOf("true")).toBe(false);
    expect(hideHeaderOf(true)).toBe(true);
  });
});

describe("p.512's local parameter defaults", () => {
  it("reads what a document holds", () => {
    expect(localDefaultsOf({ status: "triaged", priority: 2 }))
      .toEqual({ status: "triaged", priority: 2 });
  });

  it("is empty for anything that is not an object of names", () => {
    expect(localDefaultsOf(undefined)).toEqual({});
    expect(localDefaultsOf("status=triaged")).toEqual({});
    // An array is `typeof "object"`, and its indices would become parameter
    // names — which is a default for a parameter called "0".
    expect(localDefaultsOf(["triaged"])).toEqual({});
  });

  it("drops entries that name nothing", () => {
    expect(localDefaultsOf({ "": "x", "   ": "y", status: "triaged" }))
      .toEqual({ status: "triaged" });
  });

  it("drops an empty default rather than seeding a blank", () => {
    // **`null` is how the raw JSON editor spells "no default".** Kept, it would
    // beat the parameter's own default (p.27) with nothing at all, which is
    // exactly what p.512 says an unspecified local default must not do.
    expect(localDefaultsOf({ status: null, priority: undefined, note: "" }))
      .toEqual({ note: "" });
  });

  it("keeps values that only look empty", () => {
    expect(localDefaultsOf({ count: 0, flag: false })).toEqual({ count: 0, flag: false });
  });
});
