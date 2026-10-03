import { describe, expect, it } from "vitest";

import { INNER_SECTION_STYLES, innerStyleOf, ownLook, sectionLook } from "./inner-section-style";

/** p.62's Inner section style (§704): eight presets over three settings a
 * section already has, filling only what a child leaves unset. */

describe("INNER_SECTION_STYLES", () => {
  it("is p.62's eight, in p.62's order", () => {
    expect(Object.values(INNER_SECTION_STYLES).map((s) => s.label)).toEqual([
      "Classic", "Classic elevated", "Classic gray",
      "Minimal", "Minimal elevated", "Minimal ghost",
      "Muted white", "Muted gray",
    ]);
  });

  it("puts the title in a bar for Classic, above the box for Minimal, inside it for Muted", () => {
    const formats = Object.fromEntries(
      Object.entries(INNER_SECTION_STYLES).map(([name, s]) => [name, s.headerStyle]));
    expect(formats).toEqual({
      classic: "block", "classic-elevated": "block", "classic-gray": "block",
      minimal: "floating", "minimal-elevated": "floating", "minimal-ghost": "floating",
      "muted-white": "contained", "muted-gray": "contained",
    });
  });
});

describe("innerStyleOf", () => {
  it("reads a known name and nothing else", () => {
    expect(innerStyleOf("minimal")?.label).toBe("Minimal");
    expect(innerStyleOf("bold")).toBeNull();
    expect(innerStyleOf(null)).toBeNull();
    expect(innerStyleOf("toString")).toBeNull();
  });
});

describe("sectionLook", () => {
  it("is the section's own values, unchanged, with no preset", () => {
    expect(sectionLook({ headerStyle: "contained", border: "bordered", background: "#123456" }, null))
      .toEqual({ headerStyle: "contained", border: "bordered", background: "#123456", body: null });
    expect(sectionLook({}, undefined))
      .toEqual({ headerStyle: null, border: null, background: null, body: null });
  });

  it("fills every unset value from the preset", () => {
    expect(sectionLook({ headerStyle: null, border: null, background: "" }, "minimal-elevated"))
      .toEqual({ headerStyle: "floating", border: "shadow-outer", background: "shade-1", body: null });
  });

  it("keeps each value the section set, one at a time", () => {
    expect(sectionLook({ headerStyle: "contained" }, "classic")).toMatchObject(
      { headerStyle: "contained", border: "bordered", background: "shade-1" });
    expect(sectionLook({ border: "borderless" }, "classic")).toMatchObject(
      { headerStyle: "block", border: "borderless", background: "shade-1" });
    expect(sectionLook({ background: "transparent" }, "classic")).toMatchObject(
      { headerStyle: "block", border: "bordered", background: "transparent" });
  });

  it("greys Classic gray's body under a white bar, unless the section chose a colour", () => {
    expect(sectionLook({}, "classic-gray")).toMatchObject({ background: "shade-1", body: "shade-3" });
    expect(sectionLook({ background: "#ff0000" }, "classic-gray"))
      .toMatchObject({ background: "#ff0000", body: null });
  });
});

describe("ownLook", () => {
  it("names the values hiding the preset", () => {
    expect(ownLook({ headerStyle: "block", border: null, background: "shade-4" }, "minimal"))
      .toEqual(["headerStyle", "background"]);
    expect(ownLook({}, "minimal")).toEqual([]);
  });

  it("is nothing without a preset", () => {
    expect(ownLook({ headerStyle: "block", border: "bordered" }, null)).toEqual([]);
    expect(ownLook({ headerStyle: "block" }, "nonsense")).toEqual([]);
  });
});
