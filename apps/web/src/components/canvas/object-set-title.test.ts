import { describe, expect, it } from "vitest";

import {
  overrideFor, renderWhenEmptyOf, shouldRender, showIconOf, singleOf, titleFor,
} from "./object-set-title";

/** p.274's Object Set Title. */

const BASE = {
  single: false,
  typeName: "Sites",
  objectTitle: "Site 14",
  total: 42,
  override: "",
};

describe("the toggles", () => {
  it("are off unless a document says so", () => {
    // Every one of p.274's toggles is worded as something you enable, so
    // absence is the unenabled state — and a document written before a toggle
    // existed says nothing about it.
    expect(singleOf(undefined)).toBe(false);
    expect(showIconOf(undefined)).toBe(false);
    expect(renderWhenEmptyOf(undefined)).toBe(false);
    expect(singleOf(true)).toBe(true);
    expect(showIconOf(true)).toBe(true);
    expect(renderWhenEmptyOf(true)).toBe(true);
  });

  it("do not treat a truthy value as true", () => {
    // A raw JSON editor can put anything here.
    expect(singleOf("true")).toBe(false);
    expect(showIconOf(1)).toBe(false);
    expect(renderWhenEmptyOf("yes")).toBe(false);
  });
});

describe("p.274's title override", () => {
  it("applies when the widget is not showing a single object", () => {
    expect(overrideFor(false, "All open alerts")).toBe("All open alerts");
  });

  it("does not apply when it is", () => {
    // p.274: "This option is only available when Contains single object is
    // disabled." **Available is a statement about the panel; this makes it one
    // about the value too**, so an override left over from before the toggle
    // was flipped cannot quietly rename somebody's object.
    expect(overrideFor(true, "All open alerts")).toBeNull();
  });

  it("ignores a blank or non-text override", () => {
    expect(overrideFor(false, "")).toBeNull();
    expect(overrideFor(false, "   ")).toBeNull();
    expect(overrideFor(false, null)).toBeNull();
    expect(overrideFor(false, 7)).toBeNull();
  });
});

describe("the title", () => {
  it("is the object's own when the set holds one", () => {
    expect(titleFor({ ...BASE, single: true })).toBe("Site 14");
  });

  it("never falls back to the type name for a single object", () => {
    // **The dangerous fallback.** "Site" where "Site 14" was meant reads as a
    // real answer, and nothing on screen tells the reader it is not the
    // object's title.
    expect(titleFor({ ...BASE, single: true, objectTitle: undefined })).toBe("");
  });

  it("is the type name and the count when it does not", () => {
    expect(titleFor(BASE)).toBe("Sites · 42");
  });

  it("groups the count, because these are read not computed", () => {
    expect(titleFor({ ...BASE, total: 12345 })).toBe("Sites · 12,345");
  });

  it("prefers an override to the type and count", () => {
    expect(titleFor({ ...BASE, override: "Open alerts" })).toBe("Open alerts");
  });

  it("ignores an override while showing a single object", () => {
    // The same rule as `overrideFor`, asserted through the function callers
    // actually use — a guard that only holds one layer down is a guard the
    // next caller walks around.
    expect(titleFor({ ...BASE, single: true, override: "Open alerts" })).toBe("Site 14");
  });

  it("shows a bare count while the type is still resolving", () => {
    // A number with no noun is poor and beats an empty heading that fills in a
    // moment later.
    expect(titleFor({ ...BASE, typeName: undefined })).toBe("42");
  });

  it("reads an unknown count as none rather than as text", () => {
    expect(titleFor({ ...BASE, total: undefined })).toBe("Sites · 0");
  });
});

describe("p.274's render-when-empty", () => {
  it("does not render an empty set by default", () => {
    // p.274: "No: Default option. Widget will not render in the module view if
    // the inputted object set is empty."
    expect(shouldRender({ resolved: true, total: 0, renderWhenEmpty: false })).toBe(false);
  });

  it("renders an empty set when asked to", () => {
    expect(shouldRender({ resolved: true, total: 0, renderWhenEmpty: true })).toBe(true);
  });

  it("renders a set that has objects either way", () => {
    expect(shouldRender({ resolved: true, total: 1, renderWhenEmpty: false })).toBe(true);
    expect(shouldRender({ resolved: true, total: 1, renderWhenEmpty: true })).toBe(true);
  });

  it("renders while the answer is unknown", () => {
    // **Unresolved is not empty.** Treating it as zero would make every module
    // carrying this widget flash a gap on load and then fill it — the rule
    // `visibleWhen` follows for a section (§81), from the other direction.
    expect(shouldRender({ resolved: false, total: undefined, renderWhenEmpty: false })).toBe(true);
    expect(shouldRender({ resolved: true, total: undefined, renderWhenEmpty: false })).toBe(true);
  });
});
