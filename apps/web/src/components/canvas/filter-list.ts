/**
 * p.449's Filter component: how each property of a Filter List is drawn, and
 * the clauses each one reads and writes (`workshop` p.446–449; §463).
 *
 * > "Filter component: This option determines how each property is visualized
 * > within the Filter List. Options include keyword, histogram, single- and
 * > multi-select dropdowns, distribution chart, single- and multi-date pickers,
 * > and timeline displays." (p.449)
 *
 * **Every component writes into the one list of clauses** the widget's output
 * variable holds, and each owns only the operators it writes on its own
 * property. So a keyword on `region` and a histogram on `region` do not undo
 * each other, and a clause somebody else wrote (a default, p.449's "setting a
 * default value for this variable") is left where it is rather than dropped by
 * the next click. The widget used to rebuild the whole list from its
 * checkboxes, which threw away every clause it had not drawn.
 *
 * What a clause is, and reading one, is `filter-clause.ts`'s: nothing outside
 * that file writes the operator list.
 */

import { ORDERED_OPERATORS, type Clause } from "./filter-clause";

export type { Clause };

export const FILTER_COMPONENTS = [
  "histogram", "singleSelect", "multiSelect", "keyword", "dateRange",
] as const;
export type FilterComponent = (typeof FILTER_COMPONENTS)[number];

export const FILTER_COMPONENT_LABELS: Record<FilterComponent, string> = {
  histogram: "Histogram",
  singleSelect: "Single-select dropdown",
  multiSelect: "Multi-select dropdown",
  keyword: "Keyword",
  dateRange: "Date range",
};

/** p.449's date pickers are for dates; offering one on a string would write a
 * range the server refuses, because only declared dates and numbers order. */
export const DATE_TYPES = ["date", "timestamp"] as const;

export interface FilterSpec {
  id: string;
  property: string;
  component: FilterComponent;
}

export function componentOf(value: unknown): FilterComponent {
  return (FILTER_COMPONENTS as readonly unknown[]).includes(value)
    ? (value as FilterComponent) : "histogram";
}

/** The components a property of this declared type can be drawn as. */
export function componentsFor(dataType: string | null | undefined): FilterComponent[] {
  const dated = (DATE_TYPES as readonly (string | null | undefined)[]).includes(dataType);
  return FILTER_COMPONENTS.filter((c) => c !== "dateRange" || dated);
}

/**
 * The filters a document holds. A Filter List saved before §463 has only a
 * comma-separated `properties`, and each of those becomes a histogram: the
 * checkbox list it drew was a histogram without the bars, so it keeps both
 * its properties and what clicking one does.
 */
export function filtersOf(filters: unknown, legacy: unknown): FilterSpec[] {
  if (Array.isArray(filters)) {
    return filters
      .filter((f): f is Record<string, unknown> =>
        !!f && typeof f === "object"
        && typeof (f as FilterSpec).id === "string" && !!(f as FilterSpec).id
        && typeof (f as FilterSpec).property === "string" && !!(f as FilterSpec).property)
      .map((f) => ({
        id: f.id as string, property: f.property as string, component: componentOf(f.component),
      }));
  }
  return String(legacy ?? "")
    .split(",")
    .map((p) => p.trim())
    .filter(Boolean)
    .map((property, i) => ({ id: `f_${i + 1}`, property, component: "histogram" as const }));
}

/** The first `f_N` no filter has. */
export function newFilterId(filters: readonly FilterSpec[]): string {
  const taken = new Set(filters.map((f) => f.id));
  let n = filters.length + 1;
  while (taken.has(`f_${n}`)) n += 1;
  return `f_${n}`;
}

/** The values chosen on a property: its `eq` or its `in`. */
export function valuesOf(clauses: readonly Clause[], property: string): string[] {
  const out: string[] = [];
  for (const c of clauses) {
    if (c.property !== property) continue;
    if (c.op === "eq") out.push(String(c.value));
    if (c.op === "in" && Array.isArray(c.value)) out.push(...c.value.map(String));
  }
  return out;
}

/** Replace a property's chosen values. One is `eq` and several are `in`:
 * both mean the same on both stores, and `eq` is what a reader of the saved
 * document expects for a single choice. None removes the clause, since an
 * empty `in` is a filter that matches nothing. */
export function withValues(
  clauses: readonly Clause[], property: string, values: readonly string[],
): Clause[] {
  const rest = clauses.filter((c) => !(c.property === property && (c.op === "eq" || c.op === "in")));
  if (values.length === 0) return rest;
  return [...rest, values.length === 1
    ? { property, op: "eq", value: values[0] }
    : { property, op: "in", value: [...values] }];
}

export function toggleValue(
  clauses: readonly Clause[], property: string, value: string,
): Clause[] {
  const current = valuesOf(clauses, property);
  return withValues(clauses, property, current.includes(value)
    ? current.filter((v) => v !== value) : [...current, value]);
}

export function keywordOf(clauses: readonly Clause[], property: string): string {
  const c = clauses.find((x) => x.property === property && x.op === "starts_with");
  return c ? String(c.value ?? "") : "";
}

/** p.446's keyword search, as a prefix: `starts_with` is the text operator
 * both stores answer from an index (`object_sets.py`). Blank removes it. */
export function withKeyword(clauses: readonly Clause[], property: string, text: string): Clause[] {
  const rest = clauses.filter((c) => !(c.property === property && c.op === "starts_with"));
  return text.trim() ? [...rest, { property, op: "starts_with", value: text }] : rest;
}

/** `day` moved by whole days, or null when it is not a `YYYY-MM-DD` - which
 * is also how an unfinished picker is told apart from a chosen day. */
export function shiftDay(day: string, days: number): string | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return null;
  const t = Date.parse(`${day}T00:00:00Z`);
  if (Number.isNaN(t)) return null;
  return new Date(t + days * 86_400_000).toISOString().slice(0, 10);
}

export interface DayRange { from: string; to: string }

/** The range a property's date picker shows, read from what it wrote. */
export function rangeOf(clauses: readonly Clause[], property: string): DayRange {
  let from = "";
  let to = "";
  for (const c of clauses) {
    if (c.property !== property) continue;
    if (c.op === "gte") from = String(c.value ?? "").slice(0, 10);
    if (c.op === "lt") to = shiftDay(String(c.value ?? "").slice(0, 10), -1) ?? "";
  }
  return { from, to };
}

/**
 * A range of whole days, **both ends included**, as `gte` the first and `lt`
 * the day after the last. Not `lte` the last: a bare date is midnight UTC to
 * the server (`object_sets._instant`), so `lte 2024-03-31` on a timestamp
 * would drop everything that happened on the 31st after midnight.
 */
export function withRange(
  clauses: readonly Clause[], property: string, range: DayRange,
): Clause[] {
  const rest = clauses.filter((c) => !(c.property === property && ORDERED_OPERATORS.includes(c.op)));
  const out = [...rest];
  if (shiftDay(range.from, 0)) out.push({ property, op: "gte", value: range.from });
  const end = shiftDay(range.to, 1);
  if (end) out.push({ property, op: "lt", value: end });
  return out;
}

/** How wide a histogram bar is: its share of the largest, never zero for a
 * value that has rows, so a rare value is still a bar and not a gap. */
export function barWidth(count: number, max: number): number {
  if (max <= 0 || count <= 0) return 0;
  return Math.max(2, Math.round((count / max) * 100));
}

/** p.449's two layouts. */
export const FILTER_LAYOUTS = ["vertical", "pills"] as const;
export type FilterLayout = (typeof FILTER_LAYOUTS)[number];

export function layoutOf(value: unknown): FilterLayout {
  return value === "pills" ? "pills" : "vertical";
}

/** What a filter a viewer adds is drawn as: a date range on a date, since a
 * histogram of timestamps is one bar per instant, and a histogram otherwise. */
export function defaultComponentFor(dataType: string | null | undefined): FilterComponent {
  return componentsFor(dataType).includes("dateRange") ? "dateRange" : "histogram";
}

/**
 * The clauses without the ones this filter wrote. **Removing a filter takes
 * its clauses with it**: a filter a viewer removed but whose clause stayed
 * would go on narrowing the set with nothing on screen to say so, or to undo.
 */
export function withoutFilter(clauses: readonly Clause[], spec: FilterSpec): Clause[] {
  switch (spec.component) {
    case "keyword":
      return withKeyword(clauses, spec.property, "");
    case "dateRange":
      return withRange(clauses, spec.property, { from: "", to: "" });
    default:
      return withValues(clauses, spec.property, []);
  }
}

/**
 * The filters a viewer sees: the module's, less the ones they removed, plus
 * the ones they added. **Runtime state, never saved** (decision 0002 §3): p.449
 * lets users "add and remove filterable properties", which changes what they
 * see and not what the module is for the next person.
 */
export function visibleFilters(
  configured: readonly FilterSpec[], added: readonly FilterSpec[], removed: ReadonlySet<string>,
): FilterSpec[] {
  return [...configured, ...added].filter((f) => !removed.has(f.id));
}

/** An id for a filter a viewer adds, distinct from every configured one so a
 * removal cannot hit the wrong filter. */
export function viewerFilterId(taken: readonly FilterSpec[]): string {
  const ids = new Set(taken.map((f) => f.id));
  let n = 1;
  while (ids.has(`u_${n}`)) n += 1;
  return `u_${n}`;
}

/** What a pill says about its filter while closed (p.449's Pills layout), so
 * a row of pills reads as the filters applied without opening each one. */
export function pillSummary(spec: FilterSpec, clauses: readonly Clause[]): string {
  if (spec.component === "keyword") {
    const text = keywordOf(clauses, spec.property);
    return text ? `starts with “${text}”` : "";
  }
  if (spec.component === "dateRange") {
    const { from, to } = rangeOf(clauses, spec.property);
    if (from && to) return `${from} – ${to}`;
    if (from) return `from ${from}`;
    if (to) return `to ${to}`;
    return "";
  }
  return valuesOf(clauses, spec.property).join(", ");
}
