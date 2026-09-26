import { describe, expect, it } from "vitest";

import { headerStyleOf, paddingTarget, styleTarget } from "./section-header";

describe("section header (p.58)", () => {
  it("is block unless it says otherwise", () => {
    expect(headerStyleOf("contained")).toBe("contained");
    expect(headerStyleOf("floating")).toBe("floating");
    expect(headerStyleOf("block")).toBe("block");
    expect(headerStyleOf(undefined)).toBe("block");
    expect(headerStyleOf("toString")).toBe("block");
  });

  it("moves the section's box to the body only for a floating header", () => {
    expect(styleTarget(true, "floating")).toBe("body");
    expect(styleTarget(true, "block")).toBe("section");
    expect(styleTarget(true, "contained")).toBe("section");
    // A floating style with no header to float is an ordinary section.
    expect(styleTarget(false, "floating")).toBe("section");
  });
});

describe("where the padding goes", () => {
  it("is the body's under a bar or a floating header, and the section's otherwise", () => {
    expect(paddingTarget(true, "block")).toBe("body");
    expect(paddingTarget(true, "floating")).toBe("body");
    expect(paddingTarget(true, "contained")).toBe("section");
    expect(paddingTarget(false, "block")).toBe("section");
  });
});
