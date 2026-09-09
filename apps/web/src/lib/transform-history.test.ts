import { describe, expect, it } from "vitest";

import { attribution, emptyNote, isChangeSet, scopeLabel } from "./transform-history";
import type { CodeHistoryEntry } from "./types";

function entry(over: Partial<CodeHistoryEntry>): CodeHistoryEntry {
  return {
    kind: "version",
    id: "e-1",
    summary: "Saved daily_orders",
    description: "",
    created_at: "2026-01-02T00:00:00Z",
    created_by_email: "someone@example.com",
    model_count: 1,
    ...over,
  };
}

describe("what a row says about size", () => {
  it("**calls a one-model change set a change set**", () => {
    // The distinction it carries is "somebody meant these together", not
    // "there were several". Collapsing it would hide the message its author
    // wrote.
    const one = entry({ kind: "change_set", model_count: 1 });
    expect(isChangeSet(one)).toBe(true);
    expect(scopeLabel(one)).toBe("1 transform");
    expect(scopeLabel(entry({ kind: "change_set", model_count: 3 }))).toBe("3 transforms");
  });

  it("names the version for an ungrouped save", () => {
    expect(scopeLabel(entry({ version_number: 4 }))).toBe("v4");
    expect(scopeLabel(entry({ version_number: null }))).toBe("one version");
  });
});

describe("attribution", () => {
  it("says the platform rather than unknown when there is no author", () => {
    // `created_by` is nullable because a version can be written by the
    // platform rather than a person — a publish from a schedule, most
    // obviously. "unknown" would be wrong about that.
    expect(attribution(entry({ created_by_email: null }))).toBe("the platform");
    expect(attribution(entry({}))).toBe("someone@example.com");
  });
});

describe("an empty history", () => {
  it("tells the two empties apart", () => {
    // A project whose transforms have never been saved has no history; so
    // does a project with no transforms. Only the second is a reason to go
    // somewhere else.
    expect(emptyNote(0)).toContain("No transforms in this project");
    expect(emptyNote(3)).toContain("Editing a transform writes a version here");
  });
});
