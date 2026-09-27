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

/** A missing value (§537) has no size to order by, so it goes last either
 * way; NaN in a comparison would leave the order to the engine. */
function missingLast(a: ChartPoint, b: ChartPoint): number {
  return Number(Number.isNaN(a.value)) - Number(Number.isNaN(b.value));
}

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
      return out.sort((a, b) => missingLast(a, b) || a.value - b.value || byKey(a, b));
    case "valueDesc":
      return out.sort((a, b) => missingLast(a, b) || b.value - a.value || byKey(a, b));
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

/**
 * p.283's value axis (§536): its scale type and its bounds.
 *
 * > "Scale type: Allows the value axis scale to be set to either "Linear" (the
 * > default) or "Logarithmic."" (p.283)
 * >
 * > "Minimum bound: By default, set to "Automatically calculate minimum bound"
 * > based on the displayed chart values. If switched to "Min," the module
 * > builder can control the minimum value display on the value axis." (p.283;
 * > p.284's Maximum bound is the same sentence)
 */
export const SCALE_TYPES = { linear: "Linear", log: "Logarithmic" } as const;
export type ScaleType = keyof typeof SCALE_TYPES;

export interface ValueAxis {
  scale: ScaleType;
  /** A fixed bound, or null to calculate it from the values drawn. */
  min: number | null;
  max: number | null;
}

function boundOf(raw: unknown): number | null {
  return typeof raw === "number" && Number.isFinite(raw) ? raw : null;
}

export function valueAxisOf(props: {
  scaleType?: unknown; minBound?: unknown; maxBound?: unknown;
}): ValueAxis {
  return {
    scale: props.scaleType === "log" ? "log" : "linear",
    min: boundOf(props.minBound),
    max: boundOf(props.maxBound),
  };
}

/** What is wrong with the bounds as set, or null. A chart whose bounds have a
 * problem draws with calculated ones and says why, rather than drawing an
 * axis that runs backwards or a logarithm of zero. */
export function axisProblem(axis: ValueAxis): string | null {
  if (axis.min !== null && axis.max !== null && axis.min >= axis.max) {
    return "The minimum bound must be below the maximum bound.";
  }
  if (axis.scale === "log" && ((axis.min ?? 1) <= 0 || (axis.max ?? 1) <= 0)) {
    return "A logarithmic axis has no zero or negative values, so its bounds must be above 0.";
  }
  return null;
}

export interface ValueScale {
  lo: number;
  hi: number;
  ticks: number[];
  /** Where a value sits up the axis: 0 at the bottom bound, 1 at the top, and
   * outside that when a fixed bound cuts it off. Null when it cannot be drawn
   * at all: zero or below on a logarithmic axis. */
  at: (value: number) => number | null;
  /** Where a bar starts: zero when the axis shows it, else the nearer end. */
  base: number;
  /** How many of the values cannot be drawn, for the chart to say. */
  undrawn: number;
}

const LOG_TICKS = 6;

/**
 * The axis the values are drawn against. Linear and calculated is what every
 * chart before §536 drew, unchanged: from the lower of zero and the least
 * value to the higher of zero and the greatest, with five evenly spaced ticks.
 * A logarithmic one runs between whole powers of ten around the positive
 * values, with a tick at each power, thinned to six.
 */
export function valueScale(given: readonly number[], axis: ValueAxis): ValueScale {
  // A missing value (§537's NaN) has no place on any axis and says nothing
  // about where the axis should run.
  const values = given.filter(Number.isFinite);
  const { min, max } = axisProblem(axis) === null ? axis : { min: null, max: null };
  if (axis.scale === "log") {
    const positive = values.filter((v) => v > 0);
    const power = (v: number, round: (x: number) => number) =>
      10 ** round(Math.log10(v));
    let lo = min ?? (positive.length ? power(Math.min(...positive), Math.floor) : 1);
    let hi = max ?? (positive.length ? power(Math.max(...positive), Math.ceil) : 10);
    if (hi <= lo) {
      if (min !== null) hi = lo * 10;
      else lo = hi / 10;
    }
    const span = Math.log10(hi) - Math.log10(lo);
    // `Math.log10` is exact on a power of ten, so a calculated end is its
    // own tick without an epsilon to round it there.
    const first = Math.ceil(Math.log10(lo));
    const last = Math.floor(Math.log10(hi));
    const step = Math.max(1, Math.ceil((last - first + 1) / LOG_TICKS));
    const ticks = [lo];
    for (let k = first; k <= last; k += step) {
      const tick = 10 ** k;
      if (tick > lo && tick < hi) ticks.push(tick);
    }
    ticks.push(hi);
    return {
      lo, hi, ticks,
      at: (v) => (v > 0 ? (Math.log10(v) - Math.log10(lo)) / span : null),
      base: 0,
      undrawn: values.length - positive.length,
    };
  }
  let lo = min ?? Math.min(0, ...values);
  let hi = max ?? Math.max(0, ...values);
  if (hi <= lo) {
    if (min !== null) hi = lo + (Math.abs(lo) || 1);
    else if (max !== null) lo = hi - (Math.abs(hi) || 1);
    else hi = lo + 1;
  }
  const span = hi - lo;
  const at = (v: number) => (Number.isFinite(v) ? (v - lo) / span : null);
  return {
    lo, hi,
    ticks: Array.from({ length: 5 }, (_, i) => lo + (span * i) / 4),
    at,
    base: (Math.min(Math.max(0, lo), hi) - lo) / span,
    undrawn: 0,
  };
}

/**
 * p.283's axis titles (§536).
 *
 * > "Show title: If enabled, displays the title of the categorical axis and
 * > also allows this title to be override. By default, this title will display
 * > the property type(s) plotted within the chart's series." (p.283)
 * >
 * > "… the title of the value axis … By default, this title will display the
 * > aggregation type(s) used within the chart's series." (p.283)
 */
export interface AxisTitles {
  category: string | null;
  value: string | null;
}

const AGGREGATE_WORDS: Record<string, string> = {
  sum: "Sum", avg: "Average", min: "Minimum", max: "Maximum",
};

/** p.283's default value title: the aggregation, and what it is of. A scatter
 * plots a column rather than an aggregation, so its default is the column. A
 * time series set is its property, under the bucket's aggregation when it has
 * one of these. */
export function defaultValueTitle(
  kind: string, aggregate: string | null | undefined, measure: string | null | undefined,
): string {
  if (kind === "scatter") return measure ?? "";
  if ((aggregate ?? "count") === "count") return "Count";
  const word = AGGREGATE_WORDS[aggregate ?? ""];
  // A series bucketed some other way (its last reading, say) is its property.
  return word ? `${word} of ${measure ?? "…"}` : measure ?? "";
}

/** A title is shown only when asked for, and is its override when there is
 * one, else its default. A blank override is no override: a title switched on
 * and emptied would be a gap where the axis says nothing. */
export function axisTitlesOf(
  props: {
    showCategoryTitle?: unknown; categoryTitle?: unknown;
    showValueTitle?: unknown; valueTitle?: unknown;
  },
  defaults: AxisTitles,
): AxisTitles {
  const pick = (show: unknown, override: unknown, fallback: string | null) => {
    if (show !== true) return null;
    const own = typeof override === "string" ? override.trim() : "";
    return own || fallback || null;
  };
  return {
    category: pick(props.showCategoryTitle, props.categoryTitle, defaults.category),
    value: pick(props.showValueTitle, props.valueTitle, defaults.value),
  };
}

/**
 * p.281's Area options and p.282's null display, for a line chart (§537).
 *
 * > "Area options: Provides three visualization options for line charts:
 * > "Line" (which display a simple line chart), "Area" (which plots a line
 * > chart and shades the area beneath each line), and "Stacked" …" (p.281)
 * >
 * > "Display of null/missing values: Only available for Line chart. … "Gap"
 * > (where a missing value is displayed as an empty gap in a plotted line),
 * > "Ignored" (where a missing value is ignored and a plotted line instead
 * > connects the previous and next available values), or "Zeroes" (where a
 * > missing value is treated as equivalent to value of "0)." (p.282)
 *
 * A missing value travels as NaN: a point whose category is known and whose
 * value is not, so a gap can stand where it was.
 */
export const AREA_OPTIONS = { line: "Line", area: "Area" } as const;
export type AreaOption = keyof typeof AREA_OPTIONS;

export function areaOf(raw: unknown): AreaOption {
  return raw === "area" ? "area" : "line";
}

export const NULL_DISPLAYS = { ignored: "Ignored", gap: "Gap", zeroes: "Zeroes" } as const;
export type NullDisplay = keyof typeof NULL_DISPLAYS;

/** Ignored unless set: it is what every line chart drew before p.282 was
 * read, a dataset's row and a series' reading with no value both dropped. */
export function nullDisplayOf(raw: unknown): NullDisplay {
  return typeof raw === "string" && Object.hasOwn(NULL_DISPLAYS, raw)
    ? (raw as NullDisplay) : "ignored";
}

/** The points to draw. p.282's choice is a line chart's alone; any other
 * chart leaves a missing value out, since a zero bar is a claim about the
 * data and "this could not be measured" is not that claim. */
export function withMissing(
  points: readonly ChartPoint[], kind: string, display: NullDisplay,
): ChartPoint[] {
  if (kind === "line" && display === "gap") return [...points];
  if (kind === "line" && display === "zeroes") {
    return points.map((p) => (Number.isNaN(p.value) ? { ...p, value: 0 } : p));
  }
  return points.filter((p) => !Number.isNaN(p.value));
}

/** How many points have no value, for the chart to say what it did with them. */
export function missingCount(points: readonly ChartPoint[]): number {
  return points.filter((p) => Number.isNaN(p.value)).length;
}

/** What became of the missing values, in the chart's words, or null when
 * there were none. */
export function missingText(count: number, kind: string, display: NullDisplay): string | null {
  if (count === 0) return null;
  const what = count === 1 ? "1 value is missing" : `${count} values are missing`;
  if (kind === "line" && display === "gap") return `${what}, left as a gap in the line.`;
  if (kind === "line" && display === "zeroes") return `${what}, drawn as zero.`;
  return `${what} and not drawn.`;
}
