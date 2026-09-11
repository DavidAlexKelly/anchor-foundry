import { describe, expect, it } from "vitest";

import {
  checksAreAProblem,
  checksLabel,
  proposalStateLabel,
  proposeProblem,
  pullRequestSlot,
} from "./branch-columns";
import type { RepositoryBranchSummary } from "./types";

function branch(over: Partial<RepositoryBranchSummary> = {}): RepositoryBranchSummary {
  return {
    id: "b-1",
    name: "sandbox",
    head_commit_id: "3f2a1b9c",
    checks: "none",
    proposal_id: null,
    proposal_state: null,
    proposal_summary: null,
    ...over,
  };
}

describe("the Checks column", () => {
  it("**never shows a tick for a branch nothing has run against**", () => {
    // "Nothing failed" and "everything passed" are the same number, and this
    // is the column somebody glances at before merging. §295 refuses the same
    // lie about a test suite that ran nothing.
    expect(checksLabel(branch({ checks: "none" }))).toBe("not run");
    expect(checksAreAProblem(branch({ checks: "none" }))).toBe(false);
  });

  it("says passed and failed plainly", () => {
    expect(checksLabel(branch({ checks: "passed" }))).toBe("passed");
    expect(checksLabel(branch({ checks: "failed" }))).toBe("failed");
    expect(checksAreAProblem(branch({ checks: "failed" }))).toBe(true);
    expect(checksAreAProblem(branch({ checks: "passed" }))).toBe(false);
  });

  it("says nothing at all about a branch with no commits", () => {
    // There is no version for a check to have run against, and "not run" would
    // read as an omission rather than as the shape of the branch.
    expect(checksLabel(branch({ head_commit_id: null }))).toBe("—");
  });
});

describe("the Pull request column", () => {
  it("**offers the button or the state, never both** (p.16)", () => {
    // p.17 says the absence of the button *is* how you know a pull request
    // exists. A screen showing both would answer a question the reader did not
    // have to ask.
    expect(pullRequestSlot(branch()).kind).toBe("propose");
    const taken = pullRequestSlot(
      branch({ proposal_id: "p-1", proposal_state: "open", proposal_summary: "Publish it" }),
    );
    expect(taken).toEqual({ kind: "open", id: "p-1", state: "open", summary: "Publish it" });
  });

  it("offers neither on a branch with nothing committed", () => {
    // Offering the button would be offering a refusal (§214).
    expect(pullRequestSlot(branch({ head_commit_id: null }))).toEqual({
      kind: "none",
      reason: "nothing committed",
    });
  });
});

describe("the word on the button that opens one", () => {
  it("**translates our three states into p.17's three**", () => {
    // db 0039's are open/applied/withdrawn and p.17's are Open/Closed/Merged.
    // `applied` is Foundry's "Merged" in every way that matters to a reader,
    // and showing ours on a screen whose shape is borrowed from p.17 would
    // make the two harder to compare rather than easier.
    expect(proposalStateLabel("open")).toBe("Open");
    expect(proposalStateLabel("applied")).toBe("Merged");
    expect(proposalStateLabel("withdrawn")).toBe("Closed");
  });

  it("does not invent a fourth word for a state it does not know", () => {
    expect(proposalStateLabel("something-new")).toBe("Open");
  });
});

describe("whether a branch can be proposed from", () => {
  it("**names the default branch as the one case that cannot**", () => {
    // Applying lands the commit on the default branch (§283), so proposing it
    // into itself is a review of nothing - and the refusal is more useful
    // before the click than after it.
    const said = proposeProblem(branch({ name: "main" }), "main");
    expect(said).toContain("where applied changes land");
    // And it says what to do instead, because "no" without a next step is a
    // screen people work around rather than with.
    expect(said).toContain("sandbox branch");
  });

  it("names the empty branch too", () => {
    expect(proposeProblem(branch({ head_commit_id: null }), "main")).toContain(
      "Nothing has been committed",
    );
  });

  it("says nothing about a branch that can", () => {
    expect(proposeProblem(branch(), "main")).toBeNull();
  });
});
