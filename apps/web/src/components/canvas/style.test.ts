import { describe, expect, it } from "vitest";

import {
  BACKGROUND_PRESETS, BORDERS, LIGHT_TEXT_BELOW, PADDINGS,
  isDarkBackground, paddingFor, relativeLuminance, resolveBackground, schemeFor, styleFor,
} from "./style";

/** Style formatting (Foundry `workshop` p.57-62).
 *
 * Mostly values, and the values are p.62's own numbers - which is the reason
 * they are tested at all: a panel that used 20px where the page says 24 would
 * look plausible and be wrong, and nothing else in the system would object.
 *
 * The one rule is p.59-60's brightness switch, and it has the tests to match.
 */

describe("p.62's padding scale", () => {
  it("uses p.62's own numbers, including the two that are not square", () => {
    // "Regular: Adds 24 pixels of top/bottom padding and 48 pixels of
    // left/right padding"; "Large: … 40 … and 62". A single number per option
    // is the shape that quietly loses this.
    expect(PADDINGS.none).toEqual([0, 0]);
    expect(PADDINGS.compact).toEqual([16, 16]);
    expect(PADDINGS.regular).toEqual([24, 48]);
    expect(PADDINGS.large).toEqual([40, 62]);
  });

  it("reads a custom padding only when custom is chosen", () => {
    expect(paddingFor({ padding: "compact", customPadding: [99, 99] })).toEqual([16, 16]);
    expect(paddingFor({ padding: "custom", customPadding: [8, 20] })).toEqual([8, 20]);
  });

  it("treats an unfilled custom padding as none", () => {
    // The builder chose Custom and left it. Falling back to Regular would put
    // padding on a section nobody asked to pad.
    expect(paddingFor({ padding: "custom" })).toEqual([0, 0]);
    expect(paddingFor({ padding: "custom", customPadding: [-4, 10] })).toEqual([0, 10]);
  });

  it("defaults to none, which is what every module saved before this had", () => {
    expect(paddingFor({})).toEqual([0, 0]);
  });
});

describe("resolveBackground", () => {
  it("resolves a preset name to its colour", () => {
    expect(resolveBackground("shade-3")).toBe(BACKGROUND_PRESETS["shade-3"]);
  });

  it("treats transparent and unset as the same nothing", () => {
    expect(resolveBackground("transparent")).toBeNull();
    expect(resolveBackground("")).toBeNull();
    expect(resolveBackground(null)).toBeNull();
    expect(resolveBackground(undefined)).toBeNull();
  });

  it("accepts a custom hex, with or without the hash and in either length", () => {
    // p.59: "apply a custom hex color to section and page backgrounds". This
    // value is typed by hand, and a picker that ignored `abc` would look like
    // a broken control rather than a rejected input.
    expect(resolveBackground("#123456")).toBe("#123456");
    expect(resolveBackground("123456")).toBe("#123456");
    expect(resolveBackground("#ABC")).toBe("#aabbcc");
  });

  it("passes anything else through, because this prop predates the presets", () => {
    // **Compatibility, not looseness.** A Container's background has been a
    // free-text CSS colour since the first canvas; rejecting `red` in the name
    // of validation would blank a background somebody is looking at.
    expect(resolveBackground("red")).toBe("red");
    expect(resolveBackground("var(--panel)")).toBe("var(--panel)");
  });

  it("does not try to measure a colour it cannot parse", () => {
    // A free-text value is a real background whose brightness is unknown.
    // Guessing would flip a section's text on a value nothing read.
    expect(isDarkBackground("red")).toBe(false);
    expect(isDarkBackground("var(--ink)")).toBe(false);
  });
});

describe("p.59-60's brightness rule", () => {
  it("puts light text on a dark background and dark text on a light one", () => {
    expect(isDarkBackground("#000000")).toBe(true);
    expect(isDarkBackground("#16232f")).toBe(true); // the platform's own ink
    expect(isDarkBackground("#ffffff")).toBe(false);
    expect(isDarkBackground("#fafbfb")).toBe(false);
  });

  it("weights the channels rather than averaging them", () => {
    // **The test that catches the tempting shortcut.** A saturated blue and a
    // saturated yellow have the same naive channel average and could not be
    // less alike to read against: one needs white text, the other black.
    expect(isDarkBackground("#0000ff")).toBe(true);
    expect(isDarkBackground("#ffff00")).toBe(false);
    expect(relativeLuminance("#ffff00")).toBeGreaterThan(relativeLuminance("#0000ff"));
  });

  it("crosses over where WCAG's contrast formula does, not at a round half", () => {
    // 0.5 is the obvious threshold and it is far too high: a mid-grey that
    // black text reads better on would get white text.
    expect(LIGHT_TEXT_BELOW).toBeGreaterThan(0.17);
    expect(LIGHT_TEXT_BELOW).toBeLessThan(0.19);
    // #767676 is the classic "lowest grey that passes on white" and sits just
    // above the crossover, so it takes dark text.
    expect(isDarkBackground("#767676")).toBe(false);
    expect(isDarkBackground("#595959")).toBe(true);
  });

  it("does not call a transparent background dark", () => {
    // A transparent section inherits whatever is behind it. Claiming to know
    // that colour is how a section flips to white text over a white page.
    expect(isDarkBackground(null)).toBe(false);
    expect(isDarkBackground("transparent")).toBe(false);
  });

  it("is what schemeFor reports, and only then", () => {
    expect(schemeFor({ background: "#16232f" })).toBe("dark");
    expect(schemeFor({ background: "shade-2" })).toBeUndefined();
    expect(schemeFor({})).toBeUndefined();
  });
});

describe("styleFor", () => {
  it("is empty for a widget nobody styled", () => {
    // Every module in the corpus predates these props. An empty object is the
    // difference between "renders as it always did" and "renders in a box".
    expect(styleFor({})).toEqual({});
  });

  it("writes the padding as top/bottom then left/right", () => {
    expect(styleFor({ padding: "regular" }).padding).toBe("24px 48px");
  });

  it("omits the padding rather than writing a zero", () => {
    // `padding: 0px 0px` overrides a stylesheet; an absent property does not,
    // and "no padding" must not be a way of removing padding somebody else set.
    expect(styleFor({ padding: "none" }).padding).toBeUndefined();
  });

  it("gives borderless no border and no shadow at all", () => {
    // p.60: "No outline around the section or widget so it blends into the
    // background." A borderless section that still drew a rounded corner would
    // be visible against a differently coloured parent.
    expect(styleFor({ border: "borderless" })).toEqual({});
  });

  it("distinguishes p.60's two shadows by where they fall", () => {
    const outer = styleFor({ border: "shadow-outer" }).boxShadow!;
    const inner = styleFor({ border: "shadow-inner" }).boxShadow!;
    expect(outer).not.toContain("inset");
    expect(inner).toContain("inset");
  });

  it("covers every border p.60 names", () => {
    // A switch that quietly returned nothing for one of them would look like
    // Borderless, which is a real option - so the miss would be invisible.
    for (const border of BORDERS) {
      expect(() => styleFor({ border })).not.toThrow();
    }
    expect(BORDERS).toHaveLength(4);
  });

  it("combines the three independently", () => {
    const style = styleFor({ background: "#123456", padding: "compact", border: "bordered" });
    expect(style.background).toBe("#123456");
    expect(style.padding).toBe("16px 16px");
    expect(style.border).toBe("1px solid var(--line)");
  });
});
