/**
 * What an action's numbers say (§323; `action-types` p.164-166).
 *
 * The counting is in `apps/api/tests/test_action_metrics.py`. What is here is
 * the half a database cannot check: whether four integers turn into a sentence
 * somebody can act on.
 */
import { describe, expect, it } from "vitest";
import {
  FAILURE_LABELS,
  breakdown,
  durationText,
  failureHint,
  failureLabel,
  idleMessage,
  isIdle,
  needsAttention,
  runSummary,
  successRate,
  successText,
} from "./action-metrics";
import type { ActionMetrics } from "./types";

function metrics(over: Partial<ActionMetrics> = {}): ActionMetrics {
  return {
    succeeded: 0,
    failed: 0,
    running: 0,
    total: 0,
    p95_seconds: null,
    window_days: 30,
    failures: [],
    ...over,
  };
}

describe("an action nobody has run", () => {
  it("says so, with the window it looked over", () => {
    // The window is the server's, printed rather than assumed: a screen with
    // "30 days" written into it is one that lies the day the constant moves.
    const m = metrics({ window_days: 14 });
    expect(isIdle(m)).toBe(true);
    expect(idleMessage(m)).toContain("14 days");
  });

  it("is not idle the moment one run exists", () => {
    expect(isIdle(metrics({ succeeded: 1, total: 1 }))).toBe(false);
    // Including one that is still going: something is happening, which is the
    // opposite of the claim `isIdle` makes.
    expect(isIdle(metrics({ running: 1, total: 1 }))).toBe(false);
  });
});

describe("the success rate", () => {
  it("is over the runs that finished, not over all of them", () => {
    // **The assertion that distinguishes the two denominators.** Nine of ten
    // finished runs succeeded; a tenth is still going. Over finished runs that
    // is 90%; over every run it would be 81.8% — so an action would appear to
    // get worse simply for being slow, which is the opposite of what p.164's
    // reader wants to see.
    const m = metrics({ succeeded: 9, failed: 1, running: 1, total: 11 });
    expect(successRate(m)).toBeCloseTo(90);
    expect(successText(m)).toBe("90.0%");
  });

  it("is null when nothing has finished, rather than nought or a hundred", () => {
    // Both defaults are claims the numbers do not support: 0% reads as
    // "everything is broken" and 100% as "all is well", over no evidence.
    const m = metrics({ running: 3, total: 3 });
    expect(successRate(m)).toBeNull();
    expect(successText(m)).toBe("—");
  });

  it("keeps a decimal, because 99.9% and 100% are a different answer", () => {
    // An action run a thousand times with one failure is not perfect, and a
    // whole-number rounding would report it as perfect.
    const m = metrics({ succeeded: 999, failed: 1, total: 1000 });
    expect(successText(m)).toBe("99.9%");
    expect(successText(metrics({ succeeded: 1000, total: 1000 }))).toBe("100.0%");
  });
});

describe("whether the failures need attention", () => {
  it("is quiet when nothing failed", () => {
    expect(needsAttention(metrics({ succeeded: 500, total: 500 }))).toBe(false);
  });

  it("notices a bad rate over a small number of runs", () => {
    // One failure in two is 50%: too few to trip a count threshold, and
    // obviously worth looking at.
    expect(needsAttention(metrics({ succeeded: 1, failed: 1, total: 2 }))).toBe(true);
  });

  it("notices a good rate hiding a lot of failures", () => {
    // **The half a rate alone would miss.** Forty failures out of four
    // thousand is 99% and forty people who could not do their job.
    const m = metrics({ succeeded: 3960, failed: 40, total: 4000 });
    expect(successRate(m)!).toBeGreaterThan(98);
    expect(needsAttention(m)).toBe(true);
  });

  it("stays quiet for a healthy action with the odd failure", () => {
    // One in a thousand is neither a bad rate nor a lot of failures, and an
    // indicator that is always lit is one people stop reading.
    expect(needsAttention(metrics({ succeeded: 999, failed: 1, total: 1000 }))).toBe(false);
  });
});

describe("the P95 duration", () => {
  it("is a dash when nothing has finished", () => {
    expect(durationText(null)).toBe("—");
  });

  it("reads in the unit that suits the number", () => {
    expect(durationText(0.25)).toBe("250ms");
    expect(durationText(12.34)).toBe("12.3s");
    // **Minutes above a minute.** "212.4s" is a duration the reader has to do
    // arithmetic on to learn it is nearly four minutes.
    expect(durationText(212.4)).toBe("3m 32s");
    expect(durationText(120)).toBe("2m");
  });

  it("does not report a slow action as instant", () => {
    // Zero is a real answer and has to survive; it is `null` that means
    // "nothing finished".
    expect(durationText(0)).toBe("0ms");
  });
});

describe("p.166's categories", () => {
  it("are named in English rather than in the database's vocabulary", () => {
    expect(failureLabel("invalid_parameter")).toBe("Invalid parameter");
    expect(failureLabel("side_effect")).toBe("Side effect");
  });

  it("carry the sentence that says what to do", () => {
    // **The gloss matters more than the name.** "Scale limit failure" tells a
    // reader nothing they can act on; p.166's own wording does.
    expect(failureHint("scale_limit")).toContain("permitted number");
    expect(failureHint("authentication")).toContain("submission criteria");
    for (const key of Object.keys(FAILURE_LABELS)) {
      expect(failureHint(key).length, key).toBeGreaterThan(0);
    }
  });

  it("renders an unknown identifier readably rather than dropping it", () => {
    // db 0079's CHECK means one cannot arrive today, but p.166 reserves two
    // more for function-backed actions. A lookup returning "" would silently
    // remove a bar from a chart that still added up to the count beside it.
    expect(failureLabel("user_facing_function")).toBe("User facing function");
    expect(failureHint("user_facing_function")).toBe("");
  });
});

describe("the failure breakdown", () => {
  it("is biggest first, with each share over the failures", () => {
    // **Over the failures, not over all runs.** p.165 introduces the
    // categories as a breakdown of *why it failed*; a share of every run would
    // render a healthy action's bad day as a row of 0%s.
    const rows = breakdown([
      { category: "conflict", failures: 1 },
      { category: "invalid_parameter", failures: 3 },
    ]);
    expect(rows.map((r) => r.category)).toEqual(["invalid_parameter", "conflict"]);
    expect(rows.map((r) => Math.round(r.share))).toEqual([75, 25]);
    expect(rows.map((r) => r.label)).toEqual(["Invalid parameter", "Conflict"]);
  });

  it("breaks a tie by name, so the order does not wander between reads", () => {
    // Two categories with the same count would otherwise come back in whatever
    // order the server's GROUP BY produced, and a chart whose bars swap places
    // on a refresh is one people stop trusting.
    const rows = breakdown([
      { category: "side_effect", failures: 2 },
      { category: "conflict", failures: 2 },
    ]);
    expect(rows.map((r) => r.category)).toEqual(["conflict", "side_effect"]);
  });

  it("is an empty list for no failures rather than a NaN", () => {
    // `0/0` is `NaN`, which renders as the word.
    expect(breakdown([])).toEqual([]);
  });

  it("does not mutate what it was given", () => {
    // It sorts, and the caller's array is a react-query cache entry.
    const given = [
      { category: "conflict", failures: 1 },
      { category: "invalid_parameter", failures: 3 },
    ];
    breakdown(given);
    expect(given.map((f) => f.category)).toEqual(["conflict", "invalid_parameter"]);
  });
});

describe("one run in the history", () => {
  it("names a failure by its category rather than its message", () => {
    // The message is the engine's or the criterion's own words and can be a
    // paragraph; the history is a list somebody scans.
    expect(runSummary({ status: "failed", failure_category: "conflict" }))
      .toBe("Failed — Conflict");
  });

  it("still says it failed when there is no category", () => {
    // Every failure written since db 0079 has one, and rows from before it do
    // not — "Failed" is the honest answer, and dropping the row would make the
    // list disagree with the count above it.
    expect(runSummary({ status: "failed", failure_category: null })).toBe("Failed");
  });

  it("distinguishes a run that is still going from one that worked", () => {
    expect(runSummary({ status: "succeeded", failure_category: null })).toBe("Succeeded");
    expect(runSummary({ status: "running", failure_category: null })).toBe("Running");
  });
});
