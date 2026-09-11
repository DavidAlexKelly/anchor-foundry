import { describe, expect, it } from "vitest";

import { andMore, mostRecent, namedFailures, status, summary } from "./test-runs-in-checks";
import type { CodeTestOutcome, CodeTestRun } from "./types";

function outcome(over: Partial<CodeTestOutcome>): CodeTestOutcome {
  return {
    id: "tests/test_a.py::test_one",
    outcome: "passed",
    duration_ms: 0,
    file: "tests/test_a.py",
    line: 1,
    message: null,
    detail: null,
    ...over,
  };
}

function run(over: Partial<CodeTestRun>): CodeTestRun {
  return {
    id: "r-1",
    repo_id: "repo",
    branch: "main",
    status: "succeeded",
    outcomes: [],
    error: null,
    queued_at: "",
    started_at: null,
    finished_at: null,
    ...over,
  };
}

describe("which run the tab shows", () => {
  it("**the most recent, not a history**", () => {
    // The Checks tab answers "what is the state of this branch". A list of
    // every run somebody pressed the button on is a different question with
    // its own home, and it would grow without bound on exactly the branch
    // whose state matters most.
    const newest = run({ id: "new" });
    expect(mostRecent([newest, run({ id: "old" })])?.id).toBe("new");
  });

  it("has nothing to show when nothing has run", () => {
    expect(mostRecent([])).toBeUndefined();
  });
});

describe("the status word", () => {
  it("**uses the vocabulary the proposal checks already use**", () => {
    // The two kinds of row sit in one list under one heading, and a reader who
    // had to learn two sets of words for them would learn neither.
    expect(status(run({ outcomes: [outcome({})] }))).toBe("passed");
    expect(status(run({ outcomes: [outcome({ outcome: "failed" })] }))).toBe("failed");
    expect(status(run({ status: "running" }))).toBe("pending");
    expect(status(run({ status: "queued" }))).toBe("pending");
    expect(status(undefined)).toBe("none");
  });

  it("**does not call an empty run passed**", () => {
    // The assertion this whole feature hangs off, arriving on a third screen.
    expect(status(run({ status: "failed", outcomes: [] }))).toBe("failed");
  });

  it("**counts a run that could not happen as failed rather than pending**", () => {
    // It is finished, and it is not good news. Calling it pending would leave
    // the tab claiming a run is still going that stopped hours ago.
    expect(status(run({ status: "errored", outcomes: null, error: "no pytest" }))).toBe(
      "failed",
    );
  });

  it("counts an error among the outcomes as a failure", () => {
    expect(status(run({ outcomes: [outcome({}), outcome({ outcome: "error" })] }))).toBe(
      "failed",
    );
  });
});

describe("the summary", () => {
  it("**tells never-run from ran-and-found-nothing**", () => {
    // The one that would be easiest to collapse, and the one where collapsing
    // does most harm: the first is "press the button", the second is "write a
    // test".
    expect(summary(undefined)).toContain("Run them from the Tests panel");
    expect(summary(run({ status: "failed", outcomes: [] }))).toContain(
      "No unit tests in this repository",
    );
  });

  it("counts what happened when something did", () => {
    expect(
      summary(run({
        outcomes: [outcome({}), outcome({ outcome: "failed" }), outcome({ outcome: "skipped" })],
      })),
    ).toBe("1 passed, 1 failed, 1 skipped.");
  });

  it("shows the platform's own message when the run did not happen", () => {
    expect(
      summary(run({ status: "errored", outcomes: null, error: "the tests exceeded the 300s time limit" })),
    ).toBe("the tests exceeded the 300s time limit");
  });

  it("says what it is doing while it is doing it", () => {
    expect(summary(run({ status: "queued" }))).toBe("Queued.");
    expect(summary(run({ status: "running" }))).toBe("Running now.");
  });
});

describe("which failures are named", () => {
  it("**names them rather than counting them**", () => {
    // "3 failed" sends you to the panel; `tests/test_daily.py::test_totals`
    // sends you to the test.
    const rows = [
      outcome({ id: "a", outcome: "failed" }),
      outcome({ id: "b" }),
      outcome({ id: "c", outcome: "error" }),
    ];
    expect(namedFailures(run({ outcomes: rows }))).toEqual(["a", "c"]);
  });

  it("**caps the list, because a branch with two hundred failures has one problem**", () => {
    const rows = Array.from({ length: 8 }, (_, i) =>
      outcome({ id: `f${i}`, outcome: "failed" }),
    );
    expect(namedFailures(run({ outcomes: rows }))).toHaveLength(5);
    expect(andMore(run({ outcomes: rows }))).toBe("and 3 more");
  });

  it("says nothing about the ones it left out when it left none out", () => {
    expect(andMore(run({ outcomes: [outcome({ outcome: "failed" })] }))).toBeNull();
    expect(andMore(run({ outcomes: [] }))).toBeNull();
    expect(andMore(undefined)).toBeNull();
  });

  it("names nothing when nothing failed", () => {
    expect(namedFailures(run({ outcomes: [outcome({}), outcome({})] }))).toEqual([]);
    expect(namedFailures(undefined)).toEqual([]);
  });
});
