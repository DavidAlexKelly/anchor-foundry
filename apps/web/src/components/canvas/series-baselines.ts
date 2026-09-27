/** p.592-593's baselines on the Object Table's time series columns (§563).
 *
 * > "A baseline is an additional time series line, rendered in combination
 * > with a sparkline in a visually distinguishing way (e.g. as a dotted
 * > line). … Baselines can be configured in the Object Table and Metric Card
 * > widgets. There are three types of baseline: Static, Numeric property, and
 * > Time series property." (p.592)
 *
 * > "The Numeric property type means that the user can specify a numeric
 * > property of the object type feeding the widget, whose value for each
 * > object is used as the baseline for the corresponding series. … The Time
 * > series type means that the user can configure a time series summarizer
 * > to generate a unique baseline value for every series." (p.593)
 *
 * Held per column, as §555's transforms are, and read defensively: a stored
 * prop is whatever a document holds. The line is `Sparkline`'s, already the
 * Metric Card's (§526). Pure.
 */

import { summarise } from "./metric-card";

export type ColumnBaseline =
  | { kind: "static"; value: number }
  | { kind: "property"; property: string }
  | { kind: "series"; summary: string };

/** What the panel offers each kind as, p.592's three and none. */
export const COLUMN_BASELINE_KINDS: Record<string, string> = {
  none: "No baseline",
  static: "Static",
  property: "Numeric property",
  series: "From the series",
};

/** One column's baseline, or null for none - or for one that says too little
 * to draw, so a half-configured setting draws nothing rather than a line at
 * a value nobody chose. */
export function columnBaselineOf(raw: unknown): ColumnBaseline | null {
  if (!raw || typeof raw !== "object") return null;
  const b = raw as Record<string, unknown>;
  if (b.kind === "static" && typeof b.value === "number" && Number.isFinite(b.value)) {
    return { kind: "static", value: b.value };
  }
  if (b.kind === "property" && typeof b.property === "string" && b.property) {
    return { kind: "property", property: b.property };
  }
  if (b.kind === "series") {
    return { kind: "series", summary: typeof b.summary === "string" ? b.summary : "last" };
  }
  return null;
}

/** Every column's baseline, by column. */
export function baselinesByColumn(raw: unknown): Record<string, ColumnBaseline> {
  // No object check: a string's or a number's entries are never baselines
  // (one survived the sweep as equivalent).
  if (!raw) return {};
  const out: Record<string, ColumnBaseline> = {};
  for (const [column, value] of Object.entries(raw as Record<string, unknown>)) {
    const baseline = columnBaselineOf(value);
    if (baseline) out[column] = baseline;
  }
  return out;
}

/** The map with one column's baseline replaced, or dropped when it is none;
 * no baselines at all is null, as for the column's transforms. */
export function withColumnBaseline(
  raw: unknown, column: string, baseline: ColumnBaseline | null,
): Record<string, ColumnBaseline> | null {
  const next = { ...baselinesByColumn(raw) };
  if (baseline) next[column] = baseline;
  else delete next[column];
  return Object.keys(next).length ? next : null;
}

/** A row's baseline: the static value, the row's own numeric property, or its
 * series summarised as p.593's summarizer says. Null draws no line - a row
 * whose property is empty has no baseline, not one at zero. */
export function baselineFor(
  baseline: ColumnBaseline | null | undefined,
  properties: Record<string, unknown>,
  values: readonly number[],
): number | null {
  if (!baseline) return null;
  if (baseline.kind === "static") return baseline.value;
  if (baseline.kind === "series") return summarise(values, baseline.summary);
  const raw = properties[baseline.property];
  if (raw === null || raw === undefined || raw === "") return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}
