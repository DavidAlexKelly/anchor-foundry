/**
 * Chart XY's chart-wide display options (`workshop` p.281, p.283–284; §468):
 * how the categories are ordered, which way a bar chart runs, and whether its
 * values and axes are labelled.
 *
 * > "Sort by: Controls sorting logic for how each charted value is displayed.
 * > By default, sorts categorical keys alphabetically from A to Z." (p.283)
 * >
 * > "Horizontal / vertical toggle: Controls the orientation of the chart. For a
 * > Bar chart, "Horizontal" is the default. For a Line chart or Scatter chart,
 * > only "Vertical" is allowed." (p.284)
 * >
 * > "Labels: Toggles the display of value labels on the chart." (p.281)
 */

import type { ChartPoint } from "./charts";

export const CHART_SORTS = {
  source: "As the data comes",
  keyAsc: "A to Z",
  keyDesc: "Z to A",
  valueDesc: "Largest first",
  valueAsc: "Smallest first",
} as const;
export type ChartSort = keyof typeof CHART_SORTS;

/**
 * **The data's own order by default, not p.283's A to Z.** A set-backed bar
 * arrives largest first and a dataset line chart in key order (`chart-sql.ts`
 * sorts a line by its dimension), and every chart saved before §468 is drawn
 * that way. A default that reordered them would change every existing chart
 * the day this shipped; A to Z is one click away.
 */
export function chartSortOf(raw: unknown): ChartSort {
  return typeof raw === "string" && Object.hasOwn(CHART_SORTS, raw)
    ? (raw as ChartSort) : "source";
}

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

/** The points in the chosen order. Keys compare as a person reads them, so
 * "Site 2" comes before "Site 10"; a tie on value falls back to the key, so a
 * chosen order never depends on what order the server happened to return. */
export function sortPoints(points: readonly ChartPoint[], sort: ChartSort): ChartPoint[] {
  const byKey = (a: ChartPoint, b: ChartPoint) => collator.compare(a.label, b.label);
  const out = [...points];
  switch (sort) {
    case "keyAsc":
      return out.sort(byKey);
    case "keyDesc":
      return out.sort((a, b) => byKey(b, a));
    case "valueAsc":
      return out.sort((a, b) => a.value - b.value || byKey(a, b));
    case "valueDesc":
      return out.sort((a, b) => b.value - a.value || byKey(a, b));
    default:
      return out;
  }
}

export type Orientation = "vertical" | "horizontal";

/** Vertical unless a bar chart says horizontal: p.284 allows only vertical
 * for a line or a scatter. Vertical rather than p.284's horizontal default for
 * the sort's reason - it is what every saved chart draws. */
export function orientationOf(raw: unknown, kind: string): Orientation {
  return raw === "horizontal" && kind === "bar" ? "horizontal" : "vertical";
}
