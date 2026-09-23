import { describe, expect, it } from "vitest";

import {
  DEFAULT_HINT, MAX_GLYPH, glyph, iconHint, iconProblem, isIconSetName,
  storedNameNote, swatch,
} from "./object-type-icon";

describe("isIconSetName", () => {
  it("reads a stored Foundry name as a name", () => {
    // The column is 64 characters wide and defaults to "cube", because it was
    // written to hold one.
    expect(isIconSetName("cube")).toBe(true);
    expect(isIconSetName("shopping-cart")).toBe(true);
  });

  it("reads one or two characters as a glyph", () => {
    expect(isIconSetName("🚢")).toBe(false);
    expect(isIconSetName("A")).toBe(false);
    expect(isIconSetName("AB")).toBe(false);
  });

  it("reads nothing as nothing", () => {
    expect(isIconSetName("")).toBe(false);
    expect(isIconSetName("   ")).toBe(false);
    expect(isIconSetName(null)).toBe(false);
    expect(isIconSetName(undefined)).toBe(false);
  });

  it("draws the line where MAX_GLYPH says", () => {
    expect(MAX_GLYPH).toBe(2);
    expect(isIconSetName("AB")).toBe(false);
    expect(isIconSetName("ABC")).toBe(true);
  });
});

describe("glyph", () => {
  it("uses the mark somebody typed", () => {
    expect(glyph({ display_name: "Ship", icon: "🚢" })).toBe("🚢");
    expect(glyph({ display_name: "Ship", icon: "AB" })).toBe("AB");
  });

  it("falls back to the type's initial for a stored Foundry name", () => {
    // "cube" drawn as "cu" would put two letters of a word nobody chose on
    // every card in the Explorer.
    expect(glyph({ display_name: "Ship", icon: "cube" })).toBe("S");
  });

  it("falls back to the initial when no icon was chosen", () => {
    expect(glyph({ display_name: "Ship", icon: null })).toBe("S");
    expect(glyph({ display_name: "Ship", icon: "   " })).toBe("S");
    expect(glyph({ display_name: "Ship" })).toBe("S");
  });

  it("uses the api name when there is no display name", () => {
    expect(glyph({ api_name: "ship_type", icon: "cube" })).toBe("S");
  });

  it("never draws nothing", () => {
    // A blank mark beside a name is a rendering fault to look at.
    expect(glyph({})).toBe("?");
    expect(glyph({ display_name: "   ", icon: "cube" })).toBe("?");
  });

  it("takes a whole character rather than half of one", () => {
    // An emoji is two UTF-16 units, so `charAt(0)` on a name beginning with
    // one produces a lone surrogate — a box, not a letter.
    expect(glyph({ display_name: "🚢 Fleet", icon: "cube" })).toBe("🚢");
  });

  it("upper-cases the initial it falls back to", () => {
    expect(glyph({ display_name: "ship", icon: "cube" })).toBe("S");
  });
});

describe("swatch", () => {
  it("uses the colour that was chosen", () => {
    expect(swatch({ colour: "#b3261e" })).toBe("#b3261e");
  });

  it("falls back to the theme's accent rather than to a colour of its own", () => {
    // A default written in here stops following the theme the moment the
    // theme changes.
    expect(swatch({ colour: null })).toBe("var(--accent)");
    expect(swatch({ colour: "  " })).toBe("var(--accent)");
    expect(swatch({})).toBe("var(--accent)");
  });
});

describe("iconProblem", () => {
  it("says nothing about an empty field", () => {
    // Empty is a choice: the type falls back to its initial.
    expect(iconProblem("")).toBeNull();
    expect(iconProblem("  ")).toBeNull();
  });

  it("says nothing about one or two characters", () => {
    expect(iconProblem("🚢")).toBeNull();
    expect(iconProblem("AB")).toBeNull();
  });

  it("refuses the paragraph somebody pasted", () => {
    // Stored, read back as a name, and silently drawn as an initial — the
    // field would look broken rather than full.
    expect(iconProblem("a long description")).toContain("One or two characters");
  });
});

describe("storedNameNote", () => {
  it("explains a value that came from Foundry's icon set", () => {
    // Not a problem: the type predates the control, and the reader needs to
    // know why the mark is a letter.
    const said = storedNameNote("cube");
    expect(said).toContain("cube");
    expect(said).toContain("first letter");
  });

  it("says nothing about a glyph or an empty field", () => {
    expect(storedNameNote("🚢")).toBeNull();
    expect(storedNameNote("")).toBeNull();
    expect(storedNameNote(null)).toBeNull();
  });
});

describe("iconHint", () => {
  it("explains a stored Foundry name rather than refusing it", () => {
    // **The defect the browser suite found.** The editor had the two in a
    // fallback chain, and `iconProblem` matched first on "cube" — so every
    // type in the corpus was told it had typed something wrong.
    expect(iconHint("cube", "cube")).toContain("icon name from Foundry");
  });

  it("refuses a long value somebody has just put there", () => {
    // **Asserted on the half the two sentences do not share.** Both open with
    // "One or two characters", so a `toContain` on that passed over a mutant
    // that always returned the plain rule — the refusal and the default read
    // alike until the second clause.
    expect(iconHint("a long description", "cube")).not.toBe(DEFAULT_HINT);
    expect(iconHint("a long description", "cube")).toContain("no icon library");
  });

  it("gives the plain rule for an ordinary value", () => {
    expect(iconHint("🚢", "cube")).toBe(DEFAULT_HINT);
    expect(iconHint("", "cube")).toBe(DEFAULT_HINT);
    expect(iconHint("🚢", "🚢")).toBe(DEFAULT_HINT);
  });

  it("treats a null stored icon as an empty one", () => {
    expect(iconHint("", null)).toBe(DEFAULT_HINT);
    expect(iconHint("", undefined)).toBe(DEFAULT_HINT);
  });

  it("says what a blank field does, because that is a choice", () => {
    expect(DEFAULT_HINT).toContain("first letter");
  });
});
