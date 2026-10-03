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
  "histogram", "singleSelect", "multiSelect", "keyword", "distribution", "date", "dateRange",
  "timeline",
] as const;
export type FilterComponent = (typeof FILTER_COMPONENTS)[number];

export const FILTER_COMPONENT_LABELS: Record<FilterComponent, string> = {
  histogram: "Histogram",
  singleSelect: "Single-select dropdown",
  multiSelect: "Multi-select dropdown",
  keyword: "Keyword",
  distribution: "Distribution chart",
  date: "Single date",
  dateRange: "Date range",
  timeline: "Timeline",
};

/** p.449's date pickers are for dates; offering one on a string would write a
 * range the server refuses, because only declared dates and numbers order. */
export const DATE_TYPES = ["date", "timestamp"] as const;

/** And a distribution is for numbers: its bars are ranges between the set's
 * smallest and largest value, which the server takes from `min` and `max`
 * (`object_sets.distributable_type`). */
export const NUMBER_TYPES = ["integer", "float"] as const;

export interface FilterSpec {
  id: string;
  property: string;
  component: FilterComponent;
  /** p.452's search type for a keyword filter (§543): absent is the plain
   * prefix search, "advanced" the syntax with AND, OR, NOT and brackets, and
   * "regex" `ontology` p.130's regular expression (§728). */
  syntax?: "advanced" | "regex";
  /** p.451's filter on a link (§545): the link type followed, and the type
   * it reaches from the set's own, whose `property` this filter reads. An
   * empty `property` is p.451's Has link. */
  link?: string;
  linkTo?: string;
}

export function componentOf(value: unknown): FilterComponent {
  return (FILTER_COMPONENTS as readonly unknown[]).includes(value)
    ? (value as FilterComponent) : "histogram";
}

/** The components a property of this declared type can be drawn as. */
export function componentsFor(dataType: string | null | undefined): FilterComponent[] {
  const dated = (DATE_TYPES as readonly (string | null | undefined)[]).includes(dataType);
  const numeric = (NUMBER_TYPES as readonly (string | null | undefined)[]).includes(dataType);
  return FILTER_COMPONENTS.filter((c) => {
    if (c === "date" || c === "dateRange" || c === "timeline") return dated;
    if (c === "distribution") return numeric;
    return true;
  });
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
        // A linked filter's empty property is its Has link (§545), and a
        // link is only one with the type it reaches.
        && typeof (f as FilterSpec).property === "string"
        && (!!(f as FilterSpec).property
          || (!!(f as FilterSpec).link && !!(f as FilterSpec).linkTo)))
      .map((f) => ({
        id: f.id as string, property: f.property as string, component: componentOf(f.component),
        ...(f.syntax === "advanced" || f.syntax === "regex"
          ? { syntax: f.syntax as "advanced" | "regex" } : {}),
        ...(typeof f.link === "string" && f.link && typeof f.linkTo === "string" && f.linkTo
          ? { link: f.link, linkTo: f.linkTo } : {}),
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

/** A keyword filter's clause: the plain search's prefix, or p.452's
 * advanced query (§543), which is the same prefix terms combined. */
const KEYWORD_OPS = ["starts_with", "keyword_query", "matches_regex"];

export function keywordOf(clauses: readonly Clause[], property: string): string {
  const c = clauses.find((x) => x.property === property && KEYWORD_OPS.includes(x.op));
  return c ? String(c.value ?? "") : "";
}

/** p.446's keyword search, as a prefix: `starts_with` is the text operator
 * both stores answer from an index (`object_sets.py`). Blank removes it.
 * **Advanced**, it is p.452's query instead, and replaces a plain one on the
 * same property rather than ANDing with it: one box, one search. **A regular
 * expression** (§728; `ontology` p.130) is `matches_regex`, likewise. */
export function withKeyword(
  clauses: readonly Clause[], property: string, text: string,
  syntax: boolean | "advanced" | "regex" = false,
): Clause[] {
  const rest = clauses.filter((c) => !(c.property === property && KEYWORD_OPS.includes(c.op)));
  if (!text.trim()) return rest;
  const op = syntax === "regex" ? "matches_regex" : syntax ? "keyword_query" : "starts_with";
  return [...rest, { property, op, value: text }];
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
  if (spec.link) {
    // A linked filter's clauses live inside its link's `has_link` (§545).
    if (!spec.property) return withHasLink(clauses, spec.link, false);
    const far = withoutFilter(linkedClausesOf(clauses, spec.link), { ...spec, link: undefined });
    return withLinked(clauses, spec.link, far);
  }
  switch (spec.component) {
    case "keyword":
      return withKeyword(clauses, spec.property, "");
    case "dateRange":
    case "date":
    case "timeline":
    case "distribution":
      // All three write ordered comparisons, and clearing a range clears them.
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
  if (spec.link) {
    // A linked filter summarises its own clauses, inside its link's (§545).
    if (!spec.property) return hasLinkOf(clauses, spec.link) ? "has a link" : "";
    return pillSummary({ ...spec, link: undefined }, linkedClausesOf(clauses, spec.link));
  }
  if (spec.component === "keyword") {
    const text = keywordOf(clauses, spec.property);
    return text ? `starts with “${text}”` : "";
  }
  if (spec.component === "distribution") return numberRangeSummary(clauses, spec.property);
  if (spec.component === "date") return rangeOf(clauses, spec.property).from;
  if (spec.component === "dateRange" || spec.component === "timeline") {
    const { from, to } = rangeOf(clauses, spec.property);
    if (from && to) return `${from} – ${to}`;
    if (from) return `from ${from}`;
    if (to) return `to ${to}`;
    return "";
  }
  return valuesOf(clauses, spec.property).join(", ");
}

/** One bar of p.449's distribution chart, as `/object-sets/distribution`
 * returns it: `[low, high)`, or `[low, high]` when `closed`. */
export interface NumberBucket {
  low: number;
  high: number;
  closed: boolean;
  count: number;
}

/** What a bar is called. An integer bucket's `high` is the next integer past
 * its last value, so 1 to 26 reads "1–25"; a float's reads as its edges. */
export function bucketLabel(bucket: NumberBucket, integer: boolean): string {
  if (integer) {
    const last = bucket.high - 1;
    return last === bucket.low ? `${bucket.low}` : `${bucket.low}–${last}`;
  }
  return `${edge(bucket.low)}–${edge(bucket.high)}`;
}

/** A float edge to four significant figures: 0.30000000000000004 is a
 * rounding, not a boundary anybody chose. */
function edge(n: number): string {
  return Number(n.toPrecision(4)).toString();
}

/** The smallest and largest value under the chart, as its axis. */
export function axisEnds(bars: readonly NumberBucket[], integer: boolean): [string, string] {
  const first = bars[0];
  const last = bars[bars.length - 1];
  if (!first || !last) return ["", ""];
  return integer
    ? [`${first.low}`, `${last.high - 1}`]
    : [edge(first.low), edge(last.high)];
}

/** Whether this bar is the range a property's clauses select. */
export function isBucketChosen(
  clauses: readonly Clause[], property: string, bucket: NumberBucket,
): boolean {
  const on = (op: string) => clauses.some((c) =>
    c.property === property && c.op === op && Number(c.value) === (op === "gte" ? bucket.low : bucket.high));
  return on("gte") && on(bucket.closed ? "lte" : "lt");
}

/** Choose a bar, or none: the property's ordered clauses become the bar's two.
 * One bar at a time, which is what a click on a chart means. */
export function withBucket(
  clauses: readonly Clause[], property: string, bucket: NumberBucket | null,
): Clause[] {
  const rest = clauses.filter((c) => !(c.property === property && ORDERED_OPERATORS.includes(c.op)));
  if (!bucket) return rest;
  return [...rest,
    { property, op: "gte", value: bucket.low },
    { property, op: bucket.closed ? "lte" : "lt", value: bucket.high }];
}

/** What a chosen bar's pill says, from the clauses alone - the pill has no
 * buckets to look the label up in until it is opened. */
export function numberRangeSummary(clauses: readonly Clause[], property: string): string {
  let low: string | null = null;
  let high: string | null = null;
  for (const c of clauses) {
    if (c.property !== property) continue;
    if (c.op === "gte") low = String(c.value);
    if (c.op === "lt") high = `< ${String(c.value)}`;
    if (c.op === "lte") high = `≤ ${String(c.value)}`;
  }
  if (low !== null && high !== null) return `≥ ${low}, ${high}`;
  if (low !== null) return `≥ ${low}`;
  return high ?? "";
}

/** One column of p.449's timeline, as `/object-sets/time-series` returns it
 * for a date property (§466): the start of a calendar day, week or month. */
export interface TimelinePoint {
  start: string;
  count: number;
}

export const TIMELINE_INTERVALS = ["day", "week", "month"] as const;
export type TimelineInterval = (typeof TIMELINE_INTERVALS)[number];

/** The whole days a column covers, as the date range's two ends - so choosing
 * a column is choosing that range, with the same both-ends-in rule and the
 * same clauses a date range writes (`withRange`). */
export function periodOf(start: string, interval: TimelineInterval): DayRange {
  const from = start.slice(0, 10);
  if (!shiftDay(from, 0)) return { from: "", to: "" };
  if (interval === "day") return { from, to: from };
  if (interval === "week") return { from, to: shiftDay(from, 6)! };
  const [y, m] = from.split("-").map(Number) as [number, number];
  // The day before the first of the next month, whatever this month's length.
  const next = new Date(Date.UTC(y, m, 1)).toISOString().slice(0, 10);
  return { from, to: shiftDay(next, -1)! };
}

/** What a column is called: its day, the week it starts, or its month. */
export function periodLabel(start: string, interval: TimelineInterval): string {
  const from = start.slice(0, 10);
  if (interval === "month") return from.slice(0, 7);
  if (interval === "week") return `week of ${from}`;
  return from;
}

/** Whether a column is the range a property's clauses select. */
export function isPeriodChosen(
  clauses: readonly Clause[], property: string, start: string, interval: TimelineInterval,
): boolean {
  const chosen = rangeOf(clauses, property);
  const period = periodOf(start, interval);
  return !!period.from && chosen.from === period.from && chosen.to === period.to;
}

export function timelineIntervalOf(value: unknown): TimelineInterval {
  return (TIMELINE_INTERVALS as readonly unknown[]).includes(value)
    ? (value as TimelineInterval) : "day";
}

/**
 * p.451's filters on linked objects, as the clauses a Filter List writes
 * (§545; `object_sets.LINK_OPERATORS`).
 *
 * > "The Has Link filter is unique to linked object filters and filters on
 * > the presence of a link. For example: "Filter for all Tasks that have a
 * > link to Person."" (p.451)
 *
 * **Two clauses per link, never merged.** Has link is a `has_link` with no
 * filters of its own; the values chosen on the linked type's properties are
 * one `has_link` carrying them all, so one linked object has to satisfy every
 * one ("a Person over 30 *in Leeds*", not a person over 30 and another in
 * Leeds). The server ANDs the two, which is Has link and more - and clearing
 * the values never takes away a Has link somebody ticked.
 */
export const HAS_LINK = "has_link";

interface LinkedValue { filters?: Clause[] }

function linkedFiltersOf(clause: Clause): Clause[] {
  const value = clause.value as LinkedValue | null;
  return Array.isArray(value?.filters) ? value!.filters! : [];
}

/** Whether the objects must have a link at all: the Has link box. */
export function hasLinkOf(clauses: readonly Clause[], link: string): boolean {
  return clauses.some((c) => c.op === HAS_LINK && c.property === link
    && linkedFiltersOf(c).length === 0);
}

export function withHasLink(clauses: readonly Clause[], link: string, on: boolean): Clause[] {
  const rest = clauses.filter((c) => !(c.op === HAS_LINK && c.property === link
    && linkedFiltersOf(c).length === 0));
  return on ? [...rest, { property: link, op: HAS_LINK, value: { filters: [] } }] : rest;
}

/** The linked type's own clauses, for the filters drawn on its properties. */
export function linkedClausesOf(clauses: readonly Clause[], link: string): Clause[] {
  const c = clauses.find((x) => x.op === HAS_LINK && x.property === link
    && linkedFiltersOf(x).length > 0);
  return c ? linkedFiltersOf(c) : [];
}

/** The linked type's clauses written back as one `has_link`, or none. */
export function withLinked(clauses: readonly Clause[], link: string, far: Clause[]): Clause[] {
  const rest = clauses.filter((c) => !(c.op === HAS_LINK && c.property === link
    && linkedFiltersOf(c).length > 0));
  return far.length ? [...rest, { property: link, op: HAS_LINK, value: { filters: far } }] : rest;
}

/**
 * p.451's display options for linked filters (§546).
 *
 * > "Inline: The inline display option will display the linked filters
 * > alongside non-linked filters (in the same grouping). Grouped: The grouped
 * > option will visually group linked filters into a section, adding an object
 * > icon and linked object count … Collapse by default: When enabled, this
 * > option will display the linked filter group as collapsed by default when
 * > the module is loaded." (p.451)
 */
export const LINK_DISPLAYS = { inline: "Inline", grouped: "Grouped" } as const;
export type LinkDisplay = keyof typeof LINK_DISPLAYS;

export function linkDisplayOf(raw: unknown): LinkDisplay {
  return raw === "grouped" ? "grouped" : "inline";
}

export interface FilterGroup {
  /** The link a section is for, or null for the filters on the set itself. */
  link: string | null;
  linkTo: string | null;
  specs: FilterSpec[];
}

/** The filters in the order they are drawn. Inline, one run in the order they
 * were added. Grouped, the set's own filters first and then a section per
 * link, in the order each link first appears - one per end, since a link
 * followed either way reaches a different type. */
export function groupFilters(specs: readonly FilterSpec[], display: LinkDisplay): FilterGroup[] {
  if (display === "inline") return [{ link: null, linkTo: null, specs: [...specs] }];
  const own: FilterSpec[] = [];
  const sections: FilterGroup[] = [];
  for (const spec of specs) {
    if (!spec.link) {
      own.push(spec);
      continue;
    }
    const section = sections.find((g) => g.link === spec.link && g.linkTo === spec.linkTo);
    if (section) section.specs.push(spec);
    else sections.push({ link: spec.link, linkTo: spec.linkTo ?? null, specs: [spec] });
  }
  return [{ link: null, linkTo: null, specs: own }, ...sections];
}

/**
 * A linked filter's name on its pill (§621; p.451): the linked type it reads,
 * then which of its properties - or p.451's "Has link" - the way a Grouped
 * layout heads its section with the type. A pill used to say the property's
 * api name alone, so two links reaching types with a `status` each drew two
 * pills called `status`.
 *
 * `farName` is `null` until the linked type has loaded, and the pill says
 * "Linked objects" meanwhile, as the group's heading does.
 */
export function linkedPillLabel(
  spec: Pick<FilterSpec, "property">,
  farName: string | null,
  propertyName?: string | null,
): string {
  const of = farName ?? "Linked objects";
  return spec.property ? `${of} · ${propertyName || spec.property}` : `${of} · Has link`;
}
