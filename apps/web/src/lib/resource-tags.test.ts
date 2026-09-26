/** §511: tags, as the tags page and a resource's Details say them. */
import { describe, expect, it } from "vitest";

import { addable, byCategory, tagLabel, usesText } from "./resource-tags";

const tag = (id: string, category: string, name: string) =>
  ({ id, category, name, created_at: "2026-09-26T00:00:00Z" });

describe("tagLabel", () => {
  it("puts the category first, and leaves it out when there is none", () => {
    expect(tagLabel(tag("1", "Sensitivity", "PII"))).toBe("Sensitivity: PII");
    expect(tagLabel(tag("2", "", "Gold"))).toBe("Gold");
  });
});

describe("byCategory", () => {
  it("groups runs of one category, keeping the order given", () => {
    const tags = [tag("1", "", "a"), tag("2", "Q", "b"), tag("3", "Q", "c"), tag("4", "Z", "d")];
    expect(byCategory(tags).map((g) => [g.category, g.tags.map((t) => t.id)])).toEqual([
      ["", ["1"]], ["Q", ["2", "3"]], ["Z", ["4"]],
    ]);
    expect(byCategory([])).toEqual([]);
  });
});

describe("addable", () => {
  it("offers what the resource does not carry", () => {
    const all = [tag("1", "", "a"), tag("2", "", "b"), tag("3", "", "c")];
    expect(addable(all, [all[1]!]).map((t) => t.id)).toEqual(["1", "3"]);
    expect(addable(all, [])).toEqual(all);
  });
});

describe("usesText", () => {
  it("counts resources, and says so when there are none", () => {
    expect([0, 1, 2].map(usesText)).toEqual(["not used yet", "on 1 resource", "on 2 resources"]);
  });
});
