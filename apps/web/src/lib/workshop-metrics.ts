/** What a module's usage numbers say (§396; `workshop` p.185-188).
 *
 * > "Workshop's usage metrics give module builders visibility into how their
 * > applications are being used… All metrics are aggregate counts and are not
 * > attributable to any specific user." (p.185)
 *
 * The server counts (`services/workshop_metrics.py`); this decides what the
 * counts *mean*. Same division as `action-metrics.ts`, which is the same
 * question asked about one action type rather than about a module.
 *
 * **The sentence this module exists to get right.** p.185 says "how many times
 * each action in the module has been successfully submitted", and p.186's
 * "available by default for all modules and do not require any additional
 * configuration" settles what that can mean: the module decides which actions
 * are *listed*, not which submissions are *counted*. A number that says
 * "Submissions" over a module's action list will be read as "submissions made
 * here" by anybody who has not read the page, and they would be wrong by
 * however much the action is used elsewhere.
 *
 * So the label says so. `scopeNote` is not decoration and not a disclaimer
 * bolted on afterwards - it is the difference between a panel that informs and
 * one that misleads about the only thing it reports (§214).
 */
import type { ModuleActionUsage } from "./types";

/** p.188's three windows, in the order the page offers them. */
export const PERIODS = [7, 30, 90] as const;
export const DEFAULT_PERIOD = 30;

/**
 * What the panel says the numbers are about.
 *
 * Shown always, not only when it would change a reading: a caveat that appears
 * conditionally is one a reader learns to expect the absence of.
 */
export function scopeNote(): string {
  return (
    "Counts every successful submission of these actions, including from " +
    "outside this module."
  );
}

/** p.185's overview card: "the total number of action submissions across the
 * module for a selected time period". */
export function total(rows: readonly ModuleActionUsage[]): number {
  return rows.reduce((sum, row) => sum + row.submissions, 0);
}

export function previousTotal(rows: readonly ModuleActionUsage[]): number {
  return rows.reduce((sum, row) => sum + row.previous, 0);
}

/**
 * p.185's "percentage change compared to the prior equivalent period".
 *
 * **Null rather than a number when there is nothing to compare against.** A
 * jump from zero is not "+100%", it is a first period - and a panel that
 * printed a percentage there would invite somebody to read a trend off a
 * single data point. Zero-to-zero is null for the same reason and not `0%`,
 * which would read as "steady".
 */
export function change(now: number, before: number): number | null {
  if (before === 0) return null;
  return ((now - before) / before) * 100;
}

/** How that change reads. Rounded to whole percent: a tenth of a percent on a
 * usage count is noise dressed as precision. */
export function changeLabel(now: number, before: number): string | null {
  const delta = change(now, before);
  if (delta === null) return null;
  const rounded = Math.round(delta);
  if (rounded === 0) return "no change";
  return `${rounded > 0 ? "+" : ""}${rounded}%`;
}

/** Whether a change is worth colouring as a rise. Null when there is no
 * comparison, so a caller can tell "up", "down" and "cannot say" apart. */
export function rising(now: number, before: number): boolean | null {
  const delta = change(now, before);
  if (delta === null || Math.round(delta) === 0) return null;
  return delta > 0;
}

/**
 * p.185's "proportional bar indicating relative usage", as a percentage.
 *
 * **Relative to the busiest action, not to the total.** A module with twelve
 * actions would otherwise draw twelve slivers, and the comparison a reader is
 * making is between the rows - which is the busiest, and by how much. The
 * busiest row is a full bar by construction.
 *
 * Zero when nothing has been submitted at all, so an unused module draws no
 * bars rather than twelve full ones from dividing by itself.
 */
export function share(row: ModuleActionUsage, rows: readonly ModuleActionUsage[]): number {
  const busiest = Math.max(0, ...rows.map((r) => r.submissions));
  if (busiest === 0) return 0;
  return (row.submissions / busiest) * 100;
}

/**
 * The sentence when a module has no actions.
 *
 * **Not the same as "no submissions".** A module that runs no actions has
 * nothing to report; a module whose actions nobody has used has something to
 * report and the answer is zero. Collapsing them would tell a builder their
 * action is unused when the module never wired one up.
 */
export function emptyReason(rows: readonly ModuleActionUsage[]): string | null {
  // Only one case answers with a sentence, and the other deliberately does
  // not: a module whose actions nobody has used draws its rows with zeroes in
  // them, because "this action exists and has been submitted nought times" is
  // the most useful thing this panel says. The first draft had a second branch
  // returning null for that case, which is a distinction spelled out and then
  // not made (§213).
  return rows.length === 0 ? "This module does not run any actions." : null;
}

/** Where an action is used, in words. p.185: "select an action to view which
 * widgets in the module use that action". */
export function usageLabel(row: ModuleActionUsage): string {
  const widgets = row.used_by.filter((u) => u.via === "widget").length;
  const events = row.used_by.length - widgets;
  const parts: string[] = [];
  if (widgets > 0) parts.push(`${widgets} widget${widgets === 1 ? "" : "s"}`);
  if (events > 0) parts.push(`${events} event${events === 1 ? "" : "s"}`);
  // A row always has at least one, because the action list is derived from
  // exactly these references - but a document can arrive from anywhere, and a
  // blank cell reads as a bug rather than as an empty list.
  return parts.length === 0 ? "not used" : parts.join(", ");
}
