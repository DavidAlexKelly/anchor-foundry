import { describe, expect, it } from "vitest";
import { VERSION_PAGE, nextBefore, pageQuery } from "./version-pages";

const page = (from: number, count: number) =>
  Array.from({ length: count }, (_, i) => ({ version_number: from - i }));

describe("version pages", () => {
  it("asks for the first page with no query", () => {
    expect(pageQuery()).toBe("");
    expect(pageQuery(17)).toBe("?before=17");
  });

  it("continues below the oldest version of a full page", () => {
    expect(nextBefore(page(120, VERSION_PAGE))).toBe(120 - VERSION_PAGE + 1);
  });

  it("stops after a short page, and after an empty one", () => {
    expect(nextBefore(page(20, 20))).toBeUndefined();
    expect(nextBefore([])).toBeUndefined();
  });
});
