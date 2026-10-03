/** Transaction types and views (§747; `data-integration` p.22-26). */
import { describe, expect, it } from "vitest";
import { TRANSACTION_MEANING, currentViewText, viewOf, viewStarts } from "./dataset-transactions";

const v = (version_number: number, transaction_type: "SNAPSHOT" | "APPEND" | "UPDATE") =>
  ({ version_number, transaction_type });

describe("where views begin", () => {
  it("begins one at every SNAPSHOT", () => {
    // p.24's example history, as versions: a SNAPSHOT, an APPEND, an UPDATE,
    // then a new SNAPSHOT that starts a second view.
    const history = [v(4, "SNAPSHOT"), v(3, "UPDATE"), v(2, "APPEND"), v(1, "SNAPSHOT")];
    expect(viewStarts(history)).toEqual([1, 4]);
    expect(viewOf(history, 3)).toBe(1);
    expect(viewOf(history, 4)).toBe(4);
  });

  it("takes the earliest version when there is no SNAPSHOT", () => {
    // A listener's archive only ever appends.
    const history = [v(3, "APPEND"), v(2, "APPEND"), v(1, "APPEND")];
    expect(viewStarts(history)).toEqual([1]);
    expect(viewOf(history, 3)).toBe(1);
  });

  it("does not count the earliest twice when it is a SNAPSHOT", () => {
    expect(viewStarts([v(1, "SNAPSHOT"), v(2, "SNAPSHOT")])).toEqual([1, 2]);
  });

  it("has no view before the first version", () => {
    expect(viewOf([v(2, "SNAPSHOT"), v(3, "APPEND")], 1)).toBeNull();
    expect(viewOf([], 1)).toBeNull();
  });
});

describe("the current view, said", () => {
  it("names how many views there are and where the current one runs", () => {
    expect(currentViewText([v(1, "SNAPSHOT"), v(2, "APPEND"), v(3, "SNAPSHOT"), v(4, "UPDATE")]))
      .toBe("This dataset has 2 views. The current one runs from v3 to v4.");
    expect(currentViewText([v(1, "SNAPSHOT")])).toBe("This dataset has one view. The current one is v1 alone.");
    expect(currentViewText([v(2, "APPEND"), v(1, "SNAPSHOT"), v(3, "SNAPSHOT")]))
      .toBe("This dataset has 2 views. The current one is v3 alone.");
  });

  it("says nothing of a dataset with no versions", () => {
    expect(currentViewText([])).toBe("");
  });
});

describe("what each type means", () => {
  it("has a sentence for every type a version can be", () => {
    expect(Object.keys(TRANSACTION_MEANING).sort()).toEqual(["APPEND", "SNAPSHOT", "UPDATE"]);
  });
});
