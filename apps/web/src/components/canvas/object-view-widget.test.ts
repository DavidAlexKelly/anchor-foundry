import { describe, expect, it } from "vitest";

import {
  DEFAULT_EMPTY_MESSAGE, DEFAULT_VIEW_MODE, VIEW_MODES,
  allowToggleOf, emptyMessageOf, hideHeaderOf, viewModeOf,
} from "./object-view-widget";

/** p.259-263's Object View widget. */

describe("p.261's Object View Mode", () => {
  it("has the two options p.261 names and defaults to the configured one", () => {
    expect(Object.keys(VIEW_MODES).sort()).toEqual(["configured", "standard"]);
    expect(DEFAULT_VIEW_MODE).toBe("configured");
    expect(viewModeOf(undefined)).toBe("configured");
    expect(viewModeOf("standard")).toBe("standard");
  });

  it("falls back for a mode the widget does not have", () => {
    expect(viewModeOf("panel")).toBe("configured");
    expect(viewModeOf("constructor")).toBe("configured");
    expect(viewModeOf(3)).toBe("configured");
  });
});

describe("p.261's toggle between the two views", () => {
  it("is offered unless the document turned it off", () => {
    // **On by default is an argument, not a convention**: `object-views` p.2
    // says the standard view stays accessible, so a module that never touched
    // this setting must not be narrower than the platform promises.
    expect(allowToggleOf(undefined)).toBe(true);
    expect(allowToggleOf(true)).toBe(true);
    expect(allowToggleOf(false)).toBe(false);
  });

  it("is not turned off by anything that merely looks false", () => {
    // The prop is a checkbox; a document holding a string came from somewhere
    // else, and "off" is the answer that removes something a reader is
    // promised — so it takes the actual value.
    expect(allowToggleOf("false")).toBe(true);
    expect(allowToggleOf(0)).toBe(true);
    expect(allowToggleOf(null)).toBe(true);
  });

  // **Whether the switch is offered at all is not decided here.** `ObjectView`
  // withholds it when the type has no configured view, and the harness proved
  // that a second copy of that rule in this file could not change anything:
  // `e2e/test_object_view_widget.py` covers it where it lives.
});

describe("p.262's hide header", () => {
  it("is off unless a document says so", () => {
    expect(hideHeaderOf(undefined)).toBe(false);
    expect(hideHeaderOf("true")).toBe(false);
    expect(hideHeaderOf(true)).toBe(true);
  });
});

describe("p.262's empty state message", () => {
  it("uses the configured message", () => {
    expect(emptyMessageOf("Pick a flight")).toBe("Pick a flight");
  });

  it("trims it, so a stray space is not a message", () => {
    expect(emptyMessageOf("  Pick a flight  ")).toBe("Pick a flight");
  });

  it("falls back when there is nothing to say", () => {
    expect(emptyMessageOf(undefined)).toBe(DEFAULT_EMPTY_MESSAGE);
    expect(emptyMessageOf("")).toBe(DEFAULT_EMPTY_MESSAGE);
    expect(emptyMessageOf("   ")).toBe(DEFAULT_EMPTY_MESSAGE);
    expect(emptyMessageOf(7)).toBe(DEFAULT_EMPTY_MESSAGE);
    // Asserted as a literal too: `toBe(DEFAULT_…)` alone derives the
    // expectation from its own subject and would follow the constant anywhere
    // it moved (§201).
    expect(DEFAULT_EMPTY_MESSAGE).toBe("No object to show");
  });
});
