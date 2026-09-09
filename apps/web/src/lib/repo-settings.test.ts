import { describe, expect, it } from "vitest";

import {
  canChangeReviewPolicy,
  reviewPolicyEffect,
  reviewPolicyLockedReason,
  reviewPolicyScopeNote,
} from "./repo-settings";

describe("who may change the review gate", () => {
  it("is the owner, matching the endpoint", () => {
    // The browser's copy of a server rule is a display decision, not a
    // security one: `PUT /code/review-policy` requires owner whatever this
    // returns. What it buys is not offering a switch that answers 403.
    expect(canChangeReviewPolicy("owner")).toBe(true);
    expect(canChangeReviewPolicy("editor")).toBe(false);
    expect(canChangeReviewPolicy("viewer")).toBe(false);
  });

  it("names the role in the refusal, so the reader knows who to ask", () => {
    expect(reviewPolicyLockedReason("owner")).toBeNull();
    expect(reviewPolicyLockedReason("editor")).toContain("owner");
  });
});

describe("the scope note", () => {
  it("**says the setting is the project's, which is the divergence**", () => {
    // Foundry sets required review per repository (repoSettings.json, p.20).
    // Ours is per project, because the gate has to cover transforms that are
    // in no repository. A tab that let somebody discover that by flipping it
    // would be worse than one that says so.
    expect(reviewPolicyScopeNote(1)).toContain("whole project");
    expect(reviewPolicyScopeNote(1)).toContain("Foundry sets this per repository");
  });

  it("counts the repositories when there is more than one to be surprised by", () => {
    const note = reviewPolicyScopeNote(3);
    expect(note).toContain("all 3 repositories");
    // The single-repository case must not say "all 1 repositories", and more
    // importantly must still say the setting reaches beyond this screen —
    // a project with one repository today can have two tomorrow.
    expect(reviewPolicyScopeNote(1)).not.toContain("all 1");
    expect(reviewPolicyScopeNote(1)).toContain("not in a repository");
  });
});

describe("what the gate does", () => {
  it("says it in terms of what happens to a change, not in terms of a flag", () => {
    expect(reviewPolicyEffect(true)).toContain("cannot be changed directly");
    expect(reviewPolicyEffect(true)).toContain("other than their author");
    expect(reviewPolicyEffect(false)).toContain("changed directly");
    // And that proposals still work when the gate is off — otherwise turning
    // it off reads as turning review off, which it is not.
    expect(reviewPolicyEffect(false)).toContain("optional");
  });
});
