/**
 * p.281's **multiple series** on Chart XY, and p.282's **Display override**
 * naming each one (§541).
 *
 * > "Use single / multiple series: Allows either one or more chart series to
 * > be plotted for the selected X axis property. For instance, if "Alert Type"
 * > was selected as the X axis property, multiple series would allow the
 * > plotting of both the count of each "Alert Type" and also the sum of the
 * > "# of Hours Delayed" for each "Alert Type"." (p.281)
 * >
 * > "Display override: Optional. Overrides the legend display name of the
 * > current series." (p.282)
 *
 * The chart's own Measure is the first series; these are the rest. Each is
 * one more `/object-sets/group` question over the same set and the same X
 * axis property, and the answers are laid side by side as a grid - the shape
 * a segmented chart already draws, with a series where a segment was.
 */

import type { ChartPoint } from "./charts";
import { defaultValueTitle } from "./chart-display";
import type { Segmented } from "./chart-segments";
import { aggregationOf, aggregationRequest } from "./pie-chart";

export interface SeriesSpec {
  aggregate: string;
  measure: string | null;
  /** p.282's display override, or "" for the default. */
  name: string;
}

/** A bar's worth of series is plenty: past it the groups are slivers. */
export const MAX_SERIES = 6;

/** The extra series a chart holds, each read defensively: a saved document
 * is data, and an entry that is not an object is no series. */
export function seriesOf(raw: unknown): SeriesSpec[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((s): s is Record<string, unknown> => typeof s === "object" && s !== null)
    .slice(0, MAX_SERIES - 1)
    .map((s) => ({
      aggregate: aggregationOf(s.aggregate),
      measure: typeof s.measure === "string" && s.measure !== "" ? s.measure : null,
      name: typeof s.name === "string" ? s.name : "",
    }));
}

/** A series' name in the legend: its override, else what it plots. */
export function seriesName(spec: SeriesSpec): string {
  return spec.name.trim() || defaultValueTitle("bar", spec.aggregate, spec.measure);
}

/** What to ask the server for each series, or null for one still being
 * filled in, which is left out of the chart rather than asked and refused. */
export function seriesRequests(specs: readonly SeriesSpec[]) {
  return specs.map((s) => aggregationRequest(s.aggregate, s.measure));
}

/**
 * The series side by side, as a grid of categories by series.
 *
 * The first series' categories come first and in its order, which is the
 * order p.283's Sort by put them in; a category only a later series has
 * follows. A series with no value for a category has a missing one (NaN),
 * which is not the zero a count of nothing would be.
 */
export function mergeSeries(
  first: readonly ChartPoint[],
  rest: readonly (readonly ChartPoint[])[],
  names: readonly string[],
): Segmented {
  const categories = first.map((p) => p.label);
  for (const series of rest) {
    for (const p of series) if (!categories.includes(p.label)) categories.push(p.label);
  }
  const all = [first, ...rest];
  return {
    categories,
    segments: [...names],
    values: categories.map((category) =>
      all.map((series) => series.find((p) => p.label === category)?.value ?? NaN)),
  };
}
