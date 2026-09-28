/** p.325-330's Metric Card: "displays Workshop variable values in a
 * configurable card-like interface… used to highlight key figures".
 *
 * ---
 *
 * **A divergence worth stating before the rules, because it shapes all of
 * them.** p.328 says the value "must be backed by a Workshop variable of the
 * corresponding type" — the card *reads* a number and something else computes
 * it. This platform's card computes its own, by asking `/object-sets/aggregate`
 * directly.
 *
 * The variable-backed shape is the better one and this platform half has it:
 * `object_set_aggregation` is a declared transform in `workshop_variables.py`
 * and is refused on save — "not built yet: it reads the ontology, so it needs a
 * server round trip rather than a local computation". That refusal is now the
 * only thing in the way, and §226 is what removed its reason. Until it is
 * built, one number needs one widget, and every other consumer of an aggregate
 * — a Markdown heading, a chart title, an action's default — has nowhere to
 * read one from. **Named here rather than fixed in passing**, because moving
 * the aggregation onto the variable is a change to the resolver's shape, not to
 * this widget.
 */

import { showNumber, type NumberFormat } from "./value-formats";

/** What a card can show, matching `object_sets.AGGREGATIONS` and
 * `NUMERIC_AGGREGATIONS` between them.
 *
 * The four numeric ones were refused until §226, and the card's own hint said
 * so: "sums and averages need typed properties — see the ontology roadmap".
 * True when written, and untrue from §220 — the same stale refusal §228 found
 * on the Pie Chart's panel, in a second widget. Two of them within one file is
 * what makes it a pattern rather than an oversight: a control that explains why
 * it cannot work is a claim with a date on it.
 */
export const AGGREGATIONS: Record<string, string> = {
  count: "How many",
  count_distinct: "How many distinct values",
  sum: "Sum of",
  avg: "Average of",
  min: "Minimum of",
  max: "Maximum of",
};

export const DEFAULT_AGGREGATION = "count";

export function aggregationOf(raw: unknown): string {
  return typeof raw === "string" && Object.hasOwn(AGGREGATIONS, raw)
    ? raw
    : DEFAULT_AGGREGATION;
}

/** The four that are arithmetic on a value, rather than counting things. */
export const NUMERIC_AGGREGATIONS = ["sum", "avg", "min", "max"] as const;

/** Whether an aggregation needs a property to run over.
 *
 * `count` is the only one that does not: `count_distinct` counts the distinct
 * values *of* a property, and the four numeric ones compute over one.
 */
export function needsProperty(aggregation: unknown): boolean {
  return aggregationOf(aggregation) !== "count";
}

/** Which of an object type's properties an aggregation may run over.
 *
 * **Two different lists, and the difference is the whole reason this is a
 * function.** `count_distinct` is a text-identity question, so it works on any
 * property whatever its declared type; the numeric four are arithmetic and the
 * server refuses anything but an integer or a float
 * (`object_sets.AGGREGATABLE_TYPES`). A picker offering every property to a
 * `sum` would produce a sentence about arithmetic in place of a number.
 */
export function propertiesFor<T extends { data_type?: string }>(
  aggregation: unknown, properties: readonly T[],
): T[] {
  if (!(NUMERIC_AGGREGATIONS as readonly string[]).includes(aggregationOf(aggregation))) {
    return [...properties];
  }
  return properties.filter(
    (p) => p.data_type === "integer" || p.data_type === "float",
  );
}

/** What to ask the server for, or `null` while the setting is unfinished.
 *
 * §223's rule, and §228's: the widget reads its own configuration before
 * sending it. An aggregation with no property yet is a panel somebody is
 * halfway through, and the server answers it with a sentence about property
 * types — which, shown to a viewer, reports an author's unfinished setting as a
 * failure of the data.
 */
export function metricRequest(aggregation: unknown, property: unknown): {
  aggregation: string; property?: string;
} | null {
  const name = aggregationOf(aggregation);
  const over = typeof property === "string" ? property.trim() : "";
  if (!needsProperty(name)) return { aggregation: name };
  return over ? { aggregation: name, property: over } : null;
}

/** What a card shows for the number it was given.
 *
 * **`null` is not zero, and this is the widget where that matters most.** §226
 * made an aggregation over an empty set answer `null` rather than `0`, because
 * "total capacity: 0" and "there are no sites" are different facts that render
 * identically — and a Metric Card is a single large number somebody reads at a
 * glance and believes. So the card says there is nothing rather than showing a
 * figure nobody can check.
 *
 * The number is localised, which is what makes a count of 1200 readable; the
 * empty answer is a dash, which is the typographic convention for "no value"
 * and cannot be mistaken for one.
 */
export const NO_VALUE = "—";

/**
 * `format` is p.328's **Numeric formatting**, which is the module-local
 * formatter p.174 describes rather than an ontology one — the number here was
 * computed by this widget, so there is no property to inherit from.
 *
 * **It applies to the figure and not to the dash.** p.328 calls it a scheme
 * "to display the numeric value"; there is no numeric value to display when
 * the aggregation answered nothing, and a formatter that turned the empty
 * answer into `$0.00` would be §226's whole point undone by a display option.
 */
export function valueLabel(
  value: unknown,
  format: NumberFormat | null = null,
): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return NO_VALUE;
  return showNumber(value, format);
}

// ---- p.329's "Show visualization?" -----------------------------------------

/** Where the sparkline sits relative to the number (p.329's Position).
 *
 * > "Position: Specifies whether the sparkline should be displayed
 * > Side-by-side (alongside) or Stacked (under) with the metric value."
 *
 * Foundry's two words, and the values are its words rather than `row`/`column`
 * so a stored document reads as the setting a builder chose.
 */
export const SPARK_POSITIONS: Record<string, string> = {
  side_by_side: "Side-by-side",
  stacked: "Stacked",
};

export const DEFAULT_SPARK_POSITION = "side_by_side";

export function sparkPositionOf(raw: unknown): string {
  const value = String(raw ?? "");
  return value in SPARK_POSITIONS ? value : DEFAULT_SPARK_POSITION;
}

/**
 * Whether the card should draw a sparkline at all.
 *
 * **Both halves, because either alone is a half-configured card.** p.329 opens
 * the configuration on a toggle and the configuration names a variable; a
 * toggle switched on with no variable has nothing to draw, and a variable
 * chosen with the toggle off is a decision somebody reversed. Drawing on the
 * toggle alone would leave an empty box under the number with no way to tell
 * whether it was broken or unfinished.
 */
export function showsSpark(show: unknown, seriesVariable: unknown): boolean {
  return show === true && typeof seriesVariable === "string" && seriesVariable !== "";
}

/** What the card says when the toggle is on and nothing is chosen yet.
 *
 * In edit mode only - a builder needs to be told what is missing, and a
 * reader would only see an unexplained gap where a chart was promised. */
export function sparkEmptyReason(show: unknown, seriesVariable: unknown): string | null {
  if (show !== true) return null;
  if (typeof seriesVariable === "string" && seriesVariable !== "") return null;
  return "Pick a time series set variable to draw";
}

// ---- §526: p.326's size, p.328's description, p.330's time range and baseline ----
/** p.326: "Sets the display size for every metric in the widget. The options
 * here are Compact, Regular, and Large." Foundry's words as the labels, and
 * the stored values lower-case like the positions'. */
export const METRIC_SIZES: Record<string, string> = {
  compact: "Compact",
  regular: "Regular",
  large: "Large",
};
export const DEFAULT_METRIC_SIZE = "regular";

export function metricSizeOf(raw: unknown): string {
  const value = String(raw ?? "");
  return value in METRIC_SIZES ? value : DEFAULT_METRIC_SIZE;
}

/** p.328's description: "displayed as a tooltip when a user hovers over the
 * i tooltip". Blank is none, so an emptied box leaves no marker behind. */
export function descriptionOf(raw: unknown): string | null {
  const text = typeof raw === "string" ? raw.trim() : "";
  return text === "" ? null : text;
}

/** p.330's sparkline time range: "Preset options include All time, Last hour,
 * Last day, and Last week, but selecting Custom range opens a detailed range
 * selector". The exact half of the custom range is built; p.591's relative
 * half is not. */
export const SPARK_RANGES: Record<string, string> = {
  all: "All time",
  hour: "Last hour",
  day: "Last day",
  week: "Last week",
  custom: "Custom range",
  relative: "Relative range",
};

/** p.591: "The window size can be specified in terms of milliseconds,
 * seconds, minutes, hours, days, and weeks." */
export const RELATIVE_UNITS: Record<string, number> = {
  millisecond: 1, second: 1_000, minute: 60_000, hour: 3_600_000, day: 86_400_000,
  week: 604_800_000,
};

/** A relative bound: so many units before or after now. Null when it is not
 * a count of a known unit, which is an open end. */
export function relativeMs(amount: unknown, unit: unknown): number | null {
  if (typeof unit !== "string" || !(unit in RELATIVE_UNITS)) return null;
  const n = typeof amount === "number" ? amount : typeof amount === "string" && amount !== "" ? Number(amount) : NaN;
  return Number.isFinite(n) && n >= 0 ? n * (RELATIVE_UNITS[unit] ?? 0) : null;
}
export const DEFAULT_SPARK_RANGE = "all";

export function sparkRangeOf(raw: unknown): string {
  const value = String(raw ?? "");
  return value in SPARK_RANGES ? value : DEFAULT_SPARK_RANGE;
}

const RANGE_MS: Record<string, number> = { hour: 3_600_000, day: 86_400_000, week: 604_800_000 };

/** A timestamp as the series stores it: UTC, to the second, no zone. */
function utc(ms: number): string {
  return new Date(ms).toISOString().slice(0, 19);
}

/** The time range as a `range` transform appended to the series' own, or
 * null when it asks for everything. `now` is when the page first needed it
 * (p.591: "the current time is computed when it is first needed … It then
 * stays constant unless the web page is reloaded"). A custom range with
 * neither end is everything too, rather than a transform the server refuses. */
export function sparkRangeTransform(
  range: unknown, start: unknown, end: unknown, now: number,
  relative: { ago?: unknown; agoUnit?: unknown; ahead?: unknown; aheadUnit?: unknown } = {},
): { kind: "range"; start: string | null; end: string | null } | null {
  const which = sparkRangeOf(range);
  if (which in RANGE_MS) return { kind: "range", start: utc(now - (RANGE_MS[which] ?? 0)), end: null };
  if (which === "relative") {
    // p.591: "a relative start of '2 weeks ago' … a relative end of '1 week
    // from now'", counted from the page's fixed now.
    const ago = relativeMs(relative.ago, relative.agoUnit);
    const ahead = relativeMs(relative.ahead, relative.aheadUnit);
    if (ago === null && ahead === null) return null;
    return { kind: "range", start: ago === null ? null : utc(now - ago),
             end: ahead === null ? null : utc(now + ahead) };
  }
  if (which !== "custom") return null;
  const from = typeof start === "string" && start !== "" ? start : null;
  const to = typeof end === "string" && end !== "" ? end : null;
  return from || to ? { kind: "range", start: from, end: to } : null;
}

/** What is wrong with a custom range, or null. */
export function sparkRangeProblem(range: unknown, start: unknown, end: unknown): string | null {
  if (sparkRangeOf(range) !== "custom") return null;
  if (typeof start === "string" && typeof end === "string" && start !== "" && end !== "" && start > end) {
    return "The range starts after it ends.";
  }
  return null;
}

let firstNeeded: number | null = null;

/** p.591's "current time", fixed at the first ask for the life of the page, so
 * two cards with "Last day" agree about when the day began. */
export function pageNow(clock: () => number = Date.now): number {
  if (firstNeeded === null) firstNeeded = clock();
  return firstNeeded;
}

/** For tests: forget the fixed time, as a reload would. */
export function resetPageNow(): void {
  firstNeeded = null;
}

/** p.592's Static baseline: "the value of the baseline for every time series
 * is a static user-specified value". A finite number, or none. */
export function baselineOf(raw: unknown): number | null {
  if (raw === null || raw === undefined || raw === "") return null;
  const value = typeof raw === "number" ? raw : Number(raw);
  return Number.isFinite(value) ? value : null;
}

// ---- §528: p.329's secondary metric ------------------------------------------------
/** p.329: "Show secondary metric? An optional configuration to display a
 * second metric within the same metric display, under the primary metric.
 * Setting this toggle to Yes opens a value type configuration for the
 * secondary metric, which mimics the configuration for the primary metric."
 *
 * The same set, a second aggregation of it: what the primary's configuration
 * is here (an aggregation, its property, its label and its formatting). Its
 * label defaults to what it computes, since a bare second number beside the
 * first says nothing about which is which. */
export function secondaryLabelOf(label: unknown, aggregation: unknown): string {
  const text = typeof label === "string" ? label.trim() : "";
  return text !== "" ? text : (AGGREGATIONS[aggregationOf(aggregation)] ?? "");
}

// ---- §533: p.325-326's groups of metrics and their layout -------------------------
/** p.325: "Display groups of metrics together" and "Style the layout of
 * metrics, so they are displayed as Cards, Tags, or in a List." */
export const LAYOUT_STYLES: Record<string, string> = { card: "Card", tag: "Tag", list: "List" };
export const DIRECTIONS: Record<string, string> = { horizontal: "Horizontal", vertical: "Vertical" };
/** p.326's templates, "used to arrange data in every card". */
export const TEMPLATES: Record<string, string> = { stacked: "Stacked", side_by_side: "Side-by-side" };

function oneOf(options: Record<string, string>, raw: unknown, fallback: string): string {
  const value = String(raw ?? "");
  return value in options ? value : fallback;
}

export const layoutStyleOf = (raw: unknown): string => oneOf(LAYOUT_STYLES, raw, "card");
export const directionOf = (raw: unknown): string => oneOf(DIRECTIONS, raw, "horizontal");
export const templateOf = (raw: unknown): string => oneOf(TEMPLATES, raw, "stacked");

/** Which of p.326's two arrangement settings a style has: "The Card layout
 * style also lets the user choose the Direction … [and the] Template"; "The
 * Tag layout style lets the user choose the Direction"; "The List layout
 * style lets the user choose the Template". */
export function layoutSettings(style: unknown): { direction: boolean; template: boolean } {
  const which = layoutStyleOf(style);
  return { direction: which !== "list", template: which !== "tag" };
}

/** p.326: "Note that time series visualizations are only supported in this
 * layout style" (Card). */
export function sparkAllowedIn(style: unknown): boolean {
  return layoutStyleOf(style) === "card";
}

/** One metric after the first: a label, an aggregation of the card's set and
 * its property, and formatting, as p.327-328 configure each metric. */
export interface ExtraMetric {
  id: string;
  label: string;
  aggregation: string;
  property: string | null;
  valueFormat: unknown;
}

/** The stored list, read through: anything that is not a metric is dropped,
 * and a repeated id keeps its first. */
export function extraMetricsOf(raw: unknown): ExtraMetric[] {
  if (!Array.isArray(raw)) return [];
  const seen = new Set<string>();
  const out: ExtraMetric[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const it = item as Record<string, unknown>;
    if (typeof it.id !== "string" || it.id === "" || seen.has(it.id)) continue;
    seen.add(it.id);
    out.push({
      id: it.id,
      label: typeof it.label === "string" ? it.label : "",
      aggregation: aggregationOf(it.aggregation),
      property: typeof it.property === "string" && it.property !== "" ? it.property : null,
      valueFormat: it.valueFormat ?? null,
    });
  }
  return out;
}

/** p.325's Add Metric: a count, with an id the list does not have yet. */
export function addMetric(list: readonly ExtraMetric[]): ExtraMetric[] {
  const taken = new Set(list.map((m) => m.id));
  let n = list.length + 2;
  while (taken.has(`m${n}`)) n += 1;
  return [...list, { id: `m${n}`, label: "", aggregation: "count", property: null, valueFormat: null }];
}

/** p.325's Up and Down arrows. A move past either end is no move. */
export function moveMetric(list: readonly ExtraMetric[], index: number, by: -1 | 1): ExtraMetric[] {
  const to = index + by;
  if (index < 0 || index >= list.length || to < 0 || to >= list.length) return [...list];
  const next = [...list];
  const [moved] = next.splice(index, 1);
  next.splice(to, 0, moved as ExtraMetric);
  return next;
}

/** A metric's label, or what it computes when it has none, the secondary
 * metric's rule. */
export function metricLabelOf(metric: Pick<ExtraMetric, "label" | "aggregation">): string {
  return secondaryLabelOf(metric.label, metric.aggregation);
}

// ---- §534: p.592's time-series baseline ----------------------------------------------
/** p.592's baseline types. Static is §526's; Time series is "a time series
 * summarizer to generate a unique baseline value for every series … the
 * value of the most recent observation". Numeric property needs the object's
 * own properties, which the card does not read. */
export const BASELINE_KINDS: Record<string, string> = {
  none: "No baseline", static: "Static", series: "From the series",
};
/** p.586's summarizers a line can be read by. */
export const BASELINE_SUMMARIES: Record<string, string> = {
  last: "Last", first: "First", avg: "Average", min: "Min", max: "Max",
};

/** Which baseline a card has. A card from before §534 has a number and no
 * kind, which is a static one. */
export function baselineKindOf(kind: unknown, value: unknown): string {
  if (typeof kind === "string" && kind in BASELINE_KINDS) return kind;
  return baselineOf(value) === null ? "none" : "static";
}

/** The series summarised for its baseline, over the points drawn; null when
 * there are none. */
export function summarise(values: readonly number[], how: unknown): number | null {
  const finite = values.filter((v) => Number.isFinite(v));
  if (finite.length === 0) return null;
  switch (how) {
    case "first": return finite[0] ?? null;
    case "avg": return finite.reduce((a, b) => a + b, 0) / finite.length;
    case "min": return Math.min(...finite);
    case "max": return Math.max(...finite);
    default: return finite[finite.length - 1] ?? null;
  }
}
