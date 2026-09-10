import { describe, expect, it } from "vitest";

import {
  canCreate,
  deleteQuestion,
  emptyReason,
  nameProblem,
  pointsAt,
  subtitle,
  willPin,
} from "./tags";
import type { RepositoryTag } from "./types";

function tag(over: Partial<RepositoryTag> = {}): RepositoryTag {
  return {
    id: "t-1",
    repo_id: "r-1",
    name: "1.4.0",
    commit_id: "3f2a1b9c7d5e4f00",
    message: null,
    created_at: "",
    created_by: null,
    created_by_email: null,
    commit_message: null,
    ...over,
  };
}

describe("what a row points at", () => {
  it("**names the commit in the same eight characters everything else uses**", () => {
    // The History tab, the publish plan and the Pull requests tab all use
    // eight, so the four can be read against each other - and a tag's whole
    // purpose is to be resolved back to a commit.
    expect(pointsAt(tag())).toBe("3f2a1b9c");
  });
});

describe("the line under the name", () => {
  it("**prefers the tag's own message to the commit's**", () => {
    // Somebody who wrote down why this version mattered has said something the
    // commit message does not.
    expect(subtitle(tag({ message: "shipped to acme", commit_message: "fix join" })))
      .toBe("3f2a1b9c · shipped to acme");
  });

  it("falls back to the commit's message, so a row is not just a hash", () => {
    // "1.4.0 · 3f2a1b9c" makes you open it to find out what it was.
    expect(subtitle(tag({ commit_message: "fix join" }))).toBe("3f2a1b9c · fix join");
  });

  it("invents nothing when neither says anything", () => {
    expect(subtitle(tag())).toBe("3f2a1b9c");
  });

  it("does not treat whitespace as a message", () => {
    expect(subtitle(tag({ message: "   ", commit_message: "  " }))).toBe("3f2a1b9c");
  });
});

describe("what the browser refuses before a round trip", () => {
  it("**is the column's floor and not the repository's convention**", () => {
    // repoSettings.json's regex is read from the commit being tagged and the
    // browser does not have it. A second copy here would disagree with the file
    // the first time somebody edited it.
    expect(nameProblem("1.4.0")).toBeNull();
    expect(nameProblem("release-candidate-2")).toBeNull();
    expect(nameProblem("v1.4.0+build.7")).toBeNull();
  });

  it("refuses a shape the column itself cannot hold", () => {
    expect(nameProblem("-leading-dash")).toContain("starts with a letter or digit");
    expect(nameProblem("has a space")).toContain("starts with a letter or digit");
    expect(nameProblem("a/b")).toContain("starts with a letter or digit");
    expect(nameProblem("x".repeat(101))).toContain("100 characters");
  });

  it("**says nothing about an empty box**", () => {
    // A form that turns red because you have not typed anything yet is a form
    // that shouts before you have done anything wrong.
    expect(nameProblem("")).toBeNull();
    expect(nameProblem("   ")).toBeNull();
  });

  it("will not submit an empty one either", () => {
    expect(canCreate("")).toBe(false);
    expect(canCreate("   ")).toBe(false);
    expect(canCreate("1.4.0")).toBe(true);
    expect(canCreate("-nope")).toBe(false);
  });
});

describe("the empty list", () => {
  it("says nothing when there is something to show", () => {
    expect(emptyReason(2, true)).toBeNull();
  });

  it("**tells the two absences apart**", () => {
    // A repository with no commits has no version to mark, and the server would
    // refuse anyway - saying it first is the difference between a form that
    // explains and one that argues.
    expect(emptyReason(0, false)).toContain("no version to tag");
    expect(emptyReason(0, true)).toContain("never moves");
  });

  it("says what a tag is for, because somebody who has none may not know", () => {
    expect(emptyReason(0, true)).toContain("marks a version");
  });
});

describe("deleting one", () => {
  it("**says what is not at risk**", () => {
    // p.17 warns about deleting branches because that can lose work. A tag
    // cannot: the commit is held by ON DELETE RESTRICT. A confirmation that did
    // not say so would borrow the branch warning's weight for a smaller act.
    const asked = deleteQuestion(tag());
    expect(asked).toContain("1.4.0");
    expect(asked).toContain("3f2a1b9c");
    expect(asked).toContain("stays exactly where it is");
  });
});

describe("what a new tag would pin", () => {
  it("**says which commit before it is made, because it can never be moved**", () => {
    // A dialog that did not say would be asking somebody to make a permanent
    // decision blind.
    expect(willPin("main", "3f2a1b9c7d5e")).toBe("Pins 3f2a1b9c.");
    expect(willPin("main", undefined)).toBe("Pins the current version of main.");
  });
});
