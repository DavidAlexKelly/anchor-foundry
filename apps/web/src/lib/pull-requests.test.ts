import { describe as suite, expect, it } from "vitest";

import { describe, emptyReason, forRepository, unrepositoried, unrepositoriedNote } from "./pull-requests";
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
    // **The Models screen, not the Code screen** (§290). It said "Code screen"
    // until the typed-changes proposals got a home beside the transforms they
    // change - and a sentence pointing at a page B.1 deletes would have become
    // a lie the moment it went, with nothing to notice.
    expect(reason).toContain("Models screen");
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

// `suite`, not `describe`: this module *exports* a `describe`, which is why
// the vitest one is aliased at the top of the file.
suite("proposals that name no repository (§290)", () => {
  // There was a test here for `unrepositoriedNote(0)` — a sentence saying no
  // such proposals are open and that the answer is to move a transform into a
  // repository. It is gone with the branch it checked: the section that renders
  // this note is silent when the list is empty, because a permanent empty
  // section for a shape nothing creates teaches people to look past that part
  // of the screen. So the zero sentence was a string no reader could ever be
  // shown, and a test asserting its wording was a check that could not fail in
  // any way a person would notice (§213).

  it("counts them and says why they exist", () => {
    // They were opened before the project used repositories. Without that,
    // a list of two reads as a feature somebody should be using.
    expect(unrepositoriedNote(1)).toContain("1 open proposal ");
    expect(unrepositoriedNote(1)).toContain("It was");
    expect(unrepositoriedNote(3)).toContain("3 open proposals");
    expect(unrepositoriedNote(3)).toContain("They were");
  });

  it("**says what to do instead**, which is the half a reader needs", () => {
    // A survivor found this: the clause could be deleted and every check
    // above still passed. "They were opened before this project used
    // repositories" says why these exist and leaves the obvious next question
    // - how do I open one now? - unanswered, on a screen whose whole point is
    // that the old answer is gone (§277, §289).
    expect(unrepositoriedNote(2)).toContain("new changes go through one");
  });
});
