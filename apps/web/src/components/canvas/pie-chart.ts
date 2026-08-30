/** p.309-310's Pie Chart: "visualize objects data in a pie or donut chart via
 * grouping of objects by a specified property type into proportional slices".
 *
 * > "**Group by**: Select the property type used for grouping the object set
 * > where each property type value will be represented by a slice. **Enable
 * > ontology colors**: If toggled on, the widget will use the conditional
 * > formatting rules set for that property in the Ontology. **Aggregation**:
 * > … **Radius**: The inner radius of the space within the chart can be
 * > adjusted to switch chart's visualization from a pie to a donut chart.
 * > **Legend**: … The legend can be displayed to the left, right, top, or
 * > bottom relative to the chart. **Segment display**: … Segment value …
 * > Legend label … Color … Hide series." (p.310)
 *
 * ---
 *
 * **The geometry lives here rather than in the component**, and that is the
 * point of the file. `charts.tsx` has drawn a pie since Chart XY, with the
 * angle arithmetic inline in JSX where nothing but a browser could reach it —
 * so "does a 30% slice actually cover 30%" was a question no test had ever
 * asked. It is asked here now, and Chart XY's pie renders through the same
 * functions: one pie, two widgets, rather than two pies that agree until one
 * of them is changed.
 */

/** p.310's Aggregation.
 *
 * **Count only, and that is decision 0006 rather than a shortcut.** p.310 lists
 * average, count, min, max, sum and approximate unique count;
 * `object_sets.AGGREGATIONS` offers count and count_distinct over a set, and
 * the *grouped* endpoint offers count alone — because instance properties are
 * stored untyped, so Postgres and OpenSearch would disagree about what a sum
 * of them is. A pie whose slices were sums the two stores computed differently
 * would be a picture of a disagreement.
 */
export const AGGREGATIONS: Record<string, string> = {
  count: "Count of objects",
};

export const DEFAULT_AGGREGATION = "count";

export function aggregationOf(raw: unknown): string {
  return typeof raw === "string" && Object.hasOwn(AGGREGATIONS, raw)
    ? raw
    : DEFAULT_AGGREGATION;
}

/** p.310's legend positions. */
export const LEGEND_POSITIONS: Record<string, string> = {
  right: "Right",
  left: "Left",
  top: "Top",
  bottom: "Bottom",
};

export const DEFAULT_LEGEND_POSITION = "right";

export function legendPositionOf(raw: unknown): string {
  return typeof raw === "string" && Object.hasOwn(LEGEND_POSITIONS, raw)
    ? raw
    : DEFAULT_LEGEND_POSITION;
}

/** p.310's "Show legend", **on by default**: a pie with no legend is a picture
 * of coloured wedges nobody can name, and every slice's identity is in it. */
export function showLegendOf(raw: unknown): boolean {
  return raw !== false;
}

/** p.310's Radius, as a fraction of the outer radius.
 *
 * Capped short of 1 because a ring of zero width is not a chart — and clamped
 * at 0, which is p.310's pie rather than its donut.
 */
export const MAX_INNER_RADIUS = 0.9;

export function innerRadiusOf(raw: unknown): number {
  const value = Number(raw);
  if (!Number.isFinite(value)) return 0;
  return Math.min(MAX_INNER_RADIUS, Math.max(0, value));
}

/** One of p.310's Segment display overrides. */
export interface Segment {
  /** p.310's "Segment value: Enter the label key for the segment". */
  value: string;
  label?: string;
  color?: string;
  hidden?: boolean;
}

/** What a saved document's segment overrides amount to.
 *
 * Tolerant for §212's reason — this prop is an array of objects and the raw
 * JSON editor can hold anything. An entry naming no segment is dropped rather
 * than silently overriding the slice whose value happens to be `""`.
 */
export function segmentsOf(raw: unknown): Segment[] {
  if (!Array.isArray(raw)) return [];
  const out: Segment[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== "object") continue;
    const item = entry as Partial<Segment>;
    if (typeof item.value !== "string" || !item.value) continue;
    out.push({
      value: item.value,
      ...(typeof item.label === "string" && item.label.trim()
        ? { label: item.label.trim() } : {}),
      ...(typeof item.color === "string" && item.color.trim()
        ? { color: item.color.trim() } : {}),
      ...(item.hidden === true ? { hidden: true } : {}),
    });
  }
  return out;
}

/** A grouped count, as `/object-sets/group` returns one. */
export interface Group {
  value: string;
  count: number;
}

export interface Slice {
  value: string;
  label: string;
  count: number;
  /** p.310's per-segment colour, or `null` to take the palette's. */
  color: string | null;
}

/** The slices to draw, in the order the server grouped them.
 *
 * p.310's hidden segments are dropped here rather than drawn transparently,
 * because the *proportions* change: a hidden slice that still occupied its
 * angle would leave a gap, and one that kept its share of the total would make
 * every other slice smaller than the number beside it.
 */
export function visibleSlices(
  groups: readonly Group[], segments: readonly Segment[],
): Slice[] {
  const overrides = new Map(segments.map((s) => [s.value, s] as const));
  const out: Slice[] = [];
  for (const group of groups) {
    const override = overrides.get(group.value);
    if (override?.hidden) continue;
    out.push({
      value: group.value,
      label: override?.label ?? group.value,
      count: Math.max(0, group.count),
      color: override?.color ?? null,
    });
  }
  return out;
}

export interface Wedge {
  slice: Slice;
  /** Radians, clockwise from twelve o'clock. */
  start: number;
  end: number;
  /** The slice's fraction of the whole, 0 to 1. */
  share: number;
}

/** Where each slice starts and ends.
 *
 * **From twelve o'clock**, which is where every pie chart anybody has read
 * starts, and clockwise. A slice's share is of the *visible* total: p.310's
 * hidden segments are already gone by here, so the remaining slices fill the
 * circle rather than leaving a hole where one used to be.
 */
export function wedges(slices: readonly Slice[]): Wedge[] {
  const total = slices.reduce((sum, s) => sum + Math.max(0, s.count), 0);
  if (total <= 0) return [];
  let angle = -Math.PI / 2;
  return slices.map((slice) => {
    const share = Math.max(0, slice.count) / total;
    const start = angle;
    const end = angle + share * Math.PI * 2;
    angle = end;
    return { slice, start, end, share };
  });
}

/** A point on a circle, for the arc endpoints below. */
export function pointOnCircle(
  cx: number, cy: number, r: number, angle: number,
): { x: number; y: number } {
  return { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) };
}

function round(value: number): number {
  return Math.round(value * 100) / 100;
}

export interface ArcInput {
  cx: number;
  cy: number;
  /** The outer radius, in the same units as `cx`. */
  r: number;
  /** p.310's inner radius as a *fraction* of `r`; 0 is a pie. */
  inner: number;
  start: number;
  end: number;
}

/** One slice as an SVG path.
 *
 * Three shapes, and each is a case the others get wrong:
 *
 * * **a wedge** — the ordinary slice, from the centre out;
 * * **an annulus segment** — the same with p.310's inner radius, which is two
 *   arcs joined rather than a wedge with a hole;
 * * **a whole circle**, because an arc from a point back to *itself* draws
 *   nothing at all. One group is a real and common state — every object has
 *   the same status — so a chart that vanished for it would look broken on the
 *   tidiest possible data.
 */
export function arcPath({ cx, cy, r, inner, start, end }: ArcInput): string {
  const ri = r * Math.min(Math.max(inner, 0), MAX_INNER_RADIUS);
  const large = end - start > Math.PI ? 1 : 0;
  const full = end - start >= Math.PI * 2 - 1e-9;
  const outerStart = pointOnCircle(cx, cy, r, start);
  const outerEnd = pointOnCircle(cx, cy, r, full ? end - 1e-3 : end);
  const parts: string[] = [];

  if (ri <= 0) {
    if (full) {
      return [
        `M ${round(outerStart.x)} ${round(outerStart.y)}`,
        `A ${round(r)} ${round(r)} 0 1 1 ${round(outerEnd.x)} ${round(outerEnd.y)}`,
        "Z",
      ].join(" ");
    }
    parts.push(`M ${round(cx)} ${round(cy)}`);
    parts.push(`L ${round(outerStart.x)} ${round(outerStart.y)}`);
    parts.push(`A ${round(r)} ${round(r)} 0 ${large} 1 ${round(outerEnd.x)} ${round(outerEnd.y)}`);
    parts.push("Z");
    return parts.join(" ");
  }

  const innerStart = pointOnCircle(cx, cy, ri, full ? end - 1e-3 : end);
  const innerEnd = pointOnCircle(cx, cy, ri, start);
  return [
    `M ${round(outerStart.x)} ${round(outerStart.y)}`,
    `A ${round(r)} ${round(r)} 0 ${full ? 1 : large} 1`
      + ` ${round(outerEnd.x)} ${round(outerEnd.y)}`,
    `L ${round(innerStart.x)} ${round(innerStart.y)}`,
    // Back the other way — sweep 0 — or the inner edge crosses the outer one
    // and the browser fills the shape inside out.
    `A ${round(ri)} ${round(ri)} 0 ${full ? 1 : large} 0`
      + ` ${round(innerEnd.x)} ${round(innerEnd.y)}`,
    "Z",
  ].join(" ");
}

/** A slice's share, as a reader sees it.
 *
 * One decimal place, because two slices that differ by a fifth of a percent
 * are indistinguishable on screen and printing `33.333333%` beside them is
 * precision nobody can act on.
 */
export function percentLabel(share: number): string {
  return `${(share * 100).toFixed(1)}%`;
}
