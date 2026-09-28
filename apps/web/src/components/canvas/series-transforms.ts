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

export const TRANSFORM_KINDS = ["cumulative", "periodic", "rolling", "derivative", "integral", "shift", "range", "formula", "filter", "sample"] as const;
export type TransformKind = (typeof TRANSFORM_KINDS)[number];
export const WINDOW_AGGREGATES = ["sum", "avg", "min", "max", "count", "stddev"] as const;
export type WindowAggregate = (typeof WINDOW_AGGREGATES)[number];
export const TIME_UNITS = ["second", "minute", "hour", "day", "week"] as const;
export type TimeUnit = (typeof TIME_UNITS)[number];
export const MAX_TRANSFORMS = 10;
/** p.584's periodic window types. */
export const WINDOW_TYPES = ["start", "end"] as const;
export type WindowType = (typeof WINDOW_TYPES)[number];
/** p.585's integration methods. */
export const INTEGRATION_METHODS = ["linear", "left", "right"] as const;
export type IntegrationMethod = (typeof INTEGRATION_METHODS)[number];
/** p.586's formula (§532): arithmetic on the series, named `x`. The server
 * parses it; these are what the editor says it may use. */
export const FORMULA_FUNCTIONS = ["abs", "sqrt", "ln", "log10", "exp", "floor", "ceil", "round"] as const;
export const MAX_FORMULA = 200;
/** p.586's **Add input** (§561): "users can add new input time series …
 * and then build formulas using variable references to these inputs". Each
 * is a time series set variable, named in the formula; the server's caps. */
export const MAX_FORMULA_INPUTS = 4;
/** p.393's *Filter time series* (§648): each reading compared with a number,
 * and the points that match kept or removed. */
export const FILTER_OPERATORS = ["gt", "gte", "lt", "lte", "eq", "neq"] as const;
export type FilterOperator = (typeof FILTER_OPERATORS)[number];
export const FILTER_WORDS: Record<FilterOperator, string> = {
  gt: "above", gte: "at least", lt: "below", lte: "at most", eq: "equal to", neq: "not equal to",
};
/** p.393's *Sample* (§648): the reading at or before each step, or the line
 * between the readings either side. */
export const SAMPLE_METHODS = ["previous", "linear"] as const;
export type SampleMethod = (typeof SAMPLE_METHODS)[number];
/** The names offered, in order: the series itself is `x`. */
const INPUT_NAMES = "yzabcdefghijklmnopqrstuvw".split("");
export const MAX_SPAN = 100_000;

export type SeriesTransform =
  | { kind: "cumulative"; aggregate: WindowAggregate }
  | { kind: "periodic"; aggregate: WindowAggregate; window: number; unit: TimeUnit;
      /** Null lines the windows up on 1970, as the server does. */
      align: string | null; window_type: WindowType }
  | { kind: "rolling"; aggregate: WindowAggregate; window: number; unit: TimeUnit }
  | { kind: "derivative"; unit: TimeUnit }
  | { kind: "integral"; unit: TimeUnit; method: IntegrationMethod }
  | { kind: "shift"; by: number; unit: TimeUnit }
  | { kind: "range"; start: string | null; end: string | null }
  | { kind: "filter"; op: FilterOperator; value: number; keep: boolean }
  | { kind: "sample"; every: number; unit: TimeUnit; method: SampleMethod }
  | { kind: "formula"; expression: string;
      /** §561: the other inputs by name - a variable's id where the variable
       * is edited, and that variable resolved where a widget reads it. */
      inputs?: Record<string, unknown> };

/** What the editor offers each kind as. */
export const KIND_LABELS: Record<TransformKind, string> = {
  cumulative: "Cumulative",
  periodic: "Periodic",
  rolling: "Rolling window",
  derivative: "Rate of change",
  integral: "Integral",
  shift: "Time shift",
  range: "Time range",
  formula: "Formula",
  filter: "Filter",
  sample: "Sample",
};

/** A new transform of `kind`, ready to use: p.584's own examples where it
 * gives one (a running sum; a standard deviation over three days). */
export function blankTransform(kind: TransformKind): SeriesTransform {
  switch (kind) {
    case "cumulative":
      return { kind, aggregate: "sum" };
    case "periodic":
      // p.584's example: "the average input values in the sequence of two
      // week windows".
      return { kind, aggregate: "avg", window: 2, unit: "week", align: null, window_type: "start" };
    case "rolling":
      return { kind, aggregate: "stddev", window: 3, unit: "day" };
    case "derivative":
      return { kind, unit: "day" };
    case "integral":
      // p.585's example: power integrated per hour is kilowatt-hours.
      return { kind, unit: "hour", method: "linear" };
    case "shift":
      return { kind, by: 1, unit: "day" };
    case "range":
      return { kind, start: null, end: null };
    case "formula":
      // p.586's own example: "scales the input time series by a factor of
      // two, and adds five to the result".
      return { kind, expression: "x * 2 + 5" };
    case "filter":
      return { kind, op: "gt", value: 0, keep: true };
    case "sample":
      return { kind, every: 1, unit: "hour", method: "previous" };
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
    case "periodic":
      return `${AGGREGATE_WORDS[t.aggregate]} per ${units(t.window, t.unit)}` +
        (t.window_type === "end" ? ", stamped at each window's end" : "") +
        (t.align ? `, aligned to ${t.align}` : "");
    case "rolling":
      return `${AGGREGATE_WORDS[t.aggregate]} over the last ${units(t.window, t.unit)}`;
    case "derivative":
      return `change per ${t.unit}`;
    case "integral":
      return `area in ${t.unit}s${t.method === "linear" ? "" : ` (${t.method}-hand sum)`}`;
    case "shift":
      return `shifted ${units(Math.abs(t.by), t.unit)} ${t.by > 0 ? "later" : "earlier"}`;
    case "range":
      if (t.start && t.end) return `from ${t.start} to ${t.end}`;
      return t.start ? `from ${t.start}` : `until ${t.end}`;
    case "formula":
      return `${["x", ...Object.keys(t.inputs ?? {})].join(", ")} → ${t.expression.trim()}`;
    case "filter":
      return `${t.keep ? "only" : "without"} readings ${FILTER_WORDS[t.op]} ${t.value}`;
    case "sample":
      return `sampled every ${units(t.every, t.unit)}${t.method === "linear" ? ", interpolated" : ""}`;
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
    case "periodic":
    case "rolling":
      return whole(t.window) && t.window >= 1 && t.window <= MAX_SPAN
        ? null : `The window must be a whole number from 1 to ${MAX_SPAN.toLocaleString("en-US")}.`;
    case "sample":
      return whole(t.every) && t.every >= 1 && t.every <= MAX_SPAN
        ? null : `The step must be a whole number from 1 to ${MAX_SPAN.toLocaleString("en-US")}.`;
    case "filter":
      return Number.isFinite(t.value) ? null : "A filter compares with a number.";
    case "shift":
      return whole(t.by) && t.by !== 0 && Math.abs(t.by) <= MAX_SPAN
        ? null
        : `The shift must be a whole number, not zero, and at most ${MAX_SPAN.toLocaleString("en-US")} either way.`;
    case "formula":
      if (t.expression.trim() === "") return "A formula needs an expression.";
      if (t.expression.length > MAX_FORMULA) return `A formula is at most ${MAX_FORMULA} characters.`;
      for (const [name, chosen] of Object.entries(t.inputs ?? {})) {
        if (!chosen) return `Choose a series for ${name}.`;
      }
      return null;
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

/** A formula with one more input (§561), under the first name it does not
 * use yet, with no series chosen. */
export function withInput(t: Extract<SeriesTransform, { kind: "formula" }>): SeriesTransform {
  const inputs = t.inputs ?? {};
  const name = INPUT_NAMES.find((n) => !(n in inputs));
  if (!name || Object.keys(inputs).length >= MAX_FORMULA_INPUTS) return t;
  return { ...t, inputs: { ...inputs, [name]: "" } };
}

/** A formula without one of its inputs; none left is no `inputs` at all, so
 * a one-series formula reads as it always has. */
export function withoutInput(
  t: Extract<SeriesTransform, { kind: "formula" }>, name: string,
): SeriesTransform {
  const { [name]: _dropped, ...rest } = t.inputs ?? {};
  const { inputs: _all, ...plain } = t;
  return Object.keys(rest).length ? { ...plain, inputs: rest } : plain;
}

/** The series variables a chain's formulas name, in the order first named -
 * the server's `series_inputs`, which the derivation's inputs must match. */
export function seriesInputs(transforms: SeriesTransform[]): string[] {
  const out: string[] = [];
  for (const t of transforms) {
    if (t.kind !== "formula") continue;
    for (const chosen of Object.values(t.inputs ?? {})) {
      if (typeof chosen === "string" && chosen && !out.includes(chosen)) out.push(chosen);
    }
  }
  return out;
}

/** A series variable's derivation inputs: the object, then each series its
 * formulas name (§561). Nothing at all while there is neither. */
export function seriesDerivationInputs(object: string, transforms: SeriesTransform[]): string[] {
  const named = seriesInputs(transforms);
  return object || named.length ? [object, ...named] : [];
}

/** A transform's kind changed: a fresh one of the new kind, since the fields
 * of one kind mean nothing to another. */
export function withKind(t: SeriesTransform, kind: TransformKind): SeriesTransform {
  return t.kind === kind ? t : blankTransform(kind);
}

/** An Object Table's transforms, by time series column (§555; p.583's table
 * with "different time series transforms … applied"). Read defensively: a
 * stored prop is whatever a document holds, and a column's chain that is not
 * a list is no chain. */
export function transformsByColumn(raw: unknown): Record<string, SeriesTransform[]> {
  // An array is an object too, and its entries are never chains (a check for
  // it survived the sweep as equivalent): each index holds a transform.
  if (!raw || typeof raw !== "object") return {};
  return Object.fromEntries(
    Object.entries(raw as Record<string, unknown>)
      .filter((entry): entry is [string, SeriesTransform[]] =>
        Array.isArray(entry[1]) && entry[1].length > 0),
  );
}

/** The chain the column is read through: none while it has a problem, so a
 * half-edited transform leaves the column drawing its plain series rather
 * than an error the panel is already naming. */
export function readableTransforms(raw: unknown, column: string): SeriesTransform[] {
  const chain = transformsByColumn(raw)[column] ?? [];
  return transformsProblem(chain) ? [] : chain;
}

/** The map with one column's chain replaced, or dropped when emptied - so
 * "has this column got transforms" has one answer, as for its formats. */
export function withColumnTransforms(
  raw: unknown, column: string, chain: SeriesTransform[],
): Record<string, SeriesTransform[]> | null {
  const next = { ...transformsByColumn(raw) };
  if (chain.length) next[column] = chain;
  else delete next[column];
  return Object.keys(next).length ? next : null;
}
