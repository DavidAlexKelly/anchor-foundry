import { describe, expect, it } from "vitest";

import { arrayEntries, pageOf } from "./loop-array";

/** p.133's loop over an array (Foundry `workshop` p.133–134). */

describe("arrayEntries", () => {
  it("takes an array as it is", () => {
    expect(arrayEntries(["a", "b"])).toEqual(["a", "b"]);
  });

  it("keeps duplicates and falsy entries", () => {
    // **Both are the reason position is the key.** A loop over
    // ["", 0, "", null] renders four copies, not one.
    expect(arrayEntries(["a", "a"])).toEqual(["a", "a"]);
    expect(arrayEntries(["", 0, null, false])).toHaveLength(4);
  });

  it("is empty for anything that is not an array", () => {
    // A variable the server has not resolved yet, one genuinely null, and a
    // document holding the wrong thing all mean "no copies" - and none of the
    // three may throw inside a render.
    expect(arrayEntries(undefined)).toEqual([]);
    expect(arrayEntries(null)).toEqual([]);
    expect(arrayEntries("abc")).toEqual([]);
    expect(arrayEntries({ 0: "a", length: 1 })).toEqual([]);
  });
});

describe("pageOf — limit (p.134)", () => {
  const five = ["a", "b", "c", "d", "e"];

  it("shows at most maxItems, and only ever one page", () => {
    // p.134: "display only a single page which displays up to the first X…"
    const out = pageOf(five, { paging: "limit", maxItems: 3, pageSize: 2 });
    expect(out.rows.map((r) => r.value)).toEqual(["a", "b", "c"]);
    expect(out.pageCount).toBe(1);
  });

  it("is not `paged` with one page", () => {
    // The entries past the cap are not on a later page; they are not shown.
    // Conflating the two would give a Limit loop pagination controls for
    // entries it is documented not to display.
    expect(pageOf(five, { paging: "limit", maxItems: 2, pageSize: 2 }).pageCount).toBe(1);
  });

  it("shows everything when the cap is larger than the array", () => {
    expect(pageOf(five, { paging: "limit", maxItems: 99, pageSize: 2 }).rows).toHaveLength(5);
  });

  it("never shows zero copies for a nonsensical cap", () => {
    // A cap of 0 or -1 is a misconfiguration, and a loop that renders nothing
    // looks identical to a loop over an empty array - the one failure an
    // author cannot diagnose from the screen.
    expect(pageOf(five, { paging: "limit", maxItems: 0, pageSize: 2 }).rows).toHaveLength(1);
    expect(pageOf(five, { paging: "limit", maxItems: -3, pageSize: 2 }).rows).toHaveLength(1);
  });
});

describe("pageOf — paged (p.134)", () => {
  const five = ["a", "b", "c", "d", "e"];

  it("walks pages of pageSize", () => {
    const opts = { paging: "paged", maxItems: 99, pageSize: 2 } as const;
    expect(pageOf(five, { ...opts, page: 0 }).rows.map((r) => r.value)).toEqual(["a", "b"]);
    expect(pageOf(five, { ...opts, page: 1 }).rows.map((r) => r.value)).toEqual(["c", "d"]);
    expect(pageOf(five, { ...opts, page: 2 }).rows.map((r) => r.value)).toEqual(["e"]);
  });

  it("counts the pages", () => {
    expect(pageOf(five, { paging: "paged", maxItems: 99, pageSize: 2 }).pageCount).toBe(3);
    expect(pageOf(five, { paging: "paged", maxItems: 99, pageSize: 5 }).pageCount).toBe(1);
  });

  it("reports one page for an empty array rather than zero", () => {
    // So a control never reads "page 1 of 0".
    expect(pageOf([], { paging: "paged", maxItems: 99, pageSize: 2 }).pageCount).toBe(1);
  });

  it("clamps a page past the end", () => {
    // **An author can shrink the array under a reader who is on the last
    // page.** An out-of-range slice shows nothing, with no way back.
    const out = pageOf(five, { paging: "paged", maxItems: 99, pageSize: 2, page: 99 });
    expect(out.rows.map((r) => r.value)).toEqual(["e"]);
  });

  it("clamps a negative page", () => {
    const out = pageOf(five, { paging: "paged", maxItems: 99, pageSize: 2, page: -5 });
    expect(out.rows.map((r) => r.value)).toEqual(["a", "b"]);
  });
});

describe("the index travels with the entry", () => {
  it("is the position in the whole array, not in the page", () => {
    // **The key has to be stable across paging.** An index into a slice
    // repeats 0,1 on every page, so React would reuse page one's copies for
    // page two and carry their layout state across.
    const out = pageOf(["a", "b", "c", "d"], {
      paging: "paged", maxItems: 99, pageSize: 2, page: 1,
    });
    expect(out.rows).toEqual([{ index: 2, value: "c" }, { index: 3, value: "d" }]);
  });

  it("distinguishes repeated values", () => {
    // p.133 orders copies by position, and an array may hold the same entry
    // twice. Keying by value would collapse these two into one.
    const out = pageOf(["x", "x"], { paging: "limit", maxItems: 9, pageSize: 9 });
    expect(out.rows.map((r) => r.index)).toEqual([0, 1]);
  });
});
