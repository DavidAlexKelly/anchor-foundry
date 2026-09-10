import { describe, expect, it } from "vitest";

import {
  canEditProject,
  durationLabel,
  isAProblem,
  isSettled,
  runLabel,
  shouldPoll,
  tally,
  target,
  verdict,
  worstFirst,
} from "./test-runs";
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

describe("whether the panel keeps asking", () => {
  it("**stops once the run has an answer, either way**", () => {
    // A run is a job (decision 0004: unit tests are customer Python and do not
    // run in the API), so polling is the only way to learn it finished - and
    // this going false is the only way it ever stops.
    expect(shouldPoll(run({ status: "queued" }))).toBe(true);
    expect(shouldPoll(run({ status: "running" }))).toBe(true);
    expect(shouldPoll(run({ status: "succeeded" }))).toBe(false);
    expect(shouldPoll(run({ status: "failed" }))).toBe(false);
    expect(shouldPoll(run({ status: "errored", error: "no" }))).toBe(false);
  });

  it("does not poll when nothing has been asked for", () => {
    expect(shouldPoll(undefined)).toBe(false);
  });

  it("settles on every terminal status, so none is left polling for ever", () => {
    expect(isSettled(run({ status: "errored", error: "no" }))).toBe(true);
    expect(isSettled(run({ status: "running" }))).toBe(false);
  });
});

describe("the order rows are shown in", () => {
  it("**puts failures first**, because that is what the panel was opened for", () => {
    // Two hundred tests and one failure is the ordinary case, and a panel that
    // made you scroll for it is one people stop opening.
    const rows = [
      outcome({ id: "p1" }),
      outcome({ id: "s1", outcome: "skipped" }),
      outcome({ id: "f1", outcome: "failed" }),
      outcome({ id: "e1", outcome: "error" }),
    ];
    expect(worstFirst(rows).map((o) => o.id)).toEqual(["f1", "e1", "s1", "p1"]);
  });

  it("keeps the order they ran in within a severity", () => {
    // File order is the only order a reader can predict.
    const rows = [
      outcome({ id: "f2", outcome: "failed" }),
      outcome({ id: "f1", outcome: "failed" }),
    ];
    expect(worstFirst(rows).map((o) => o.id)).toEqual(["f2", "f1"]);
  });

  it("does not mutate what it was given", () => {
    const rows = [outcome({ id: "p" }), outcome({ id: "f", outcome: "failed" })];
    worstFirst(rows);
    expect(rows.map((o) => o.id)).toEqual(["p", "f"]);
  });
});

describe("the summary line", () => {
  it("**does not call an empty run a pass**", () => {
    // The assertion this whole feature hangs off. "Nothing failed" and
    // "everything passed" are the same number, and code-repositories.md §10
    // names it: a suite that cannot fail is not accepted.
    const said = verdict(run({ status: "failed", outcomes: [] }));
    expect(said).toContain("No unit tests found");
    // And it says what to do about it, because somebody who has never written
    // one cannot be expected to know the naming rule.
    expect(said).toContain("test_*.py");
  });

  it("counts what happened when something did", () => {
    expect(
      verdict(run({
        outcomes: [outcome({}), outcome({ outcome: "failed" }), outcome({ outcome: "skipped" })],
      })),
    ).toBe("1 passed, 1 failed, 1 skipped");
  });

  it("says only what applies, rather than three zeroes", () => {
    expect(verdict(run({ outcomes: [outcome({}), outcome({})] }))).toBe("2 passed");
  });

  it("**shows the platform's own message when the run did not happen**", () => {
    // Not "your tests failed": none of theirs ran. This is the distinction
    // transform_runner.py keeps with result.json, reaching a reader.
    expect(
      verdict(run({ status: "errored", outcomes: null, error: "the tests exceeded the 300s time limit" })),
    ).toBe("the tests exceeded the 300s time limit");
  });

  it("says what it is doing while it is doing it", () => {
    expect(verdict(run({ status: "queued" }))).toContain("Waiting");
    expect(verdict(run({ status: "running" }))).toContain("Running");
  });

  it("distinguishes never-run from run-and-empty", () => {
    // Two different situations with two different remedies, and a panel that
    // showed the same sentence for both would answer neither.
    expect(verdict(undefined)).toContain("No tests have been run");
    expect(verdict(run({ status: "failed", outcomes: [] }))).toContain("No unit tests found");
  });
});

describe("whether the verdict is bad news", () => {
  it("**counts a run that could not happen as bad news**", () => {
    // The case a boolean over `failed` alone would miss, and the quietest
    // possible way to lose a test suite.
    expect(isAProblem(run({ status: "errored", outcomes: null, error: "no" }))).toBe(true);
  });

  it("counts an empty run as bad news, for the same reason the verdict does", () => {
    expect(isAProblem(run({ status: "failed", outcomes: [] }))).toBe(true);
  });

  it("is not bad news while it is still running", () => {
    // Nothing is wrong yet, and colouring a running panel red would teach
    // people to ignore the colour.
    expect(isAProblem(run({ status: "running" }))).toBe(false);
    expect(isAProblem(undefined)).toBe(false);
  });

  it("is not bad news when everything passed", () => {
    expect(isAProblem(run({ outcomes: [outcome({})] }))).toBe(false);
  });
});

describe("counting", () => {
  it("**folds errors into the failed count and only there**", () => {
    // The row keeps them apart because the first thing to look at differs;
    // the count does not, because "3 failed" and "2 failed, 1 errored" say the
    // same thing to somebody deciding whether to look.
    expect(
      tally([outcome({ outcome: "failed" }), outcome({ outcome: "error" }), outcome({})]),
    ).toEqual({ passed: 1, failed: 2, skipped: 0 });
  });
});

describe("a row", () => {
  it("says nothing about a duration that is not information", () => {
    expect(durationLabel(outcome({ duration_ms: 0 }))).toBeNull();
    expect(durationLabel(outcome({ duration_ms: 40 }))).toBe("40ms");
    expect(durationLabel(outcome({ duration_ms: 2500 }))).toBe("2.5s");
  });

  it("**does not guess where to jump when pytest did not say**", () => {
    // A collection error names the module that would not import and no test
    // file. A row that jumped somewhere plausible and wrong is worse than one
    // that does not jump, because the reader believes it.
    expect(target(outcome({ file: null }))).toBeNull();
    expect(target(outcome({ file: "tests/test_a.py", line: 12 }))).toEqual({
      path: "tests/test_a.py",
      line: 12,
    });
  });

  it("falls back to the first line rather than to no line", () => {
    // The file is the useful half; opening it at the top is right when the
    // line is unknown, and refusing to open it would be worse.
    expect(target(outcome({ line: null }))).toEqual({ path: "tests/test_a.py", line: 1 });
  });
});

describe("the button", () => {
  it("**reports progress rather than inviting a second press**", () => {
    // The server refuses a fourth queued run, and a button that still said
    // "Run tests" would be walking people into that refusal.
    expect(runLabel(run({ status: "running" }))).toBe("Running…");
    expect(runLabel(run({ status: "queued" }))).toBe("Running…");
    expect(runLabel(run({ status: "succeeded" }))).toBe("Run tests");
    expect(runLabel(undefined)).toBe("Run tests");
  });
});

describe("who is offered the Run button", () => {
  it("**not a viewer**, because running tests executes code they may not write", () => {
    // The line `preview_transform` draws and the route takes. Offered and
    // refused is worse than not offered (§214).
    expect(canEditProject("viewer")).toBe(false);
    expect(canEditProject("editor")).toBe(true);
    expect(canEditProject("owner")).toBe(true);
  });
});
