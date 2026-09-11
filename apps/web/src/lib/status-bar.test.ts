import { describe, expect, it } from "vitest";

import {
  assistDetail,
  assistIsAProblem,
  assistLabel,
  assistState,
  checksAreAProblem,
  checksLabel,
  problemsAreAProblem,
  problemsLabel,
  savingDetail,
  savingIsAProblem,
  savingLabel,
} from "./status-bar";
import type { RepositoryCheck } from "./types";

function assist(over: Partial<Parameters<typeof assistState>[0]> = {}) {
  return assistState({
    editorReady: true,
    analysing: false,
    failed: false,
    answered: false,
    ...over,
  });
}

function check(over: Partial<RepositoryCheck> = {}): RepositoryCheck {
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
    ...over,
  } as RepositoryCheck;
}

describe("what the thing that makes the editor smart is doing", () => {
  it("says the editor is loading before anything else can matter", () => {
    // Monaco is imported dynamically, so this is a real state rather than a
    // moment — and until it is there, there is no editor to be smart about.
    expect(assist({ editorReady: false })).toBe("loading");
  });

  it("says loading even when an answer is already in hand", () => {
    expect(assist({ editorReady: false, answered: true })).toBe("loading");
  });

  it("is idle when nothing has been asked", () => {
    expect(assist({})).toBe("idle");
  });

  it("is working while a request is in flight", () => {
    expect(assist({ analysing: true })).toBe("working");
  });

  it("is ready once there is an answer", () => {
    expect(assist({ answered: true })).toBe("ready");
  });

  it("lets a failure outrank an answer, because the answer is stale", () => {
    expect(assist({ failed: true, answered: true })).toBe("unavailable");
  });

  it("lets a failure outrank a request still in flight", () => {
    expect(assist({ failed: true, analysing: true })).toBe("unavailable");
  });
});

describe("what the assist indicator says", () => {
  it("names each state", () => {
    expect(assistLabel("loading")).toBe("Editor loading");
    expect(assistLabel("idle")).toBe("Analysis on demand");
    expect(assistLabel("working")).toBe("Analysing");
    expect(assistLabel("ready")).toBe("Analysis ready");
    expect(assistLabel("unavailable")).toBe("Analysis unavailable");
  });

  it("never claims to be ready when it is idle", () => {
    // p.15's lesson: an editor that is not analysing while you type should say
    // so rather than behave like a dumb one in silence. "Ready" here would be
    // that silence dressed as reassurance.
    expect(assistLabel("idle")).not.toContain("Ready");
    expect(assistLabel("idle")).not.toContain("ready");
  });

  it("says on hover that nothing is watching you type", () => {
    const said = assistDetail("idle");
    expect(said).toContain("not watching you type");
    // And that this is a difference from Foundry rather than a fault.
    expect(said).toContain("Code Assist");
  });

  it("tells somebody whether to keep working when analysis is unavailable", () => {
    // "Analysis unavailable" alone is a fact nobody can act on. What they need
    // is whether a broken panel can let a broken thing through.
    const said = assistDetail("unavailable");
    expect(said).toContain("publish refuses");
  });

  it("treats only the failure as a problem", () => {
    expect(assistIsAProblem("unavailable")).toBe(true);
    for (const state of ["loading", "idle", "working", "ready"] as const) {
      expect(assistIsAProblem(state)).toBe(false);
    }
  });
});

describe("the problems indicator", () => {
  it("says nothing at all before anything has been asked", () => {
    // Zero problems and never having looked are the same number, and only one
    // of them is a claim this platform can make — Problems is a round trip.
    expect(problemsLabel(undefined)).toBeNull();
  });

  it("says none once it has looked and found none", () => {
    expect(problemsLabel(0)).toBe("No problems");
  });

  it("counts, and counts one in the singular", () => {
    expect(problemsLabel(1)).toBe("1 problem");
    expect(problemsLabel(3)).toBe("3 problems");
  });

  it("is a problem only when there are some", () => {
    expect(problemsAreAProblem(undefined)).toBe(false);
    expect(problemsAreAProblem(0)).toBe(false);
    expect(problemsAreAProblem(2)).toBe(true);
  });
});

describe("the checks indicator", () => {
  it("says nothing before the checks are known", () => {
    expect(checksLabel(undefined)).toBeNull();
  });

  it("puts a word to what `verdict` already decided", () => {
    expect(checksLabel([check({ status: "pass" })])).toBe("Checks passed");
    expect(checksLabel([check({ status: "fail" })])).toBe("Checks failing");
    expect(checksLabel([])).toBe("No checks");
  });

  it("does not call a check that could not run a pass", () => {
    // The fourth screen this session to need the sentence, and the one most
    // likely to be glanced at rather than read.
    expect(checksLabel([check({ status: "error" })])).not.toBe("Checks passed");
    expect(checksAreAProblem([check({ status: "error" })])).toBe(true);
  });

  it("covers every status the database can produce, and only those", () => {
    // **The premise this test started with was wrong**, and the fix was to
    // delete it rather than to weaken `verdict`. It asserted that a `running`
    // check is not a pass; `code_check_status` (db 0037) is exactly
    // `pass | warn | fail | error`, so there is no such status and `verdict`'s
    // fall-through to "passing" is a fall-through over one remaining value.
    //
    // What is worth pinning is that closed set, because the fall-through is
    // only safe while it stays closed: a fifth value added to the enum would
    // read as a pass, silently, which is the shape §300's survivor had.
    expect(checksLabel([check({ status: "pass" })])).toBe("Checks passed");
    expect(checksLabel([check({ status: "warn" })])).toBe("Checks warning");
    expect(checksLabel([check({ status: "fail" })])).toBe("Checks failing");
    expect(checksLabel([check({ status: "error" })])).toBe("Checks incomplete");
    expect(
      [
        checksAreAProblem([check({ status: "pass" })]),
        checksAreAProblem([check({ status: "warn" })]),
        checksAreAProblem([check({ status: "fail" })]),
        checksAreAProblem([check({ status: "error" })]),
      ],
    ).toEqual([false, false, true, true]);
  });

  it("is not a problem when there is nothing to know", () => {
    expect(checksAreAProblem(undefined)).toBe(false);
    expect(checksAreAProblem([])).toBe(false);
    expect(checksAreAProblem([check({ status: "pass" })])).toBe(false);
  });
});

describe("the saving indicator", () => {
  it("never says the word Saved on its own", () => {
    // The dangerous misreading: Foundry's editor saves to the branch, ours
    // keeps drafts in the browser, and nothing reaches the repository until
    // somebody commits. "Saved" would be true in the sense the word usually
    // carries and false in the sense that matters.
    expect(savingLabel(2, null)).toBe("2 files kept in this browser");
    expect(savingLabel(2, null)).not.toContain("Saved");
  });

  it("counts one file in the singular", () => {
    expect(savingLabel(1, null)).toBe("1 file kept in this browser");
  });

  it("says there is nothing uncommitted rather than nothing saved", () => {
    expect(savingLabel(0, null)).toBe("Nothing uncommitted");
  });

  it("says the work is not being kept when the browser will not store it", () => {
    expect(savingLabel(3, "This browser is not storing drafts")).toBe("Not kept");
    expect(savingIsAProblem("This browser is not storing drafts")).toBe(true);
    expect(savingIsAProblem(null)).toBe(false);
  });

  it("passes the storage warning through rather than rewording it", () => {
    // `editor-drafts.ts` already phrases both conditions, and a second wording
    // here would be two sentences about one thing.
    const warning = "These edits are too large to keep in the browser";
    expect(savingDetail(3, warning)).toBe(warning);
  });

  it("says on hover that kept is not committed", () => {
    expect(savingDetail(2, null)).toContain("not in the repository until you commit");
  });

  it("says everything is committed when nothing has changed", () => {
    expect(savingDetail(0, null)).toBe("Everything here is committed.");
  });
});
