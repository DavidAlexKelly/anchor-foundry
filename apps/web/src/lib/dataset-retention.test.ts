import { describe, expect, it } from "vitest";
import { whyNotBranchable } from "./branch-from-version";
import { whyNotRollbackable } from "./dataset-rollback";
import {
  parseKeep,
  previewText,
  retentionText,
  tonightText,
  versionsText,
  whyExpired,
} from "./dataset-retention";
import type { DatasetRetention } from "./types";

const base: DatasetRetention = {
  versions: 10, total_bytes: 2048, unmeasured: 0, current_version: 10,
  keep_versions: null, expired: 0, would_expire: [], would_free_bytes: 0,
};

describe("versionsText (§966)", () => {
  it("joins runs into ranges and keeps the rest", () => {
    expect(versionsText([1, 2, 3, 4, 7, 9, 10])).toBe("v1–v4, v7, v9, v10");
    expect(versionsText([5])).toBe("v5");
    expect(versionsText([3, 1, 2, 2])).toBe("v1–v3");
    expect(versionsText([])).toBe("");
  });
});

describe("retentionText", () => {
  it("says every version is kept when there is no policy", () => {
    expect(retentionText(base)).toContain("Every version is kept");
    expect(retentionText(base)).toContain("Keeping 10 versions");
  });

  it("says the policy, what has gone, and counts only what is held", () => {
    const text = retentionText({ ...base, keep_versions: 3, expired: 4 });
    expect(text).toContain("The newest 3 versions are kept");
    expect(text).toContain("never the current version");
    expect(text).toContain("4 versions' data has been removed");
    expect(text).toContain("Keeping 6 versions");
  });

  it("says a version missing from storage is not counted", () => {
    expect(retentionText({ ...base, unmeasured: 1 })).toContain("1 version is no longer in storage");
  });
});

describe("tonightText and previewText", () => {
  it("say what goes, and when, before and after saving", () => {
    const going = { ...base, keep_versions: 2, would_expire: [1, 2, 3], would_free_bytes: 1024 };
    expect(tonightText(going)).toBe("Tonight v1–v3 (1.0 KB) will be removed.");
    expect(tonightText({ ...going, keep_versions: null })).toBe("");
    expect(tonightText({ ...going, would_expire: [] })).toBe("");
    expect(previewText(going, 2)).toBe("Keeping the newest 2 versions would remove v1–v3 (1.0 KB), tonight.");
    expect(previewText(base, 1)).toBe("Keeping the newest 1 version would remove nothing now.");
  });
});

describe("parseKeep", () => {
  it("takes a whole number of versions, and nothing else", () => {
    expect(parseKeep(" 5 ")).toBe(5);
    expect(parseKeep("0")).toBeNull();
    expect(parseKeep("2.5")).toBeNull();
    expect(parseKeep("-1")).toBeNull();
    expect(parseKeep("")).toBeNull();
    expect(parseKeep("1000001")).toBeNull();
  });
});

describe("an expired version", () => {
  const expired = { version_number: 2, size_bytes: null, expired_at: "2026-10-16T03:35:00Z" };
  it("is refused in words, not as a file gone missing", () => {
    const said = "this version's data was removed by the retention policy";
    expect(whyExpired(expired)).toBe(said);
    expect(whyNotBranchable(expired)).toBe(said);
    expect(whyNotRollbackable(expired, 5)).toBe(said);
    expect(whyExpired({ expired_at: null })).toBe("");
  });
});
