/**
 * p.3's Summary view: job statuses over time (§359).
 *
 * > "A Summary view on the right side of the page shows aggregated information
 * > on job statuses over time." (p.3)
 *
 * The counting is the server's, over a real window and with that window sent
 * alongside (§323's rule). What is here is the half a *chart* needs and a
 * count does not: which days the window covers, including the ones nothing ran
 * on, and how tall the tallest bar is.
 *
 * **Its own module with its own tests, not folded into a component**, for the
 * reason §358 learned twice over: vitest cannot parse `.tsx`, and a rule two
 * callers share cannot be pinned by comparing those callers — they move
 * together.
 */

import type { ModelRunDay } from "@/lib/types";

/** A day of the window, whether or not anything ran on it. */
export interface DayBar {
  /** `YYYY-MM-DD`, which is what the server's `date_trunc('day', …)` names. */
  day: string;
  succeeded: number;
  failed: number;
  unfinished: number;
  total: number;
}

function key(when: Date): string {
  return when.toISOString().slice(0, 10);
}

/**
 * Every day the window covers, oldest first, with noughts where nothing ran.
 *
 * **The gaps are the point.** The server sends only the days that had runs,
 * because that is all it knows; a chart drawn straight from those would put
 * Monday next to Friday at the same width and tell a reader the model ran
 * steadily. A quiet week has to look quiet.
 *
 * `today` is passed in rather than read from the clock, so this is a function
 * of its arguments and a test can ask about a Tuesday in March.
 */
export function overWindow(
  days: readonly ModelRunDay[],
  windowDays: number,
  today: Date,
): DayBar[] {
  const byDay = new Map<string, ModelRunDay>();
  for (const day of days) byDay.set(day.day.slice(0, 10), day);

  const bars: DayBar[] = [];
  for (let back = windowDays - 1; back >= 0; back -= 1) {
    // Built from a UTC midnight, matching `date_trunc('day', …)`: a local-time
    // day would land a run on the wrong bar for every reader west of UTC.
    const when = new Date(Date.UTC(
      today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() - back,
    ));
    const found = byDay.get(key(when));
    const succeeded = found?.succeeded ?? 0;
    const failed = found?.failed ?? 0;
    const unfinished = found?.unfinished ?? 0;
    bars.push({
      day: key(when),
      succeeded,
      failed,
      unfinished,
      total: succeeded + failed + unfinished,
    });
  }
  return bars;
}

/**
 * The tallest day in the window, and never nought.
 *
 * A chart scales its bars against this, and dividing by the height of an empty
 * window is how a summary of a model that has not run becomes `NaN%` on every
 * bar rather than an empty chart.
 */
export function tallest(bars: readonly DayBar[]): number {
  return Math.max(1, ...bars.map((bar) => bar.total));
}

/**
 * What the summary says when there is nothing to draw, or `""` when there is.
 *
 * **A chart of nothing is §214's control that cannot work**: thirty empty bars
 * say "this model failed thirty times to run" as readily as "nothing
 * happened", and the reader cannot tell which. A sentence can.
 *
 * The window is quoted from the answer rather than written in, so the sentence
 * cannot drift from what was counted.
 */
export function nothingToShow(
  bars: readonly DayBar[],
  windowDays: number,
): string {
  if (bars.some((bar) => bar.total > 0)) return "";
  return `This model has not run in the last ${windowDays} days.`;
}
