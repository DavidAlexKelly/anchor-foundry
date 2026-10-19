import { describe, expect, it } from "vitest";
import { pageTitle } from "./page-title";

describe("a page's title", () => {
  it("is the page, then where it is, then the product", () => {
    expect(pageTitle("Datasets", "Operations")).toBe("Datasets · Operations · Anchor");
  });

  it("leaves out a part still loading, rather than a blank between dots", () => {
    expect(pageTitle("Datasets", undefined)).toBe("Datasets · Anchor");
    expect(pageTitle(null, "  ")).toBe("Anchor");
  });

  it("trims what it is given", () => {
    expect(pageTitle(" Pipeline ", "Ops\n")).toBe("Pipeline · Ops · Anchor");
  });
});
