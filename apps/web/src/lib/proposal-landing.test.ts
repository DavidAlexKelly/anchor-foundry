import { describe, expect, it } from "vitest";

import { divergenceRemedy, landingIsAProblem, landingNote } from "./proposal-landing";
import type { CodeProposalDetail } from "./types";

function proposal(over: Partial<CodeProposalDetail>): CodeProposalDetail {
  return {
    lands_on: "main",
    landing: "fast_forward",
    blockers: [],
    ...over,
  } as CodeProposalDetail;
}

describe("what the branch line says", () => {
  it("**names the branch and what happens to it**", () => {
    const note = landingNote(proposal({ lands_on: "trunk", landing: "fast_forward" }));
    expect(note).toContain("trunk");
    expect(note).toContain("moves");
  });

  it("**says so when nothing will move**", () => {
    // "nothing will happen to the branch" and "the branch will be updated"
    // look identical on a screen that mentions neither, and the second is the
    // one people assume.
    const note = landingNote(proposal({ landing: "landed" }));
    expect(note).toContain("already has this commit");
    expect(note).toContain("main");
  });

  it("says the branch moved on when it has", () => {
    expect(landingNote(proposal({ landing: "diverged" }))).toContain("has moved on");
  });

  it("**stays silent for a proposal that lands on no branch**", () => {
    // A typed-changes proposal names no repository (db 0039), so a line
    // reading "lands on main" would describe something that cannot happen.
    expect(landingNote(proposal({ lands_on: null, landing: null }))).toBeNull();
    // Half an answer is still no answer.
    expect(landingNote(proposal({ lands_on: "main", landing: null }))).toBeNull();
    expect(landingNote(proposal({ lands_on: null, landing: "fast_forward" }))).toBeNull();
  });
});

describe("which of them is a warning", () => {
  it("**only the divergence**", () => {
    // The other two are the system working, and styling them as problems would
    // train people past the one that is.
    expect(landingIsAProblem(proposal({ landing: "diverged" }))).toBe(true);
    expect(landingIsAProblem(proposal({ landing: "fast_forward" }))).toBe(false);
    expect(landingIsAProblem(proposal({ landing: "landed" }))).toBe(false);
    expect(landingIsAProblem(proposal({ lands_on: null, landing: null }))).toBe(false);
  });
});

describe("the remedy", () => {
  it("**is an instruction, because retrying cannot work**", () => {
    // Landing is fast-forward only: there is no merge commit, so a divergence
    // cannot be resolved by moving a pointer.
    const remedy = divergenceRemedy(proposal({ lands_on: "trunk", landing: "diverged" }));
    expect(remedy).toContain("Merge trunk into the branch this was made on");
    expect(remedy).toContain("cannot be resolved by retrying");
  });

  it("offers nothing when there is nothing wrong", () => {
    expect(divergenceRemedy(proposal({ landing: "fast_forward" }))).toBeNull();
    expect(divergenceRemedy(proposal({ landing: "landed" }))).toBeNull();
    expect(divergenceRemedy(proposal({ lands_on: null, landing: null }))).toBeNull();
  });
});
