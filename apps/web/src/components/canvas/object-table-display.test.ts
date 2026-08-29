import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import {
  DEFAULT_EMPTY_MESSAGE, DEFAULT_LINES, DEFAULT_NO_VALUE, EMPTY_MODES, MAX_LINES,
  cellStyle, emptyMessageOf, emptyModeOf, fillsCellOf, fitColumnsOf, frozenOf,
  linesOf, narrowHeadersOf, noValueOf, rowMinHeight, stickyLefts, wrapOf,
} from "./object-table-display";

/** p.224-225's Display & formatting block. */

/** The constant `widgets.tsx` multiplies the line count by. Restated here
 * because `widgets.tsx` is a `.tsx` file and importing one into a vitest
 * suite fails to parse; the test below pins it to the stylesheet, which is
 * the pair that can actually drift. */
const LINE_HEIGHT_IN_WIDGETS = 18;

describe("lines per row", () => {
  it("defaults to one and reads a number", () => {
    expect(DEFAULT_LINES).toBe(1);
    expect(linesOf(3)).toBe(3);
    expect(linesOf("4")).toBe(4);
  });

  it("treats absence as the default rather than as zero", () => {
    // **`Number(null)` is 0 and `Number("")` is 0** (§203), and a row of zero
    // lines is a row nobody can read. It arrives from a prop that is simply
    // missing, which is every table saved before this setting existed.
    //
    // The *clamp* is what makes this true, not a guard: the default and the
    // floor are both 1, so a coerced zero lands on the right answer anyway.
    // An explicit absence check here was dead code, and the harness said so.
    expect(linesOf(undefined)).toBe(DEFAULT_LINES);
    expect(linesOf(null)).toBe(DEFAULT_LINES);
    expect(linesOf("")).toBe(DEFAULT_LINES);
  });

  it("clamps what a document can name", () => {
    // Not an error anybody would see: a table drawn at zero height, or one row
    // taller than the page, just looks broken.
    expect(linesOf(0)).toBe(1);
    expect(linesOf(-5)).toBe(1);
    expect(linesOf(1e9)).toBe(MAX_LINES);
    expect(linesOf("abc")).toBe(DEFAULT_LINES);
    expect(linesOf(Infinity)).toBe(DEFAULT_LINES);
    expect(linesOf(2.7)).toBe(2);
  });
});

describe("value wrapping", () => {
  it("is off unless a document says otherwise", () => {
    // The shape every table already had. A stored default of "on" would change
    // how every module that predates the setting is drawn.
    expect(wrapOf(undefined)).toBe(false);
    expect(wrapOf(null)).toBe(false);
    expect(wrapOf("true")).toBe(false);
    expect(wrapOf(1)).toBe(false);
    expect(wrapOf(true)).toBe(true);
  });
});

describe("cell style", () => {
  it("lets text break only when wrapping is on", () => {
    expect(cellStyle(1, true).whiteSpace).toBe("normal");
    expect(cellStyle(1, false).whiteSpace).toBe("nowrap");
  });

  it("clamps only when text can break", () => {
    expect(cellStyle(3, true).WebkitLineClamp).toBe(3);
    expect(cellStyle(3, false).WebkitLineClamp).toBeUndefined();
  });

  it("leaves an unwrapped cell free to widen its column", () => {
    // **The clamp is not merely pointless without wrapping, it is harmful.** A
    // clamped, overflow-hidden box does not report the width its content needs,
    // so a `nowrap` value inside one is clipped where it should have widened
    // the column and let the grid scroll sideways. The browser suite is what
    // found it, and only because a *control* test asked whether an unfrozen
    // column scrolls away — without that, "the frozen column did not move"
    // passed against a table that could not scroll at all.
    expect(cellStyle(3, false).overflow).toBeUndefined();
    expect(cellStyle(3, true).overflow).toBe("hidden");
  });

  it("gives the row a height that follows the line count", () => {
    // p.224: the number "controls the height of each table row". Without this
    // a count above 1 would do nothing visible on a table of short values, and
    // a setting that sometimes does nothing is not trusted the rest of the time.
    expect(rowMinHeight(1, 18)).toBe(18);
    expect(rowMinHeight(3, 18)).toBe(54);
  });
});

describe("the line height the row height is built from", () => {
  it("is the one the stylesheet gives a grid cell", () => {
    // **Two files that have to agree**, and nothing else makes them. p.224's
    // line count becomes a pixel height by multiplying, so a stylesheet change
    // would silently make every multi-line row the wrong height — visible only
    // as rows that look slightly off, which is the kind of wrong nobody
    // reports. Read from the stylesheet rather than restated.
    const css = readFileSync(
      new URL("../../app/globals.css", import.meta.url), "utf8",
    );
    const grid = /\.data-grid td \{([^}]*)\}/.exec(css);
    expect(grid, ".data-grid td not found - renamed?").not.toBeNull();
    const height = /line-height:\s*(\d+)px/.exec(grid![1]!);
    expect(height, "no line-height on .data-grid td").not.toBeNull();
    expect(Number(height![1])).toBe(LINE_HEIGHT_IN_WIDGETS);
  });
});

describe("frozen columns", () => {
  it("defaults to none and reads a number", () => {
    expect(frozenOf(undefined, 5)).toBe(0);
    expect(frozenOf(null, 5)).toBe(0);
    expect(frozenOf("", 5)).toBe(0);
    expect(frozenOf(2, 5)).toBe(2);
    expect(frozenOf("2", 5)).toBe(2);
  });

  it("clamps to the columns that exist", () => {
    // A property can be removed from the object type long after a table was
    // pointed at it, so the count can outlive the columns it named.
    expect(frozenOf(9, 3)).toBe(3);
    expect(frozenOf(-2, 3)).toBe(0);
    expect(frozenOf(2, 0)).toBe(0);
    expect(frozenOf("abc", 3)).toBe(0);
  });

  it("pins each frozen column at the running total of the ones before it", () => {
    // **Cumulative, which is the half CSS cannot do.** A sticky column sits at
    // a fixed distance from the left edge, and the second one's distance is
    // the first one's width.
    expect(stickyLefts([40, 60, 80], 2)).toEqual([0, 40, null]);
    expect(stickyLefts([40, 60, 80], 3)).toEqual([0, 40, 100]);
  });

  it("pins nothing when nothing is frozen", () => {
    expect(stickyLefts([40, 60], 0)).toEqual([null, null]);
  });

  it("survives a width it could not measure", () => {
    // A cell that has not been laid out yet reports nothing useful, and a NaN
    // running total would unpin every column after it.
    expect(stickyLefts([40, NaN, 80], 3)).toEqual([0, 40, 40]);
  });
});

describe("the empty state", () => {
  it("has p.224's two modes and defaults to the default one", () => {
    expect(Object.keys(EMPTY_MODES).sort()).toEqual(["custom", "default"]);
    expect(emptyModeOf(undefined)).toBe("default");
    expect(emptyModeOf("custom")).toBe("custom");
    expect(emptyModeOf("something else")).toBe("default");
  });

  it("says p.224's words unless a custom message is set", () => {
    expect(DEFAULT_EMPTY_MESSAGE).toBe("No objects found");
    expect(emptyMessageOf("default", "ignored")).toBe(DEFAULT_EMPTY_MESSAGE);
    expect(emptyMessageOf("custom", "Nothing here yet")).toBe("Nothing here yet");
  });

  it("falls back rather than showing nothing", () => {
    // An author who switched the mode and has not typed yet should still see a
    // table that explains itself.
    expect(emptyMessageOf("custom", "")).toBe(DEFAULT_EMPTY_MESSAGE);
    expect(emptyMessageOf("custom", "   ")).toBe(DEFAULT_EMPTY_MESSAGE);
    expect(emptyMessageOf("custom", null)).toBe(DEFAULT_EMPTY_MESSAGE);
    expect(emptyMessageOf("custom", 7)).toBe(DEFAULT_EMPTY_MESSAGE);
  });
});

describe("the no-value display", () => {
  it("says p.224's words by default", () => {
    expect(DEFAULT_NO_VALUE).toBe("No value");
    expect(noValueOf(undefined, "x")).toBe(DEFAULT_NO_VALUE);
    expect(noValueOf(false, "x")).toBe(DEFAULT_NO_VALUE);
  });

  it("takes an override, including an empty one", () => {
    // **An empty string is a real answer**, not a missing one: "show nothing
    // where there is nothing" is a legitimate thing to configure, which is why
    // this checks the type rather than the truthiness.
    expect(noValueOf(true, "—")).toBe("—");
    expect(noValueOf(true, "")).toBe("");
  });

  it("falls back when the override is not text", () => {
    expect(noValueOf(true, null)).toBe(DEFAULT_NO_VALUE);
    expect(noValueOf(true, 7)).toBe(DEFAULT_NO_VALUE);
  });
});

describe("the table-level flags", () => {
  it("fits columns unless a document turns it off", () => {
    // **Default on, and the divergence is deliberate.** p.225 words it as
    // something you enable, so Foundry's default is presumably off — but every
    // table this platform has drawn is full-width, and defaulting to off would
    // restyle every saved module the day it shipped.
    expect(fitColumnsOf(undefined)).toBe(true);
    expect(fitColumnsOf(true)).toBe(true);
    expect(fitColumnsOf(false)).toBe(false);
  });

  it("keeps narrow headers and cell-filling formatting off by default", () => {
    // Both are additions to what the table already did, so absence means the
    // old behaviour.
    expect(narrowHeadersOf(undefined)).toBe(false);
    expect(narrowHeadersOf(true)).toBe(true);
    expect(narrowHeadersOf("true")).toBe(false);
    expect(fillsCellOf(undefined)).toBe(false);
    expect(fillsCellOf(true)).toBe(true);
    expect(fillsCellOf(1)).toBe(false);
  });
});
