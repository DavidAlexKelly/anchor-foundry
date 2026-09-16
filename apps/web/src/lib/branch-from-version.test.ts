/**
 * Branching from a historical transaction (§357; `dataset-preview` p.4).
 */
import { describe, expect, it } from "vitest";
import { branchName, whyNotBranchable } from "./branch-from-version";

describe("what a branch is called", () => {
  it("names the dataset and the version it came from", () => {
    expect(branchName("Orders", 3)).toBe("Orders v3");
  });

  it("gives two branches off different versions different names", () => {
    // **The reason the version is in there at all.** Branching twice off one
    // dataset at different points is the normal case, and two datasets called
    // "Orders (branch)" tell a reader nothing about which is which.
    expect(branchName("Orders", 3)).not.toBe(branchName("Orders", 4));
  });

  it("keeps the source's name recognisable", () => {
    // The negative control for the line above: a name that was only the
    // version would also differ between versions, and would be useless.
    expect(branchName("Orders", 3)).toContain("Orders");
  });
});

describe("which versions can be branched", () => {
  it("says nothing about a version whose data is there", () => {
    expect(whyNotBranchable({ size_bytes: 4096 })).toBe("");
  });

  it("refuses a version whose data is gone, and says why", () => {
    // `size_bytes` is a HEAD against the object store taken when the history
    // was listed, so null means the bytes are not where the row says they are.
    expect(whyNotBranchable({ size_bytes: null }))
      .toBe("this version's data is no longer in storage, so there is nothing to copy");
  });

  it("reads a version that was never measured as gone too", () => {
    // `size_bytes` is optional on `DatasetVersion`, so a response that omits
    // it is absent rather than measured — and the History tab's View button
    // has always used `== null`, which catches both. A strict `=== null` here
    // would offer a branch the server then refuses with a bare conflict.
    expect(whyNotBranchable({}))
      .toBe("this version's data is no longer in storage, so there is nothing to copy");
  });

  it("does not read an empty version as a missing one", () => {
    // **Zero bytes is a fact about the data; null is a fact about the
    // storage.** A version that measured zero has been measured, and refusing
    // it would block branching a dataset somebody emptied on purpose.
    expect(whyNotBranchable({ size_bytes: 0 })).toBe("");
  });
});
