import { describe, expect, it } from "vitest";

import {
  DEFAULT_EMPTY_MESSAGE, DEFAULT_VIEW_MODE, VIEW_MODES,
  allowToggleOf, emptyMessageOf, hideHeaderOf, showsToggle, startsStandard, viewModeOf,
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

describe("which view opens", () => {
  it("opens the configured one by default when there is one", () => {
    expect(startsStandard({ mode: undefined, hasConfigured: true })).toBe(false);
  });

  it("opens the standard one when the document asks for it", () => {
    // **`hasConfigured: true` is load-bearing.** With no configured view the
    // answer is `true` whatever the mode says, so a test written without one
    // would pass against a version that ignored the mode entirely.
    expect(startsStandard({ mode: "standard", hasConfigured: true })).toBe(true);
  });

  it("opens the standard one when the type has no configured view", () => {
    // A view can be unpublished long after the module was saved. A widget that
    // honoured the stale preference would render nothing where an object
    // should be — and the object is still perfectly viewable.
    expect(startsStandard({ mode: "configured", hasConfigured: false })).toBe(true);
    expect(startsStandard({ mode: undefined, hasConfigured: false })).toBe(true);
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

  it("is never offered when there is nothing to switch to", () => {
    // Two buttons where one leads nowhere is a control that lies about what
    // the platform has.
    expect(showsToggle({ allowToggle: true, hasConfigured: false })).toBe(false);
    expect(showsToggle({ allowToggle: undefined, hasConfigured: false })).toBe(false);
  });

  it("is offered when there is a configured view and the setting allows it", () => {
    expect(showsToggle({ allowToggle: undefined, hasConfigured: true })).toBe(true);
    expect(showsToggle({ allowToggle: false, hasConfigured: true })).toBe(false);
  });
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
