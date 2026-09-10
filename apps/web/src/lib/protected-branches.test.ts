import { describe, expect, it } from "vitest";

import {
  isProtected,
  protectedReason,
  suggestedSandboxName,
  type BranchContext,
} from "./protected-branches";

function ctx(over: Partial<BranchContext> = {}): BranchContext {
  return {
    branch: "main",
    defaultBranch: "main",
    reviewRequired: true,
    hasCommits: true,
    ...over,
  };
}

describe("which branch is protected", () => {
  it("**the default branch, and only while review is required**", () => {
    // Protection is the gate, not a second switch: with the gate off there is
    // nothing protecting anything, and the Settings tab's description would
    // stop matching what happens.
    expect(isProtected(ctx())).toBe(true);
    expect(isProtected(ctx({ reviewRequired: false }))).toBe(false);
  });

  it("never a sandbox, gated or not", () => {
    expect(isProtected(ctx({ branch: "work" }))).toBe(false);
    expect(isProtected(ctx({ branch: "work", reviewRequired: false }))).toBe(false);
  });

  it("**not a branch with nothing on it yet**", () => {
    // Putting a repository's first commit on its default branch is how a
    // repository starts. Refusing it would leave a new repository in a gated
    // project with no way in at all, which is a wall rather than a rule.
    expect(isProtected(ctx({ hasCommits: false }))).toBe(false);
  });

  it("follows the repository's own default rather than the name 'main'", () => {
    // A repository that named its own trunk does not get a second one.
    expect(isProtected(ctx({ branch: "trunk", defaultBranch: "trunk" }))).toBe(true);
    expect(isProtected(ctx({ branch: "main", defaultBranch: "trunk" }))).toBe(false);
  });
});

describe("what to say about it", () => {
  it("**names the route, not just the rule**", () => {
    // A refusal that only says no teaches people the product is broken.
    const reason = protectedReason(ctx({ branch: "trunk", defaultBranch: "trunk" }));
    expect(reason).toContain("trunk is protected");
    expect(reason).toContain("requires code review");
    expect(reason).toContain("sandbox branch");
    expect(reason).toContain("pull request");
  });

  it("**says applying the request moves the branch**", () => {
    // §283. Without that sentence, working on a sandbox reads as a detour that
    // leaves the work stranded somewhere nobody opens the repository on.
    expect(protectedReason(ctx())).toContain("moves main to your commit");
  });

  it("says nothing when there is nothing to say", () => {
    expect(protectedReason(ctx({ reviewRequired: false }))).toBeNull();
    expect(protectedReason(ctx({ branch: "work" }))).toBeNull();
    expect(protectedReason(ctx({ hasCommits: false }))).toBeNull();
  });
});

describe("the sandbox name offered", () => {
  it("**does not collide with a branch that already exists**", () => {
    // Offering a name the create endpoint refuses would turn a helpful default
    // into an error somebody has to read and undo.
    expect(suggestedSandboxName([])).toBe("sandbox-1");
    expect(suggestedSandboxName(["sandbox-1"])).toBe("sandbox-2");
    expect(suggestedSandboxName(["sandbox-1", "sandbox-2", "main"])).toBe("sandbox-3");
  });

  it("skips only the ones taken, rather than counting them", () => {
    // `sandbox-${existing.length + 1}` collides the moment somebody deletes
    // one, which is the obvious wrong implementation.
    expect(suggestedSandboxName(["main", "other"])).toBe("sandbox-1");
    expect(suggestedSandboxName(["sandbox-2"])).toBe("sandbox-1");
  });
});
