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

import { sortPoints, type ChartSort } from "./chart-display";

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

/** p.281's Stacked area (§601): each segment's line drawn at the running
 * total of the segments before it and itself, so the bands between lines are
 * each segment's own values. A missing value stacks as nothing - a band can
 * be empty, and a stack cannot have a hole in it. */
export function stackSegments(data: Segmented): Segmented {
  return {
    ...data,
    values: data.values.map((row) => {
      let total = 0;
      return row.map((value) => (total += Number.isNaN(value) ? 0 : value));
    }),
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
export function segmentLayout(data: Segmented, mode: SegmentMode, stacks?: readonly number[]): {
  bars: SegmentBar[];
  max: number;
} {
  if (stacks) return stackedGroups(data, stacks);
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

/**
 * p.284's legend **Positioning options** and p.282's **Display override**, on
 * the segmented chart's legend (§539).
 *
 * > "Show legend: Toggles display of a legend of chart series' titles and
 * > series' colors. Positioning options: When "Show legend" is enabled,
 * > controls the positioning of the legend within the chart." (p.284)
 * >
 * > "Display override: Optional. Overrides the legend display name of the
 * > current series. For segmented charts, overrides the legend display name
 * > of a single segment." (p.282)
 *
 * p.284 does not list the positions; these are the four p.310 gives the Pie
 * Chart's legend, which is the same idea on the page next door.
 */
export const SEGMENT_LEGEND_POSITIONS = {
  bottom: "Bottom", top: "Top", left: "Left", right: "Right",
} as const;
export type SegmentLegendPosition = keyof typeof SEGMENT_LEGEND_POSITIONS;

/** Bottom unless set: where every segmented chart's legend was before. */
export function segmentLegendPositionOf(raw: unknown): SegmentLegendPosition {
  return typeof raw === "string" && Object.hasOwn(SEGMENT_LEGEND_POSITIONS, raw)
    ? (raw as SegmentLegendPosition) : "bottom";
}

/** Entries to a row above or below the plot; a side legend is one column. */
export const LEGEND_PER_ROW = 6;
export const LEGEND_ROW = 16;
export const LEGEND_ENTRY_WIDTH = 96;
export const LEGEND_SIDE_WIDTH = 120;

export interface Inset { top: number; right: number; bottom: number; left: number }

/** How much of the chart's frame the legend takes, on which side. */
export function legendInset(count: number, position: SegmentLegendPosition): Inset {
  const inset = { top: 0, right: 0, bottom: 0, left: 0 };
  if (count === 0) return inset;
  if (position === "left" || position === "right") {
    inset[position] = LEGEND_SIDE_WIDTH;
  } else {
    inset[position] = Math.ceil(count / LEGEND_PER_ROW) * LEGEND_ROW + 6;
  }
  return inset;
}

/** Where the `index`th entry's swatch baseline sits. Rows fill left to right
 * from the top of the legend; a side legend is a column from the plot's top. */
export function legendEntryAt(
  index: number, count: number, position: SegmentLegendPosition,
  plot: { x: number; y: number }, frame: { width: number; height: number },
): { x: number; y: number } {
  if (position === "left" || position === "right") {
    return {
      x: position === "left" ? 8 : frame.width - LEGEND_SIDE_WIDTH + 8,
      y: plot.y + 10 + index * LEGEND_ROW,
    };
  }
  const rows = Math.ceil(count / LEGEND_PER_ROW);
  const row = Math.floor(index / LEGEND_PER_ROW);
  const top = position === "top" ? 14 : frame.height - 6 - (rows - 1) * LEGEND_ROW;
  return { x: plot.x + (index % LEGEND_PER_ROW) * LEGEND_ENTRY_WIDTH, y: top + row * LEGEND_ROW };
}

/** A segment's name in the legend and its tooltip: its override when it has
 * one, else its value. A blank override is none, as a blank axis title is. */
export function segmentName(value: string, names: unknown): string {
  if (typeof names !== "object" || names === null || Array.isArray(names)) return value;
  // Anything inherited ("toString") is a function, never a string, so the
  // type check is all the own-property check there needs to be.
  const own = (names as Record<string, unknown>)[value];
  return typeof own === "string" && own.trim() !== "" ? own.trim() : value;
}

/**
 * p.283's **Sort by** on a segmented chart (§540), which the panel offered and
 * the chart ignored: §468 sorted a plain chart's points, and a segmented one
 * is drawn from the cross-tab's grid instead.
 *
 * A category is ordered by its bar's whole height, the total of its segments,
 * which is the "charted value" p.283 sorts; by key, it is ordered as a plain
 * chart's keys are. Each row of the grid travels with its category.
 */
export function sortSegmented(data: Segmented, sort: ChartSort): Segmented {
  const totals = data.categories.map((label, i) => ({
    label, value: (data.values[i] ?? []).reduce((sum, v) => sum + v, 0), index: i,
  }));
  const order = sortPoints(totals, sort) as typeof totals;
  return {
    categories: order.map((c) => c.label),
    segments: data.segments,
    values: order.map((c) => data.values[c.index] ?? []),
  };
}


/**
 * Layers side by side, each stacked by its own segments (§678; p.282's
 * Segment by on a layer): `stacks[segment]` names the group a column belongs
 * to, the groups share a category's slot in the order they first appear, and
 * each group piles its columns from zero. The axis reaches the tallest pile.
 */
function stackedGroups(data: Segmented, stacks: readonly number[]): { bars: SegmentBar[]; max: number } {
  const groups = [...new Set(stacks)];
  const n = Math.max(groups.length, 1);
  const bars: SegmentBar[] = [];
  let max = 0;
  data.values.forEach((row, category) => {
    const running = new Map<number, number>();
    row.forEach((value, segment) => {
      if (!(value > 0)) return;
      const group = groups.indexOf(stacks[segment]!);
      const from = running.get(group) ?? 0;
      running.set(group, from + value);
      bars.push({ category, segment, from, to: from + value, offset: group / n, width: 1 / n, value });
      max = Math.max(max, from + value);
    });
  });
  return { bars, max };
}
