/** p.3's Summary view: job statuses over time (§359). */
import { describe, expect, it } from "vitest";
import { nothingToShow, overWindow, tallest } from "./run-summary";

const MARCH_10 = new Date(Date.UTC(2026, 2, 10, 13, 45));
const day = (d: string, over: Partial<{ succeeded: number; failed: number; unfinished: number }> = {}) => ({
  day: `${d}T00:00:00Z`,
  succeeded: 0, failed: 0, unfinished: 0, ...over,
});

describe("the days a window covers", () => {
  it("has one bar per day, oldest first", () => {
    const bars = overWindow([], 7, MARCH_10);
    expect(bars).toHaveLength(7);
    expect(bars[0]!.day).toBe("2026-03-04");
    expect(bars[6]!.day).toBe("2026-03-10");
  });

  it("includes today", () => {
    // The boundary: a window that stopped at yesterday would hide the run
    // somebody just started and came to this screen to look at.
    expect(overWindow([], 30, MARCH_10).at(-1)!.day).toBe("2026-03-10");
  });

  it("puts each day's counts on its own bar", () => {
    const bars = overWindow(
      [day("2026-03-09", { succeeded: 2, failed: 1 })], 7, MARCH_10,
    );
    const ninth = bars.find((b) => b.day === "2026-03-09")!;
    expect([ninth.succeeded, ninth.failed, ninth.total]).toEqual([2, 1, 3]);
  });

  it("fills the days nothing ran on with noughts", () => {
    // **The gaps are the point.** The server sends only the days that had
    // runs; a chart drawn straight from those puts Monday beside Friday at
    // equal width and tells a reader the model ran steadily.
    const bars = overWindow(
      [day("2026-03-04", { succeeded: 1 }), day("2026-03-10", { succeeded: 1 })],
      7, MARCH_10,
    );
    expect(bars.map((b) => b.total)).toEqual([1, 0, 0, 0, 0, 0, 1]);
  });

  it("counts unfinished runs into the day's total", () => {
    const bars = overWindow([day("2026-03-10", { unfinished: 3 })], 7, MARCH_10);
    expect(bars.at(-1)!.total).toBe(3);
  });

  it("ignores a day outside the window", () => {
    // The negative control: a build that dropped every count onto the last bar
    // would satisfy the totals above.
    const bars = overWindow([day("2026-01-01", { succeeded: 9 })], 7, MARCH_10);
    expect(bars.every((b) => b.total === 0)).toBe(true);
  });

  it("reads the day from UTC, not from the reader's clock", () => {
    // `date_trunc('day', …)` is UTC, so a local-time day would land a run on
    // the wrong bar for every reader west of UTC — and quietly, since the
    // count is right and only the column is wrong.
    //
    // **The hour matters and the first draft's did not.** `vitest.config.ts`
    // runs this suite in `America/New_York` precisely so a timezone bug is
    // catchable, but 23:30 UTC is still the same date there — so the original
    // 23:30 proved nothing, and a mutant reading `getDate()` walked through
    // it. 02:00 UTC on the 11th is 22:00 on the 10th in New York, which is the
    // only shape of time that can tell the two apart.
    const earlyUtc = new Date(Date.UTC(2026, 2, 11, 2, 0));
    expect(overWindow([], 1, earlyUtc)[0]!.day).toBe("2026-03-11");
  });
});

describe("how tall the tallest bar is", () => {
  it("is the busiest day", () => {
    const bars = overWindow(
      [day("2026-03-09", { succeeded: 2 }), day("2026-03-10", { failed: 5 })],
      7, MARCH_10,
    );
    expect(tallest(bars)).toBe(5);
  });

  it("is never nought", () => {
    // **What a chart divides by.** An empty window scaling against its own
    // height is how every bar becomes `NaN%`.
    expect(tallest(overWindow([], 30, MARCH_10))).toBe(1);
    expect(tallest([])).toBe(1);
  });
});

describe("when there is nothing to draw", () => {
  it("says so in words", () => {
    // A chart of thirty empty bars says "this model failed thirty times to
    // run" as readily as "nothing happened" (§214).
    expect(nothingToShow(overWindow([], 30, MARCH_10), 30))
      .toBe("This model has not run in the last 30 days.");
  });

  it("quotes the window it was given", () => {
    // Not a hard-coded 30: the sentence must not drift from what was counted
    // (§323's rule, one screen over).
    expect(nothingToShow(overWindow([], 7, MARCH_10), 7)).toContain("7 days");
  });

  it("says nothing when a single run happened", () => {
    // The negative control, and the boundary that matters: one run in thirty
    // days is a chart, not an empty state.
    const bars = overWindow([day("2026-02-20", { succeeded: 1 })], 30, MARCH_10);
    expect(nothingToShow(bars, 30)).toBe("");
  });

  it("counts an unfinished run as something happening", () => {
    // A model whose only run is still queued has not "not run".
    const bars = overWindow([day("2026-03-10", { unfinished: 1 })], 30, MARCH_10);
    expect(nothingToShow(bars, 30)).toBe("");
  });
});
