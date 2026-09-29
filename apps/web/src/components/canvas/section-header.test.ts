import { describe, expect, it } from "vitest";

import { headerCount, headerStyleOf, paddingTarget, styleTarget } from "./section-header";

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

  it("puts the first widgets in the header, and none without one (p.14)", () => {
    expect(headerCount(2, 5, true)).toBe(2);
    expect(headerCount(2, 5, false)).toBe(0);
    // More than there are, or nonsense, clamps rather than inventing widgets.
    expect(headerCount(9, 3, true)).toBe(3);
    expect(headerCount(-1, 3, true)).toBe(0);
    expect(headerCount(1.8, 3, true)).toBe(1);
    expect(headerCount("2", 3, true)).toBe(0);
    expect(headerCount(Number.NaN, 3, true)).toBe(0);
    expect(headerCount(undefined, 3, true)).toBe(0);
  });
});
