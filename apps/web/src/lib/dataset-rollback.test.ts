/** Rolling a dataset back to an earlier version (§361; `data-lineage` p.73). */
import { describe, expect, it } from "vitest";
import { isRebuilt, rollbackSummary, whyNotRollbackable } from "./dataset-rollback";

describe("whether a version can be rolled back to", () => {
  it("allows an earlier version whose data is there", () => {
    expect(whyNotRollbackable({ version_number: 2, size_bytes: 400 }, 5)).toBe("");
  });

  it("refuses the version the dataset is already on", () => {
    // The server refuses it too, with a 409. Saying so on the button is the
    // difference between a control that is off and one that looks broken.
    expect(whyNotRollbackable({ version_number: 5, size_bytes: 400 }, 5)).toContain(
      "the version the dataset is on",
    );
  });

  it("refuses a version whose bytes are gone", () => {
    expect(whyNotRollbackable({ version_number: 2, size_bytes: null }, 5)).toContain(
      "no longer in storage",
    );
  });

  it("treats an absent size as gone rather than as measured", () => {
    // `size_bytes` is optional on the version, so a response that omits it
    // must not read as "0 bytes, fine" — and refusing is the safe direction,
    // since the server would refuse it anyway a moment later.
    expect(whyNotRollbackable({ version_number: 2 }, 5)).toContain("no longer in storage");
  });

  it("checks the current version before the bytes", () => {
    // Both are true of the current version of a dataset whose storage has
    // gone, and "this is the version you are on" is the one that tells
    // somebody what to press instead.
    expect(whyNotRollbackable({ version_number: 5, size_bytes: null }, 5)).toContain(
      "the version the dataset is on",
    );
  });
});

describe("what the confirmation says", () => {
  it("names the version it restores and the version it writes", () => {
    const lines = rollbackSummary(2, 7, "upload");
    expect(lines[0]).toContain("v2");
    expect(lines[0]).toContain("v8");
  });

  it("says the history is kept, which is what makes this reversible", () => {
    expect(rollbackSummary(2, 7, "upload")[1]).toContain("v7");
    expect(rollbackSummary(2, 7, "upload")[1]).toContain("Nothing is deleted");
  });

  it("never repeats Foundry's 'cannot easily be undone'", () => {
    // p.76's warning is not true here — nothing is deleted, so rolling back to
    // the version you were on puts it back. A caution that is not warranted is
    // the §214 failure pointed the other way.
    for (const origin of ["upload", "sync", "model_output", "fork"]) {
      expect(rollbackSummary(2, 7, origin).join(" ")).not.toMatch(/undone|undo/i);
    }
  });

  it("warns about the next build only where something builds it", () => {
    // p.74's sentence, shown where it can come true.
    expect(rollbackSummary(2, 7, "model_output").join(" ")).toContain("next build");
    expect(rollbackSummary(2, 7, "sync").join(" ")).toContain("next build");
    expect(rollbackSummary(2, 7, "upload").join(" ")).not.toContain("next build");
    expect(rollbackSummary(2, 7, "fork").join(" ")).not.toContain("next build");
  });
});

describe("what rebuilds itself", () => {
  it("is a model output or a sync, and not an upload or a fork", () => {
    expect(isRebuilt("model_output")).toBe(true);
    expect(isRebuilt("sync")).toBe(true);
    expect(isRebuilt("upload")).toBe(false);
    expect(isRebuilt("fork")).toBe(false);
  });

  it("does not treat an origin it has never heard of as rebuilt", () => {
    // A new origin arrives as a *quiet* wrong warning otherwise, and the safe
    // default is the one that says less rather than the one that says
    // something untrue about a build that may not exist.
    expect(isRebuilt("something_new")).toBe(false);
  });
});
