import { describe, expect, it } from "vitest";

import {
  VERSION_PARAM,
  aheadNote,
  aheadOfPublished,
  versionFrom,
  versionNote,
} from "./app-version";

describe("which version a link asks for", () => {
  it("defaults to the published one", () => {
    expect(versionFrom(null)).toBe("latest");
    expect(versionFrom("")).toBe("latest");
    expect(versionFrom("latest")).toBe("latest");
  });

  it("reads p.166's other one", () => {
    expect(versionFrom("saved")).toBe("saved");
  });

  it("treats anything unrecognised as the published one", () => {
    // The failure mode of guessing the other way is showing unpublished work
    // to somebody who typed a character wrong.
    expect(versionFrom("dev")).toBe("latest");
    expect(versionFrom("Saved")).toBe("latest");
    expect(versionFrom("saved ")).toBe("latest");
  });

  it("names the parameter once", () => {
    expect(VERSION_PARAM).toBe("version");
  });
});

describe("what the banner says", () => {
  it("says nothing on a published module", () => {
    // A banner on every published module is one nobody reads.
    expect(versionNote("latest")).toBeNull();
  });

  it("says what other people see, not just what this is", () => {
    const said = versionNote("saved");
    expect(said).toContain("last saved version");
    expect(said).toContain("Other people see");
  });
});

describe("how far ahead of the published version this is", () => {
  it("says nothing on a published module", () => {
    expect(aheadOfPublished("latest", 5, 2)).toBeNull();
  });

  it("counts the saves since publishing", () => {
    expect(aheadOfPublished("saved", 5, 2)).toBe(3);
    expect(aheadOfPublished("saved", 3, 2)).toBe(1);
  });

  it("says nothing when there is nothing to be ahead of", () => {
    // An app that has never been published has no version to differ from, and
    // "1 change ahead" of nothing is arithmetic rather than information.
    expect(aheadOfPublished("saved", 4, null)).toBeNull();
  });

  it("says nothing when the two are level", () => {
    expect(aheadOfPublished("saved", 2, 2)).toBeNull();
  });

  it("never reports a negative, which would mean the pointer moved past", () => {
    expect(aheadOfPublished("saved", 1, 3)).toBeNull();
  });

  it("counts one save in the singular", () => {
    expect(aheadNote(1)).toBe("1 save ahead of what is published.");
    expect(aheadNote(4)).toBe("4 saves ahead of what is published.");
    expect(aheadNote(null)).toBeNull();
  });
});
