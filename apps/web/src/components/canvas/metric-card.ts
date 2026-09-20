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
