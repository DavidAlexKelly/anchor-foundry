/** Transaction types and views (§747; `data-integration` p.22-26). Where
 *  views begin is the server's to work out since §879, over the whole history
 *  rather than the page on screen: `apps/api/tests/test_version_paging.py`. */
import { describe, expect, it } from "vitest";
import { TRANSACTION_MEANING, currentViewText, olderPage } from "./dataset-transactions";

describe("the current view, said", () => {
  it("names how many views there are and where the current one runs", () => {
    expect(currentViewText({ views: 2, view_start: 3, newest: 4 }))
      .toBe("This dataset has 2 views. The current one runs from v3 to v4.");
    expect(currentViewText({ views: 1, view_start: 1, newest: 1 }))
      .toBe("This dataset has one view. The current one is v1 alone.");
    expect(currentViewText({ views: 2, view_start: 3, newest: 3 }))
      .toBe("This dataset has 2 views. The current one is v3 alone.");
  });

  it("says nothing of a dataset with no versions", () => {
    expect(currentViewText({ views: 0, view_start: null, newest: null })).toBe("");
  });
});

describe("the next page of the history", () => {
  it("starts under the oldest version shown", () => {
    expect(olderPage({ items: [{ version_number: 90 }, { version_number: 41 }] })).toBe(41);
  });

  it("is not there once the first version is shown, or the page is empty", () => {
    expect(olderPage({ items: [{ version_number: 3 }, { version_number: 1 }] })).toBeUndefined();
    expect(olderPage({ items: [] })).toBeUndefined();
  });
});

describe("what each type means", () => {
  it("has a sentence for every type a version can be", () => {
    expect(Object.keys(TRANSACTION_MEANING).sort()).toEqual(["APPEND", "SNAPSHOT", "UPDATE"]);
  });
});
