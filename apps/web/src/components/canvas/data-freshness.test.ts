import { describe, expect, it } from "vitest";

import { freshnessLabel, isStale, itemsOf, newItemId } from "./data-freshness";

const now = Date.parse("2025-07-18T12:00:00Z");
const ago = (ms: number) => new Date(now - ms).toISOString();

describe("freshnessLabel (p.400)", () => {
  it("is relative within a day", () => {
    expect(freshnessLabel(ago(30 * 60_000), now)).toBe("30 min ago");
    expect(freshnessLabel(ago(59 * 60_000 + 59_000), now)).toBe("59 min ago");
    expect(freshnessLabel(ago(60 * 60_000), now)).toBe("1 hour ago");
    expect(freshnessLabel(ago(2 * 3_600_000 + 5 * 60_000), now)).toBe("2 hours ago");
    expect(freshnessLabel(ago(24 * 3_600_000 - 1), now)).toBe("23 hours ago");
    expect(freshnessLabel(ago(10_000), now)).toBe("just now");
    expect(freshnessLabel(ago(60_000), now)).toBe("1 min ago");
  });

  it("is absolute from 24 hours, in p.400's shape", () => {
    // TZ is pinned to New York for the test runner: 17:52 UTC is 1:52 PM.
    expect(freshnessLabel("2025-07-16T17:52:00Z", now)).toBe("Wed, Jul 16, 2025, 1:52 PM");
    expect(freshnessLabel(ago(24 * 3_600_000), now)).toBe("Thu, Jul 17, 2025, 8:00 AM");
  });

  it("says never rather than dating nothing, and does not report the future", () => {
    expect(freshnessLabel(null, now)).toBe("Never indexed");
    expect(freshnessLabel("junk", now)).toBe("Never indexed");
    expect(freshnessLabel(new Date(now + 90_000).toISOString(), now)).toBe("just now");
  });

  it("is stale from p.400's 24 hours", () => {
    expect(isStale(ago(24 * 3_600_000), now)).toBe(true);
    expect(isStale(ago(24 * 3_600_000 - 1), now)).toBe(false);
    expect(isStale(null, now)).toBe(true);
    expect(isStale("junk", now)).toBe(true);
  });
});

describe("itemsOf and newItemId (p.401)", () => {
  it("keeps items with an id and a type, and sources with a dataset", () => {
    expect(itemsOf([
      { id: "d_1", objectTypeId: "t1", sources: [
        { datasetId: "ds1", name: "Orders feed" }, { datasetId: "ds2", name: "  " },
        { name: "no id" }, null] },
      { id: "d_2", objectTypeId: "t2" },
      { id: "", objectTypeId: "t3" }, { id: "d_4" }, "junk",
    ])).toEqual([
      { id: "d_1", objectTypeId: "t1", sources: [
        { datasetId: "ds1", name: "Orders feed" }, { datasetId: "ds2" }] },
      { id: "d_2", objectTypeId: "t2", sources: [] },
    ]);
    expect(itemsOf("nope")).toEqual([]);
  });

  it("gives a new item the first d_N not taken", () => {
    expect(newItemId([])).toBe("d_1");
    expect(newItemId([{ id: "d_2", objectTypeId: "t", sources: [] }])).toBe("d_3");
  });
});
