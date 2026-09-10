import { describe, expect, it } from "vitest";

import {
  checkTarget,
  emptyReason,
  severity,
  tally,
  verdict,
  verdictNote,
  worstFirst,
} from "./branch-checks";
import type { RepositoryCheck } from "./types";

function check(over: Partial<RepositoryCheck>): RepositoryCheck {
  return {
    id: "c-1",
    name: "transform_runs",
    status: "pass",
    summary: "ran",
    model_id: null,
    source_path: "src/t.sql",
    ran_at: "2026-01-02T00:00:00Z",
    ran_by_email: "someone@example.com",
    proposal_id: "p-1",
    proposal_summary: "Add a transform",
    proposal_state: "open",
    source_commit_id: "commit-1",
    ...over,
  };
}

describe("the order", () => {
  it("**puts the worst first, because the list is read to find the failure**", () => {
    const ordered = worstFirst([
      check({ id: "a", status: "pass" }),
      check({ id: "b", status: "fail" }),
      check({ id: "c", status: "warn" }),
      check({ id: "d", status: "error" }),
    ]);
    expect(ordered.map((c) => c.id)).toEqual(["b", "d", "c", "a"]);
  });

  it("**ranks `error` above `warn`**", () => {
    // A warning is an answer. An error means nobody has been told anything
    // about the code, which is the more urgent of the two.
    expect(severity("error")).toBeLessThan(severity("warn"));
    expect(severity("fail")).toBeLessThan(severity("error"));
  });

  it("**sorts an unrecognised status with the failures**", () => {
    // A status this build does not know is not evidence that anything is fine.
    expect(severity("something-new")).toBe(severity("fail"));
  });

  it("breaks ties by time, newest first", () => {
    const ordered = worstFirst([
      check({ id: "old", status: "pass", ran_at: "2026-01-01T00:00:00Z" }),
      check({ id: "new", status: "pass", ran_at: "2026-02-01T00:00:00Z" }),
    ]);
    expect(ordered.map((c) => c.id)).toEqual(["new", "old"]);
  });

  it("does not mutate what it was given", () => {
    const given = [check({ id: "a", status: "pass" }), check({ id: "b", status: "fail" })];
    worstFirst(given);
    expect(given.map((c) => c.id)).toEqual(["a", "b"]);
  });
});

describe("the branch's verdict", () => {
  it("**does not call an error a pass**", () => {
    // A branch reporting "passing" on the strength of checks that never
    // completed is the single most misleading thing this tab could say.
    expect(verdict([check({ status: "error" })])).toBe("unknown");
    expect(verdict([check({ status: "pass" }), check({ status: "error" })])).toBe("unknown");
  });

  it("reports the worst thing present", () => {
    expect(verdict([check({ status: "pass" })])).toBe("passing");
    expect(verdict([check({ status: "warn" }), check({ status: "pass" })])).toBe("warning");
    expect(verdict([check({ status: "error" }), check({ status: "fail" })])).toBe("failing");
    expect(verdict([])).toBe("none");
  });
});

describe("the sentence under it", () => {
  it("counts what produced the verdict", () => {
    const note = verdictNote([check({ status: "fail" }), check({ status: "fail" })]);
    expect(note).toContain("2 checks failed");
    expect(verdictNote([check({ status: "fail" })])).toContain("1 check failed");
  });

  it("**says an error does not block, and why**", () => {
    // Refusing to apply because *we* could not answer would make every outage
    // a freeze on every project (`code_checks.py`).
    const note = verdictNote([check({ status: "error" })]);
    expect(note).toContain("could not run");
    expect(note).toContain("does not block");
  });

  it("says a warning is the dataset's own policy rather than a near-failure", () => {
    expect(verdictNote([check({ status: "warn" })])).toContain("dataset's own policy");
  });

  it("says nothing has been checked rather than that everything passed", () => {
    expect(verdictNote([])).toContain("Nothing has been checked");
  });
});

describe("counting", () => {
  it("tallies by status and leaves absent ones absent", () => {
    const counts = tally([check({ status: "pass" }), check({ status: "pass" }), check({ status: "warn" })]);
    expect(counts).toEqual({ pass: 2, warn: 1 });
  });
});

describe("an empty tab", () => {
  it("**tells the three emptinesses apart**", () => {
    // Three different absences with three different remedies, and the reader
    // is the one who knows which they are looking at.
    expect(emptyReason(false, true)).toContain("Nothing has been committed");
    expect(emptyReason(true, true)).toContain("look at the sandbox branch");
    expect(emptyReason(true, false)).toContain("Open a pull request for this branch");
  });

  it("does not tell somebody on the default branch to open a request from it", () => {
    // Since §284 the default branch takes no direct commits while review is
    // required, so "open a pull request for this branch" would be advice that
    // cannot be followed.
    expect(emptyReason(true, true)).not.toContain("Open a pull request for this branch");
  });
});

describe("which file a check is about", () => {
  it("prefers the path, because a commit-backed file may have no model", () => {
    expect(checkTarget(check({ source_path: "src/t.sql", model_id: null }))).toBe("src/t.sql");
  });

  it("**says 'the whole change' rather than 'unknown' when neither is set**", () => {
    // A check can be about the proposal as a whole. That is what happened;
    // "unknown" would be wrong about it.
    expect(checkTarget(check({ source_path: null, model_id: null }))).toBe("the whole change");
    expect(checkTarget(check({ source_path: null, model_id: "m-1" }))).toBe("a transform");
  });
});
