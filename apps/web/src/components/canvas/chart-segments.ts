/**
 * p.281–282's **Segment by** and **Segment overrides** on Chart XY (§467).
 *
 * > "Segment by: Optional. Enables each plotted value to be segmented by a
 * > secondary property type. As an example, if "Alert Type" was selected as
 * > the X axis property and then "Aircraft Type" was selected as the Segment by
 * > option on a bar chart, each bar would show the count of objects of each
 * > "Alert Type" segmented by each "Aircraft Type"." (p.281–282)
 * >
 * > "Segment overrides: Only available for Bar chart. Modifies how each bar
 * > chart value is displayed. Options include: "Stacked," "Percentage," and
 * > "Grouped."" (p.282)
 *
 * The data is `/object-sets/cross-tab`'s: a grid of counts, categories by
 * segments, which is the same grouping a Pivot Table draws - so a segmented bar
 * and a pivot cell over the same two properties are one number.
 */

export const SEGMENT_MODES = {
  stacked: "Stacked",
  percentage: "Percentage",
  grouped: "Grouped",
} as const;
export type SegmentMode = keyof typeof SEGMENT_MODES;

export function segmentModeOf(raw: unknown): SegmentMode {
  return typeof raw === "string" && Object.hasOwn(SEGMENT_MODES, raw)
    ? (raw as SegmentMode) : "stacked";
}

export interface Segmented {
  categories: string[];
  segments: string[];
  /** `values[category][segment]`. */
  values: number[][];
}

/** The cross-tab's answer as categories and segments. A grid whose rows are
 * not as long as its columns is read as zeroes where it is short, rather than
 * as a bar that silently stops. */
export function segmentedFrom(crossTab: {
  rows: { value: string }[];
  columns: { value: string }[];
  cells: number[][];
}): Segmented {
  const segments = crossTab.columns.map((c) => c.value);
  return {
    categories: crossTab.rows.map((r) => r.value),
    segments,
    values: crossTab.rows.map((_, i) =>
      segments.map((_, j) => Number(crossTab.cells[i]?.[j] ?? 0) || 0)),
  };
}

/** One rectangle, in value space: from `from` to `to` on the value axis, and
 * across `offset`..`offset + width` of its category's slot (0..1). */
export interface SegmentBar {
  category: number;
  segment: number;
  from: number;
  to: number;
  offset: number;
  width: number;
  value: number;
}

/**
 * Where each segment's rectangle goes, and how tall the axis must be.
 *
 * - **Stacked** piles a category's segments from zero; the axis reaches the
 *   largest category's total.
 * - **Percentage** piles them as shares of their category, so every bar is the
 *   same height and the axis is 0 to 1. A category with nothing in it has no
 *   shares and draws no bar, rather than dividing by zero into a full one.
 * - **Grouped** puts them side by side from zero; the axis reaches the largest
 *   single segment.
 *
 * An empty segment is left out: a zero-height rectangle is a click target and
 * a tooltip with nothing to show.
 */
export function segmentLayout(data: Segmented, mode: SegmentMode): {
  bars: SegmentBar[];
  max: number;
} {
  const bars: SegmentBar[] = [];
  let max = 0;
  const n = Math.max(data.segments.length, 1);
  data.values.forEach((row, category) => {
    const total = row.reduce((sum, v) => sum + v, 0);
    let running = 0;
    row.forEach((value, segment) => {
      if (value <= 0) return;
      if (mode === "grouped") {
        bars.push({ category, segment, from: 0, to: value, offset: segment / n, width: 1 / n, value });
        max = Math.max(max, value);
        return;
      }
      const scale = mode === "percentage" ? total : 1;
      bars.push({
        category, segment, from: running / scale, to: (running + value) / scale,
        offset: 0, width: 1, value,
      });
      running += value;
    });
    max = Math.max(max, mode === "percentage" ? (total > 0 ? 1 : 0) : running);
  });
  return { bars, max };
}
