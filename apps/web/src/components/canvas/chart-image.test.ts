/** §529: p.309's chart as a picture. The drawing needs a browser, and
 * `e2e/test_pie_chart.py` downloads one; these are the parts that do not. */
import { describe, expect, it } from "vitest";

import { PAINT, copyProblem, imageFileName } from "./chart-image";

describe("the file name", () => {
  it("is the chart's words, lower-cased and joined", () => {
    expect(imageFileName("count by region")).toBe("count-by-region.png");
    expect(imageFileName("  Sum of Capacity / Site!! ")).toBe("sum-of-capacity-site.png");
  });

  it("is chart when there are no words", () => {
    expect(imageFileName("")).toBe("chart.png");
    expect(imageFileName(null)).toBe("chart.png");
    expect(imageFileName("!!!")).toBe("chart.png");
  });

  it("is at most eighty characters before the extension, never ending in a dash", () => {
    const name = imageFileName(`${"a".repeat(79)} b`);
    expect(name).toBe(`${"a".repeat(79)}.png`);
    expect(imageFileName("x".repeat(200))).toBe(`${"x".repeat(80)}.png`);
  });
});

describe("what a standalone SVG carries", () => {
  it("includes the paint a chart takes from its stylesheet", () => {
    for (const name of ["fill", "stroke", "stroke-width", "font-family", "font-size", "opacity"]) {
      expect(PAINT).toContain(name);
    }
  });
});

describe("a failed copy", () => {
  it("names a browser that cannot copy images", () => {
    const had = (globalThis as { ClipboardItem?: unknown }).ClipboardItem;
    delete (globalThis as { ClipboardItem?: unknown }).ClipboardItem;
    try {
      expect(copyProblem(new Error("nope"))).toBe("This browser cannot copy images. Download the chart instead.");
    } finally {
      if (had !== undefined) (globalThis as { ClipboardItem?: unknown }).ClipboardItem = had;
    }
  });

  it("says what went wrong otherwise", () => {
    (globalThis as { ClipboardItem?: unknown }).ClipboardItem = class {};
    try {
      expect(copyProblem(new Error("Document is not focused."))).toBe(
        "Couldn't copy the chart: Document is not focused.");
      expect(copyProblem("denied")).toBe("Couldn't copy the chart: denied");
    } finally {
      delete (globalThis as { ClipboardItem?: unknown }).ClipboardItem;
    }
  });
});
