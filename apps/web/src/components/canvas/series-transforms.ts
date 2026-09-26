/** Time series transforms on a time series set variable (§524; `workshop`
 * p.583-586).
 *
 * > "A time series transform performs a mathematical operation on input time
 * > series data to yield a new output time series. These input time series
 * > can be time series properties or the outputs from other transforms,
 * > which allows multiple transforms to be chained together." (p.583)
 *
 * The server computes them (`services/time_series.py`), over every point
 * before the cap. This file is what the variable editor offers and says, and
 * the subset of the server's checks a form can make before Save. The
 * vocabularies are held to the server's by `test_time_series_transforms.py`.
 */

export const TRANSFORM_KINDS = ["cumulative", "rolling", "derivative", "shift", "range"] as const;
export type TransformKind = (typeof TRANSFORM_KINDS)[number];
export const WINDOW_AGGREGATES = ["sum", "avg", "min", "max", "count", "stddev"] as const;
export type WindowAggregate = (typeof WINDOW_AGGREGATES)[number];
export const TIME_UNITS = ["second", "minute", "hour", "day", "week"] as const;
export type TimeUnit = (typeof TIME_UNITS)[number];
export const MAX_TRANSFORMS = 10;
export const MAX_SPAN = 100_000;

export type SeriesTransform =
  | { kind: "cumulative"; aggregate: WindowAggregate }
  | { kind: "rolling"; aggregate: WindowAggregate; window: number; unit: TimeUnit }
  | { kind: "derivative"; unit: TimeUnit }
  | { kind: "shift"; by: number; unit: TimeUnit }
  | { kind: "range"; start: string | null; end: string | null };

/** What the editor offers each kind as. */
export const KIND_LABELS: Record<TransformKind, string> = {
  cumulative: "Cumulative",
  rolling: "Rolling window",
  derivative: "Rate of change",
  shift: "Time shift",
  range: "Time range",
};

/** A new transform of `kind`, ready to use: p.584's own examples where it
 * gives one (a running sum; a standard deviation over three days). */
export function blankTransform(kind: TransformKind): SeriesTransform {
  switch (kind) {
    case "cumulative":
      return { kind, aggregate: "sum" };
    case "rolling":
      return { kind, aggregate: "stddev", window: 3, unit: "day" };
    case "derivative":
      return { kind, unit: "day" };
    case "shift":
      return { kind, by: 1, unit: "day" };
    case "range":
      return { kind, start: null, end: null };
  }
}

const AGGREGATE_WORDS: Record<WindowAggregate, string> = {
  sum: "sum", avg: "average", min: "minimum", max: "maximum", count: "count",
  stddev: "standard deviation",
};

function units(n: number, unit: TimeUnit): string {
  return `${n} ${unit}${n === 1 ? "" : "s"}`;
}

/** One transform in words, for the chart's caption and the editor's list. */
export function transformText(t: SeriesTransform): string {
  switch (t.kind) {
    case "cumulative":
      return `running ${AGGREGATE_WORDS[t.aggregate]}`;
    case "rolling":
      return `${AGGREGATE_WORDS[t.aggregate]} over the last ${units(t.window, t.unit)}`;
    case "derivative":
      return `change per ${t.unit}`;
    case "shift":
      return `shifted ${units(Math.abs(t.by), t.unit)} ${t.by > 0 ? "later" : "earlier"}`;
    case "range":
      if (t.start && t.end) return `from ${t.start} to ${t.end}`;
      return t.start ? `from ${t.start}` : `until ${t.end}`;
  }
}

/** The chain in words, in order; "" when there is none. */
export function transformsText(transforms: SeriesTransform[] | undefined): string {
  return (transforms ?? []).map(transformText).join(", then ");
}

function whole(n: number): boolean {
  return Number.isInteger(n);
}

/** What is wrong with one transform, or null. */
export function transformProblem(t: SeriesTransform): string | null {
  switch (t.kind) {
    case "rolling":
      return whole(t.window) && t.window >= 1 && t.window <= MAX_SPAN
        ? null : `The window must be a whole number from 1 to ${MAX_SPAN.toLocaleString("en-US")}.`;
    case "shift":
      return whole(t.by) && t.by !== 0 && Math.abs(t.by) <= MAX_SPAN
        ? null
        : `The shift must be a whole number, not zero, and at most ${MAX_SPAN.toLocaleString("en-US")} either way.`;
    case "range":
      if (!t.start && !t.end) return "A time range needs a start, an end or both.";
      if (t.start && t.end && t.start > t.end) return "The time range starts after it ends.";
      return null;
    default:
      return null;
  }
}

/** The first problem in the chain, named by its place in it. */
export function transformsProblem(transforms: SeriesTransform[]): string | null {
  if (transforms.length > MAX_TRANSFORMS) return `A series takes at most ${MAX_TRANSFORMS} transforms.`;
  for (const [index, t] of transforms.entries()) {
    const problem = transformProblem(t);
    if (problem) return `Transform ${index + 1}: ${problem}`;
  }
  return null;
}

/** A transform's kind changed: a fresh one of the new kind, since the fields
 * of one kind mean nothing to another. */
export function withKind(t: SeriesTransform, kind: TransformKind): SeriesTransform {
  return t.kind === kind ? t : blankTransform(kind);
}
