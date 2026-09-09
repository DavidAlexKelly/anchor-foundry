import { describe as suite, expect, it } from "vitest";

import { describe, emptyReason, forRepository, unrepositoried } from "./pull-requests";
import type { CodeProposal } from "./types";

function proposal(over: Partial<CodeProposal>): CodeProposal {
  return {
    id: "p-1",
    project_id: "proj",
    source_repo_id: null,
    source_commit_id: null,
    summary: "A change",
    description: "",
    state: "open",
    change_set_id: null,
    created_by: null,
    created_by_email: null,
    created_at: "",
    files_updated_at: "",
    file_count: 0,
    ...over,
  };
}

const mine = proposal({ id: "a", source_repo_id: "r-1", source_commit_id: "c0ffee1234" });
const theirs = proposal({ id: "b", source_repo_id: "r-2", source_commit_id: "beefdead99" });
const typed = proposal({ id: "c", source_repo_id: null, file_count: 3 });

suite("which proposals are this repository's", () => {
  it("keeps only the ones publishing a commit from it", () => {
    // A proposal is project-level and a repository is one of several (db 0039),
    // so "this project's proposals" and "this repository's" are different
    // lists. A tab that showed the first would put another repository's review
    // in front of somebody looking at this one.
    expect(forRepository([mine, theirs, typed], "r-1").map((p) => p.id)).toEqual(["a"]);
    expect(forRepository([mine, theirs, typed], "r-2").map((p) => p.id)).toEqual(["b"]);
  });

  it("does not sweep up the ones that name no repository", () => {
    // The typed-changes shape belongs to *no* repository, so it cannot be
    // shown on any repository's tab honestly.
    expect(forRepository([typed], "r-1")).toEqual([]);
    expect(unrepositoried([mine, theirs, typed]).map((p) => p.id)).toEqual(["c"]);
  });
});

suite("what a row says a proposal would do", () => {
  it("names the commit for a publish, because that is the identifying thing", () => {
    // The same eight characters the History tab and the publish plan use, so
    // the three can be read against each other.
    expect(describe(mine)).toBe("publishes c0ffee12");
  });

  it("counts files for a typed change, and gets the singular right", () => {
    expect(describe(typed)).toBe("3 files");
    expect(describe(proposal({ file_count: 1 }))).toBe("1 file");
    expect(describe(proposal({ file_count: 0 }))).toBe("0 files");
  });
});

suite("what an empty tab says", () => {
  it("says nothing at all when there is something to show", () => {
    expect(emptyReason([mine], "r-1")).toBeNull();
  });

  it("is plain when the project has no open proposals either", () => {
    expect(emptyReason([], "r-1")).toBe("No open proposals for this repository.");
  });

  it("**says where the others are, rather than looking like nothing is happening**", () => {
    // The case that makes this function worth having: a reviewer sent a link,
    // finding an empty tab, needs to tell "already dealt with" from "not here".
    const reason = emptyReason([typed], "r-1");
    expect(reason).toContain("Code screen");
    expect(reason).toContain("1 in this project");
    expect(reason).toContain("changes a transform");
  });

  it("gets the plural right for several elsewhere", () => {
    const reason = emptyReason([typed, proposal({ id: "d" })], "r-1");
    expect(reason).toContain("2 in this project");
    expect(reason).toContain("change transforms");
    expect(reason).toContain("are");
  });

  it("does not claim the others are typed changes when they belong to another repository", () => {
    // Two different absences with two different remedies: one is reviewed on
    // another screen, the other on another repository's tab. Saying "Code
    // screen" for the second would send the reader somewhere it is not.
    const reason = emptyReason([theirs], "r-1");
    expect(reason).not.toContain("Code screen");
    expect(reason).toContain("belongs to something else");
  });
});
